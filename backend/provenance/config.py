from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_MB = 1024 * 1024
DEFAULT_VIDEO_SEARCH_FRAMES = 3
MAX_VIDEO_SEARCH_FRAMES = 8


def _frame_limit(raw: str | None) -> int:
    """Read how many video frames to search. Anything invalid keeps the default."""
    try:
        return max(1, min(MAX_VIDEO_SEARCH_FRAMES, int(raw))) if raw else DEFAULT_VIDEO_SEARCH_FRAMES
    except ValueError:
        return DEFAULT_VIDEO_SEARCH_FRAMES


@dataclass(frozen=True)
class ProvenanceConfig:
    # A provider runs only if its key is set. The keys never appear in repr or results.
    vision_api_key: str | None = field(default=None, repr=False)
    tineye_api_key: str | None = field(default=None, repr=False)
    serpapi_api_key: str | None = field(default=None, repr=False)

    # When set, results come from this recorded file and nothing touches the network.
    replay_path: Path | None = None

    max_candidates: int = 25
    max_results_per_provider: int = 30
    request_timeout_s: float = 6.0
    provider_timeout_s: float = 20.0
    # Total time for checking result pages and images, after the providers answer.
    check_budget_s: float = 20.0
    check_workers: int = 6
    max_page_bytes: int = 2 * _MB
    max_robots_bytes: int = 256 * 1024
    max_candidate_image_bytes: int = 10 * _MB
    max_candidate_image_pixels: int = 50_000_000
    max_redirects: int = 3

    # pHash distance at or under which a result counts as the same picture.
    same_image_distance: int = 5
    # Above this, a result the provider called exact looks like a different picture.
    related_image_distance: int = 12

    user_agent: str = "TrustFeed-Provenance/0.1 (research prototype)"

    # Each web search with visual matches spends a second SerpApi search.
    serpapi_visual_matches: bool = True
    # How many of a video's keyframes are searched. Each one spends its own searches.
    video_search_frames: int = 3
    # Results are saved here by the file's SHA-256, so searching again spends nothing. Not set means nothing is saved.
    cache_dir: Path | None = None
    cache_days: float = 30.0
    # The shortest time between two requests to one site. A site's own Crawl-delay can raise it, up to the cap.
    site_delay_s: float = 1.0
    max_site_delay_s: float = 10.0

    @classmethod
    def from_env(cls) -> ProvenanceConfig:
        def value(name: str) -> str | None:
            return os.environ.get(name, "").strip() or None

        replay = value("PROVENANCE_REPLAY_PATH")
        cache = value("PROVENANCE_CACHE_DIR")
        return cls(
            serpapi_visual_matches=(value("SERPAPI_VISUAL_MATCHES") or "1").casefold() in {"1", "true", "yes", "on"},
            video_search_frames=_frame_limit(value("PROVENANCE_VIDEO_FRAMES")),
            # Outside the repository by default, so saved results can't be committed by accident.
            cache_dir=Path(cache) if cache else Path.home() / ".cache" / "trustfeed" / "provenance",
            vision_api_key=value("GOOGLE_VISION_API_KEY"),
            tineye_api_key=value("TINEYE_API_KEY"),
            serpapi_api_key=value("SERPAPI_API_KEY"),
            replay_path=Path(replay) if replay else None,
        )
