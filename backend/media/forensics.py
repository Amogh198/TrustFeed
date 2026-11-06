"""Pixel forensics with OpenCV and NumPy: ELA, noise, compression and frequency.

Each test measures how the pixels behave. None of them can say an image is fake: ordinary sharpening,
re-saving, cropping and text overlays all move these numbers. They never change the overall score.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.media.config import MediaConfig
from backend.media.models import CheckStatus, ForensicRegion, ForensicsCheck, ForensicTest

# Uploads are never logged.
logger = logging.getLogger(__name__)

# Loaded on first use, so importing this package stays light and the app still starts without them.
cv2: Any = None
np: Any = None


def _ensure_libraries() -> bool:
    global cv2, np
    if cv2 is not None and np is not None:
        return True
    try:
        import cv2 as opencv
        import numpy as numpy_module
    except ImportError:
        return False
    cv2, np = opencv, numpy_module
    return True


ELA = "ela"
NOISE_UNEVENNESS = "noise_unevenness"
NOISE_LEVEL = "noise_level"
COMPRESSION_GHOST = "compression_ghost"
COMPRESSION_GRID = "compression_grid"
FREQUENCY_DETAIL = "frequency_detail"
FREQUENCY_PEAKS = "frequency_peaks"
TEST_NAMES = (ELA, NOISE_UNEVENNESS, NOISE_LEVEL, COMPRESSION_GHOST, COMPRESSION_GRID, FREQUENCY_DETAIL, FREQUENCY_PEAKS)
# These read what JPEG compression left behind, and were measured on JPEG files only.
JPEG_ONLY = frozenset({ELA, COMPRESSION_GHOST, COMPRESSION_GRID})
# These were measured as adding nothing, so they're reported but add no evidence line. A test checks this against the results file.
ADDS_NOTHING = frozenset({NOISE_UNEVENNESS, NOISE_LEVEL, COMPRESSION_GHOST, FREQUENCY_PEAKS})

# A score at or above its limit is "unusual". Each limit is the score reached by the top 5% of real images on the
# calibration split, as written to the results file by backend.media.eval.forensics. A test checks they still match.
FLAG_LIMITS: dict[str, float] = {
    ELA: 0.0161,
    NOISE_UNEVENNESS: 11.2819,
    NOISE_LEVEL: -0.3034,
    COMPRESSION_GHOST: 19.6314,
    COMPRESSION_GRID: 0.2689,
    FREQUENCY_DETAIL: 3.7096,
    FREQUENCY_PEAKS: 6.4906,
}

ELA_QUALITY = 90
ELA_BLOCK = 16
NOISE_BLOCK = 32
GRID = 8
GHOST_QUALITIES = (50, 60, 70, 80, 90)
GHOST_BLOCK = 16
FREQUENCY_SIDE = 512
FREQUENCY_MIN_SIDE = 128
MIN_SIDE = 64
# Larger images are examined in the middle only, to keep the time and memory used in check.
MAX_PIXELS = 8_000_000
REGION_Z = 4.0
MIN_REGION_BLOCKS = 6
MAX_REGIONS = 5
# A "region" covering more of the image than this says nothing about any one part of it.
MAX_REGION_SHARE = 0.5
# Pixels this dark or bright are clipped, so they hold no usable noise.
_CLIPPED_LOW, _CLIPPED_HIGH = 16.0, 235.0
_MAD_TO_SIGMA = 1.4826
_IMMERKAER = ((1, -2, 1), (-2, 4, -2), (1, -2, 1))
_STANDARD_LUMA_TABLE = (
    16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55, 14, 13, 16, 24, 40, 57, 69, 56, 14, 17, 22, 29, 51,
    87, 80, 62, 18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113, 92, 49, 64, 78, 87, 103, 121, 120, 101,
    72, 92, 95, 98, 112, 100, 103, 99,
)  # fmt: skip


@dataclass
class Measurement:
    score: float | None
    # How far each block stands out, for finding regions. None if this test has no regions.
    block_z: np.ndarray | None = None
    block_size: int = 0


def to_luma(rgb: np.ndarray) -> np.ndarray:
    return (rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114).astype(np.float32)


def block_means(values: np.ndarray, size: int) -> np.ndarray:
    _ensure_libraries()
    rows, columns = values.shape[0] // size, values.shape[1] // size
    trimmed = values[: rows * size, : columns * size]
    return trimmed.reshape(rows, size, columns, size).mean(axis=(1, 3))


def robust_z(values: np.ndarray, floor: float = 1e-3, mask: np.ndarray | None = None) -> np.ndarray:
    """How many robust standard deviations each value is from the middle, so one region can't hide itself."""
    _ensure_libraries()
    sample = values if mask is None else values[mask]
    if sample.size == 0:
        return np.zeros_like(values)
    middle = np.median(sample)
    spread = _MAD_TO_SIGMA * np.median(np.abs(sample - middle))
    return (values - middle) / max(float(spread), floor)


