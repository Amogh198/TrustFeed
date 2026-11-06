"""Compare the pictures on public posts already found, so altered reposts of one picture can be connected.

Public platforms can't be searched by image, so this only sees posts that a text, link or hashtag search or an
account history already found. Pictures are read through the protected HTTP client, reduced to hashes in memory,
and never saved. Only public thumbnails are fetched, and nothing from the submitted file is sent anywhere.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field

from backend.network.sources.base import PublicPost, safe_web_link

logger = logging.getLogger(__name__)

# Local features travel with a picture's hashes under this name, and never reach the coordination test.
FEATURES_KEY = "local_features"
MAX_IMAGES = 60
MAX_IMAGES_PER_POST = 4
TIME_BUDGET_SECONDS = 15
_REQUEST_TIMEOUT_SECONDS = 6
_MAX_BYTES = 8 * 1024 * 1024
_MAX_PIXELS = 40_000_000
_WORKERS = 6

# Returns a picture's hashes, or None if it can't be read. Tests pass their own.
ImageReader = Callable[[str], Mapping[str, str] | None]

IMAGE_LIMIT = (
    "Pictures were compared only on posts already found by text, link or hashtag, because these platforms can't be "
    "searched by image. Other reposts of this picture may exist."
)


@dataclass
class ImageReadout:
    # Hashes for one picture per post: the one like the submitted file if any, otherwise its first.
    by_post: dict[str, dict[str, str]] = field(default_factory=dict)
    same_as_submitted: set[str] = field(default_factory=set)
    read: int = 0
    failed: int = 0
    skipped: int = 0


def read_post_image(url: str) -> dict[str, str] | None:
    """Fetch one public picture safely and reduce it to hashes. The picture isn't kept."""
    from PIL import Image

    from backend.media.fingerprint import compute_fingerprints
    from backend.media.local_features import compute_features
    from backend.provenance.safe_http import HttpBlocked, HttpFailed, safe_request

    try:
        response = safe_request(url, timeout_s=_REQUEST_TIMEOUT_SECONDS, max_bytes=_MAX_BYTES, headers={"Accept": "image/*"})
    except (HttpBlocked, HttpFailed):
        return None
    if response.status != 200:
        return None
    try:
        with Image.open(io.BytesIO(response.body), formats=("JPEG", "PNG", "WEBP", "GIF")) as image:
            if image.width * image.height > _MAX_PIXELS:
                return None
            hashes = compute_fingerprints(image)
            features = compute_features(image)
            return {**hashes, FEATURES_KEY: features} if features else hashes
    except Exception as exc:  # noqa: BLE001 - A picture from the internet can be broken in any way.
        logger.info("A post's picture could not be read: %s", type(exc).__name__)
        return None


def _same_picture(left: Mapping[str, str], right: Mapping[str, str]) -> bool:
    from backend.media.fingerprint import same_picture

    return same_picture(dict(left), dict(right))


def _shares_content(features: str | None, submitted: Sequence[str]) -> bool:
    if not features or not submitted:
        return False
    from backend.media.local_features import MATCH_LIMIT, best_agreement

    return best_agreement([features], submitted) >= MATCH_LIMIT


def _wanted(posts: Iterable[PublicPost], on_topic: Mapping[str, str]) -> list[tuple[str, str]]:
    """List (post id, picture link), with posts that carry the content first."""
    ordered = sorted(posts, key=lambda post: (post.id not in on_topic, post.created_at, post.id))
    return [
        (post.id, link)
        for post in ordered
        for link in dict.fromkeys(item for item in (safe_web_link(raw) for raw in post.image_urls[:MAX_IMAGES_PER_POST]) if item)
    ]


def compare_post_images(
    posts: Iterable[PublicPost],
    on_topic: Mapping[str, str],
    submitted: Sequence[Mapping[str, str]],
    reader: ImageReader,
    time_budget_s: float = TIME_BUDGET_SECONDS,
    submitted_features: Sequence[str] = (),
) -> ImageReadout:
    """Hash each post's pictures within the limits, and note which look like the submitted file."""
    wanted = _wanted(posts, on_topic)
    readout = ImageReadout(skipped=max(0, len(wanted) - MAX_IMAGES))
    if not wanted:
        return readout
    executor = ThreadPoolExecutor(max_workers=_WORKERS)
    futures = {executor.submit(reader, link): post_id for post_id, link in wanted[:MAX_IMAGES]}
    try:
        for future in as_completed(futures, timeout=time_budget_s):
            post_id = futures[future]
            try:
                hashes = future.result()
            except Exception as exc:  # noqa: BLE001 - One bad picture must not lose the trace.
                logger.info("A post's picture failed: %s", type(exc).__name__)
                hashes = None
            if not hashes:
                readout.failed += 1
                continue
            readout.read += 1
            kept = dict(hashes)
            features = kept.pop(FEATURES_KEY, None)
            if any(_same_picture(kept, target) for target in submitted) or _shares_content(features, submitted_features):
                readout.same_as_submitted.add(post_id)
                readout.by_post[post_id] = kept
            else:
                readout.by_post.setdefault(post_id, kept)
    except FuturesTimeout:
        readout.skipped += sum(not future.done() for future in futures)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return readout
