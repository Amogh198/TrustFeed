"""Occlusion heatmap: cover one part of an image at a time and see how the model's score moves.

It shows what the model is sensitive to, not what was edited. ``render_png`` holds only colours,
with none of the upload's pixels, so it is safe to keep after the upload is deleted.
"""

from __future__ import annotations

import io
import logging
import time
from typing import Any

from pydantic import BaseModel, Field

from backend.media.classifier import ImageClassifier
from backend.media.errors import ClassifierUnavailable
from backend.media.models import CheckStatus

# Upload contents are never logged.
logger = logging.getLogger(__name__)

HEATMAP_LABEL = "Where the model's score changed. This shows sensitivity, not proof of editing."
_LIMITS = [
    "This shows which areas moved the model's score. It does not show that an area was edited or generated.",
    "Each area is covered on its own, so effects that depend on several areas together are missed.",
    "It uses a smaller copy of the image, so its starting score can differ slightly from the detector's result.",
]
GRID_SIZE = 8
MIN_SIDE = 64
WORKING_SIDE = 512
# Below this no area is said to stand out. Colours also never scale below the second figure,
# so that tiny changes stay faint instead of being stretched into a strong picture.
NOTABLE_CHANGE = 0.02
DISPLAY_FLOOR = 0.05
DEFAULT_MAX_SECONDS = 60.0


class OcclusionHeatmap(BaseModel):
    kind: str = "occlusion_heatmap"
    label: str = HEATMAP_LABEL
    status: CheckStatus
    grid_size: int = GRID_SIZE
    base_score: float | None = None
    # Rows of (original score - score with that area covered). Above 0, the area was raising the score.
    changes: list[list[float]] | None = None
    max_change: float | None = None
    notable: bool = False
    reasoning: str
    limitations: list[str] = Field(default_factory=list)


def _unavailable(reason: str) -> OcclusionHeatmap:
    return OcclusionHeatmap(status=CheckStatus.UNAVAILABLE, reasoning=reason, limitations=list(_LIMITS))


def _covered_copy(image: Any, row: int, column: int, fill: tuple[int, ...]) -> Any:
    width, height = image.size
    box = (
        column * width // GRID_SIZE,
        row * height // GRID_SIZE,
        (column + 1) * width // GRID_SIZE,
        (row + 1) * height // GRID_SIZE,
    )
    copy = image.copy()
    copy.paste(fill, box)
    return copy


def _scores(classifier: ImageClassifier, images: list[Any]) -> list[float] | None:
    scores = classifier.predict(images)
    # The range check also refuses NaN and infinity.
    if len(scores) != len(images) or not all(0 <= score <= 1 for score in scores):
        return None
    return [float(score) for score in scores]


def occlusion_heatmap(
    image: Any, classifier: ImageClassifier, *, batch_size: int = 8, max_seconds: float = DEFAULT_MAX_SECONDS
) -> OcclusionHeatmap:
    """Measure each area's effect on the score. Failures are reported, never raised.

    A full grid takes 65 model runs, so this is for on-request use. Running out of time gives
    ``unavailable`` rather than a partial picture.
    """
    from PIL import ImageStat

    if min(image.size) < MIN_SIDE:
        return _unavailable(f"The image is smaller than {MIN_SIDE}px on one side, so no heatmap was made.")
    working = image.convert("RGB")
    working.thumbnail((WORKING_SIDE, WORKING_SIDE))
    # The image's own average colour, so that the cover doesn't add a strong edge of its own.
    fill = tuple(int(value) for value in ImageStat.Stat(working).mean)
    cells = [(row, column) for row in range(GRID_SIZE) for column in range(GRID_SIZE)]
    deadline = time.monotonic() + max_seconds
    size = max(1, batch_size)
    try:
        base = _scores(classifier, [working])
        if base is None:
            return _unavailable("The classifier returned invalid output, so no heatmap was made.")
        changes = [[0.0] * GRID_SIZE for _ in range(GRID_SIZE)]
        for start in range(0, len(cells), size):
            if time.monotonic() > deadline:
                return _unavailable(f"The heatmap did not finish within {max_seconds:.0f} seconds.")
            batch = cells[start : start + size]
            scores = _scores(classifier, [_covered_copy(working, row, column, fill) for row, column in batch])
            if scores is None:
                return _unavailable("The classifier returned invalid output, so no heatmap was made.")
            for (row, column), score in zip(batch, scores, strict=True):
                changes[row][column] = round(base[0] - score, 4)
    except ClassifierUnavailable as exc:
        return _unavailable(f"{exc} No heatmap was made.")
    except Exception as exc:  # noqa: BLE001 - a model failure must be reported, never crash the request.
        logger.warning("Media heatmap failed: %s", type(exc).__name__)
        return _unavailable("The heatmap failed unexpectedly, so none was made.")

    largest = max(abs(value) for row in changes for value in row)
    notable = largest >= NOTABLE_CHANGE
    if notable:
        reasoning = f"Covering one area moved the score by up to {largest:.4f}, from {base[0]:.4f}."
    else:
        reasoning = (
            f"No area stands out: covering any one area moved the score by at most {largest:.4f}, from {base[0]:.4f}."
        )
    return OcclusionHeatmap(
        status=CheckStatus.COMPLETE,
        base_score=round(base[0], 4),
        changes=changes,
        max_change=largest,
        notable=notable,
        reasoning=reasoning,
        limitations=list(_LIMITS),
    )


def render_png(heatmap: OcclusionHeatmap, *, cell_pixels: int = 32) -> bytes:
    """Draw a transparent colour grid for the dashboard to lay over its own preview of the image.

    Red areas were raising the score and blue areas were lowering it.
    """
    from PIL import Image

    if heatmap.changes is None:
        raise ValueError("This heatmap has no measurements to draw.")
    scale = max(heatmap.max_change or 0.0, DISPLAY_FLOOR)
    grid = Image.new("RGBA", (heatmap.grid_size, heatmap.grid_size))
    for row, values in enumerate(heatmap.changes):
        for column, value in enumerate(values):
            alpha = round(170 * min(abs(value) / scale, 1.0))
            grid.putpixel((column, row), (214, 40, 40, alpha) if value > 0 else (31, 95, 200, alpha))
    picture = grid.resize((heatmap.grid_size * cell_pixels,) * 2, Image.Resampling.NEAREST)
    output = io.BytesIO()
    picture.save(output, format="PNG")
    return output.getvalue()


def render_overlay(image: Any, heatmap: OcclusionHeatmap) -> bytes:
    """Draw the heatmap over the image, with its label. This holds the image, so never store it."""
    from PIL import Image, ImageDraw

    picture = image.convert("RGBA")
    picture.thumbnail((WORKING_SIDE, WORKING_SIDE))
    colours = Image.open(io.BytesIO(render_png(heatmap))).resize(picture.size, Image.Resampling.NEAREST)
    picture.alpha_composite(colours)
    caption = 34
    canvas = Image.new("RGB", (picture.width, picture.height + caption), "white")
    canvas.paste(picture.convert("RGB"), (0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.text((4, picture.height + 3), "Where the model's score changed.", fill="black")
    draw.text((4, picture.height + 18), "Sensitivity, not proof of editing.", fill="black")
    output = io.BytesIO()
    canvas.save(output, format="PNG")
    return output.getvalue()