def _resave(rgb: np.ndarray, quality: int) -> np.ndarray:
    ok, encoded = cv2.imencode(".jpg", rgb[..., ::-1], [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("The image could not be re-encoded.")
    return cv2.imdecode(encoded, cv2.IMREAD_COLOR)[..., ::-1]


def _texture(luma: np.ndarray) -> np.ndarray:
    return np.abs(cv2.Sobel(luma, cv2.CV_32F, 1, 0, ksize=3)) + np.abs(cv2.Sobel(luma, cv2.CV_32F, 0, 1, ksize=3))


def _ela(rgb: np.ndarray, luma: np.ndarray) -> Measurement:
    """Re-save the image once and see where it changes most, allowing for how busy each area is."""
    error = np.abs(to_luma(_resave(rgb, ELA_QUALITY)) - luma)
    relative = block_means(error, ELA_BLOCK) / (block_means(_texture(luma), ELA_BLOCK) + 8.0)
    z = robust_z(relative)
    return Measurement(float(np.mean(z > REGION_Z)), z, ELA_BLOCK)


def _noise(luma: np.ndarray) -> tuple[Measurement, Measurement]:
    """Estimate each block's noise from what a small filter leaves behind, ignoring edges and clipped areas.

    Returns how uneven it is across the image, and how little there is overall.
    """
    response = np.abs(cv2.filter2D(luma, cv2.CV_32F, np.array(_IMMERKAER, dtype=np.float32)))
    size = NOISE_BLOCK
    rows, columns = luma.shape[0] // size, luma.shape[1] // size
    blocks = response[: rows * size, : columns * size].reshape(rows, size, columns, size).transpose(0, 2, 1, 3)
    sigma = np.median(blocks.reshape(rows, columns, -1), axis=2) * _MAD_TO_SIGMA / 6.0
    brightness = block_means(luma, size)
    usable = (brightness > _CLIPPED_LOW) & (brightness < _CLIPPED_HIGH)
    if usable.sum() < 8:
        return Measurement(None), Measurement(None)
    z = np.where(usable, robust_z(np.log(sigma + 0.25), mask=usable), 0.0)
    return (
        Measurement(float(np.percentile(z, 99)), z, size),
        Measurement(-float(np.median(sigma[usable]))),
    )


def _ghost(rgb: np.ndarray, luma: np.ndarray) -> Measurement:
    """A part saved earlier at another quality stays closest to its copy at that quality."""
    errors = [block_means(np.abs(to_luma(_resave(rgb, q)) - luma), GHOST_BLOCK) for q in GHOST_QUALITIES]
    stack = np.stack(errors)
    relative = stack / (stack.mean(axis=0, keepdims=True) + 1.0)
    ghost = -np.stack([robust_z(layer) for layer in relative]).min(axis=0)
    return Measurement(float(np.percentile(ghost, 99)), ghost, GHOST_BLOCK)


def _grid_strength(luma: np.ndarray, axis: int) -> float:
    steps = np.abs(np.diff(luma, axis=axis)).mean(axis=1 - axis)
    profile = np.array([steps[k::GRID].mean() for k in range(GRID)])
    peak = int(profile.argmax())
    middle = float(np.median(np.delete(profile, peak)))
    return float((profile[peak] - middle) / (middle + 1e-3))


def _grid(luma: np.ndarray) -> Measurement:
    """How strongly the 8-pixel JPEG grid shows, in its weaker direction."""
    return Measurement(min(_grid_strength(luma, 0), _grid_strength(luma, 1)))


def _frequency(luma: np.ndarray) -> tuple[Measurement, Measurement]:
    """Read the spectrum of the middle of the image. Whole image only, so these have no regions.

    Returns how little fine detail there is compared with middling detail, and how strong any regular peaks are.
    """
    height, width = luma.shape
    side = min(FREQUENCY_SIDE, height, width)
    if side < FREQUENCY_MIN_SIDE:
        return Measurement(None), Measurement(None)
    top, left = (height - side) // 2, (width - side) // 2
    crop = luma[top : top + side, left : left + side]
    residual = crop - cv2.GaussianBlur(crop, (0, 0), 1.5)
    window = np.outer(np.hanning(side), np.hanning(side)).astype(np.float32)
    power = np.abs(np.fft.fftshift(np.fft.fft2(residual * window))) ** 2 + 1e-6
    log_power = np.log(power)

    y, x = np.indices((side, side))
    radius = np.hypot(y - side // 2, x - side // 2) / side
    fine = power[(radius > 0.35) & (radius < 0.5)].mean()
    middling = power[(radius > 0.1) & (radius < 0.25)].mean()

    rings = np.minimum((radius * 100).astype(np.int32), 70)
    medians = np.zeros(71)
    spreads = np.ones(71)
    for ring in range(71):
        values = log_power[rings == ring]
        if values.size:
            medians[ring] = np.median(values)
            spreads[ring] = max(_MAD_TO_SIGMA * np.median(np.abs(values - medians[ring])), 1e-3)
    z = (log_power - medians[rings]) / spreads[rings]

    # The JPEG grid puts peaks at every eighth of the sampling rate, so those are set aside.
    lattice = np.zeros((side, side), dtype=bool)
    for k in range(-GRID // 2, GRID // 2 + 1):
        centre = side // 2 + round(k * side / GRID)
        low, high = max(0, centre - 2), min(side, centre + 3)
        lattice[low:high, :] = True
        lattice[:, low:high] = True
    band = (radius > 0.12) & (radius < 0.5) & ~lattice
    return (
        Measurement(-float(np.log(fine / middling))),
        Measurement(float(np.percentile(z[band], 99.99))),
    )


def measure_all(rgb: np.ndarray) -> dict[str, Measurement]:
    """Run every test on 8-bit RGB pixels. The caller decides which apply to the file it came from."""
    _ensure_libraries()
    luma = to_luma(rgb)
    unevenness, level = _noise(luma)
    detail, peaks = _frequency(luma)
    return {
        ELA: _ela(rgb, luma),
        NOISE_UNEVENNESS: unevenness,
        NOISE_LEVEL: level,
        COMPRESSION_GHOST: _ghost(rgb, luma),
        COMPRESSION_GRID: _grid(luma),
        FREQUENCY_DETAIL: detail,
        FREQUENCY_PEAKS: peaks,
    }


def find_regions(block_z: np.ndarray, block_size: int, origin: tuple[int, int] = (0, 0)) -> list[ForensicRegion]:
    """Boxes around connected blocks that stand out, largest first, in the image's own pixels."""
    _ensure_libraries()
    mask = (block_z > REGION_Z).astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    found = []
    for label in range(1, count):
        left, top, width, height, area = stats[label]
        if area >= MIN_REGION_BLOCKS and width * height <= MAX_REGION_SHARE * block_z.size:
            found.append((int(area), int(left), int(top), int(width), int(height)))
    found.sort(reverse=True)
    return [
        ForensicRegion(
            x=origin[0] + left * block_size, y=origin[1] + top * block_size, width=width * block_size, height=height * block_size
        )
        for _, left, top, width, height in found[:MAX_REGIONS]
    ]


def estimate_jpeg_quality(table: Any) -> int | None:
    """Estimate the 1-100 quality setting from a luminance table, using the common IJG scale. Other tools differ."""
    _ensure_libraries()
    if table is None or len(table) != len(_STANDARD_LUMA_TABLE):
        return None
    scale = float(np.mean(np.asarray(table, dtype=np.float64) * 100.0 / np.asarray(_STANDARD_LUMA_TABLE)))
    if scale <= 0:
        return None
    quality = 5000.0 / scale if scale > 100 else (200.0 - scale) / 2.0
    return int(np.clip(round(quality), 1, 100))


def _read_jpeg_quality(path: Path) -> int | None:
    from PIL import Image

    try:
        with Image.open(path) as image:
            return estimate_jpeg_quality((getattr(image, "quantization", None) or {}).get(0))
    except (OSError, ValueError, SyntaxError):
        return None


def _middle(rgb: np.ndarray) -> tuple[np.ndarray, tuple[int, int], bool]:
    height, width = rgb.shape[:2]
    if height * width <= MAX_PIXELS:
        return rgb, (0, 0), False
    scale = (MAX_PIXELS / (height * width)) ** 0.5
    new_height, new_width = int(height * scale), int(width * scale)
    top, left = (height - new_height) // 2, (width - new_width) // 2
    return rgb[top : top + new_height, left : left + new_width], (left, top), True


def _test_result(name: str, measurement: Measurement, is_jpeg: bool, origin: tuple[int, int]) -> ForensicTest:
    if name in JPEG_ONLY and not is_jpeg:
        return ForensicTest(
            name=name, status=CheckStatus.UNAVAILABLE, reason="This test reads JPEG compression and this file isn't a JPEG."
        )
    if measurement.score is None:
        return ForensicTest(
            name=name, status=CheckStatus.UNAVAILABLE, reason="The image has too little usable area for this test."
        )
    limit = FLAG_LIMITS.get(name)
    flagged = None if limit is None else measurement.score >= limit
    regions = []
    if flagged and measurement.block_z is not None:
        regions = find_regions(measurement.block_z, measurement.block_size, origin)
    return ForensicTest(
        name=name,
        status=CheckStatus.COMPLETE,
        score=round(measurement.score, 4),
        limit=limit,
        flagged=flagged,
        regions=regions,
    )


def _analyze(path: Path, image: Any, container: str) -> ForensicsCheck:
    rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    limitations = []
    working, origin, cropped = _middle(rgb)
    if cropped:
        limitations.append("This image is large, so only the middle of it was examined. Larger images weren't measured.")
    is_jpeg = container == "jpeg"
    measured = measure_all(working)
    return ForensicsCheck(
        status=CheckStatus.COMPLETE,
        source_format=container,
        jpeg_quality_estimate=_read_jpeg_quality(path) if is_jpeg else None,
        tests=[_test_result(name, measured[name], is_jpeg, origin) for name in TEST_NAMES],
        limitations=limitations,
    )


def run_forensics(path: Path, image: Any, container: str, config: MediaConfig) -> ForensicsCheck:
    """Run the tests within the time limit. Failures are reported in the result, never raised."""
    if not _ensure_libraries():
        return ForensicsCheck(
            status=CheckStatus.UNAVAILABLE,
            limitations=["Pixel forensics need OpenCV and NumPy, and at least one isn't installed."],
        )
    if min(image.size) < MIN_SIDE:
        return ForensicsCheck(
            status=CheckStatus.UNAVAILABLE,
            limitations=[f"The image is smaller than {MIN_SIDE}px on one side, so pixel forensics weren't run."],
        )
    outcome: list[ForensicsCheck] = []

    def run() -> None:
        try:
            outcome.append(_analyze(path, image, container))
        except Exception as exc:  # noqa: BLE001 - one failed check never stops the others.
            logger.warning("Media forensics failed: %s", type(exc).__name__)
            outcome.append(
                ForensicsCheck(status=CheckStatus.UNAVAILABLE, limitations=["Pixel forensics failed unexpectedly."])
            )

    thread = threading.Thread(target=run, daemon=True, name="media-forensics")
    thread.start()
    thread.join(config.forensics_time_limit_s)
    if outcome:
        return outcome[0]
    return ForensicsCheck(
        status=CheckStatus.UNAVAILABLE,
        limitations=[f"Pixel forensics didn't finish within {config.forensics_time_limit_s:.0f} seconds."],
    )
