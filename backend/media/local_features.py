"""Local picture features, which still match when much of a picture has been cropped away.

Whole-picture fingerprints change once a crop removes much of the picture. These describe small patches instead,
and a match needs many patches to agree on one shift and resize, so they survive heavier crops. They don't survive
mirroring. A match shows that pictures share visible content, not who made them or which came first.
"""

from __future__ import annotations

import base64
from collections.abc import Iterable, Sequence
from typing import Any

MAX_SIDE = 640
MAX_FEATURES = 400
# Chosen on the calibration split only, in data/eval/crop_matching_2026-11-06.json.
MATCH_LIMIT = 9
# Each picture saves about 19 KB, so a video keeps only a few frames.
MAX_VIDEO_FRAMES = 4
_RATIO = 0.8
_MIN_CANDIDATES = 8
_REPROJECTION_PIXELS = 5.0
# A crop can enlarge a picture, but these limits refuse transforms no repost would make.
_MIN_SCALE, _MAX_SCALE = 0.4, 2.5
_DESCRIPTOR_BYTES = 32
_POINT_BYTES = 4


def compute_features(image: Any, max_features: int = MAX_FEATURES) -> str | None:
    """Describe a picture's patches as text for saving, or None if it has too little detail."""
    import cv2
    import numpy as np

    rgb = image.convert("L")
    scale = min(1.0, MAX_SIDE / max(rgb.size))
    if scale < 1.0:
        rgb = rgb.resize((max(1, int(rgb.width * scale)), max(1, int(rgb.height * scale))))
    orb = cv2.ORB_create(nfeatures=max_features)
    points, descriptors = orb.detectAndCompute(np.asarray(rgb), None)
    if descriptors is None or len(points) < _MIN_CANDIDATES:
        return None
    # Positions are in the reduced picture, so whole numbers are accurate enough.
    xy = np.array([point.pt for point in points], dtype=np.uint16)
    return base64.b64encode(xy.tobytes() + descriptors.tobytes()).decode("ascii")


def frame_features(images: Iterable[Any]) -> list[str]:
    """Describe up to ``MAX_VIDEO_FRAMES`` pictures spread evenly through a video, or one image."""
    pictures = list(images)
    step = max(1, len(pictures) / MAX_VIDEO_FRAMES)
    chosen = [pictures[int(index * step)] for index in range(min(len(pictures), MAX_VIDEO_FRAMES))]
    return [text for text in (compute_features(picture) for picture in chosen) if text]


def _load(text: str) -> tuple[Any, Any]:
    import numpy as np

    raw = base64.b64decode(text.encode("ascii"), validate=True)
    count = len(raw) // (_POINT_BYTES + _DESCRIPTOR_BYTES)
    if not count or len(raw) != count * (_POINT_BYTES + _DESCRIPTOR_BYTES):
        raise ValueError("Saved picture features have the wrong length.")
    xy = np.frombuffer(raw, dtype=np.uint16, count=count * 2).reshape(count, 2).astype(np.float32)
    descriptors = np.frombuffer(raw, dtype=np.uint8, offset=count * _POINT_BYTES).reshape(count, _DESCRIPTOR_BYTES)
    return xy, descriptors


def agreeing_features(left: str, right: str) -> int:
    """Count the patches that agree on one shift and resize between two pictures. Zero means no match was found."""
    try:
        import cv2
    except ImportError:
        return 0
    import numpy as np

    try:
        left_xy, left_descriptors = _load(left)
        right_xy, right_descriptors = _load(right)
    except ValueError:
        return 0
    pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(left_descriptors, right_descriptors, k=2)
    good = [pair[0] for pair in pairs if len(pair) == 2 and pair[0].distance < _RATIO * pair[1].distance]
    if len(good) < _MIN_CANDIDATES:
        return 0
    source = np.float32([left_xy[match.queryIdx] for match in good])
    target = np.float32([right_xy[match.trainIdx] for match in good])
    transform, kept = cv2.estimateAffinePartial2D(source, target, method=cv2.RANSAC, ransacReprojThreshold=_REPROJECTION_PIXELS)
    if transform is None or kept is None:
        return 0
    scale = float(np.hypot(transform[0, 0], transform[1, 0]))
    if not _MIN_SCALE <= scale <= _MAX_SCALE or abs(float(transform[1, 0])) > 0.2 * scale:
        return 0
    return int(kept.sum())


def best_agreement(left: Sequence[str], right: Sequence[str]) -> int:
    """The most patches agreeing between any picture of one case and any picture of another."""
    return max((agreeing_features(one, other) for one in left for other in right), default=0)
