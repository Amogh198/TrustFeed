"""Find face regions and score each one with the detectors. It never identifies anyone.

No face is compared with any other face or any list. Only boxes and scores are kept, never the crops.
"""

from __future__ import annotations

import gc
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any

from backend.media.config import MediaConfig
from backend.media.errors import ClassifierUnavailable
from backend.media.models import CheckStatus, FaceRegion, FaceScore, FacesCheck, ModelBand

logger = logging.getLogger(__name__)

CASCADE = "haarcascade_frontalface_default.xml"
MIN_FACE = 48
# Faces are looked for on a copy no longer than this, so a huge image can't take long.
DETECT_SIDE = 1600
MARGIN = 0.25
FACES_LIMITATIONS = (
    "This only finds where faces are. It never identifies anyone.",
    "Face finding uses a simple method: it misses turned, small or covered faces, and can mark things that aren't faces.",
    "Accuracy on face swaps has not been measured, because no properly labelled face swap set was available. The "
    "detectors' scores on a face crop are unmeasured signals, not proof.",
)


@dataclass(frozen=True)
class FaceBox:
    x: int
    y: int
    width: int
    height: int


def detect_faces(image: Any) -> list[FaceBox]:
    """Return face boxes in the image's own pixels, largest first."""
    import cv2
    import numpy as np

    rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    longest = max(rgb.shape[:2])
    scale = min(1.0, DETECT_SIDE / longest)
    if scale < 1.0:
        rgb = cv2.resize(rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    gray = cv2.equalizeHist(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY))
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + CASCADE)
    if cascade.empty():
        raise RuntimeError("The face model file could not be read.")
    found = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(MIN_FACE, MIN_FACE))
    boxes = [FaceBox(*(round(int(value) / scale) for value in box)) for box in found]
    return sorted(boxes, key=lambda box: box.width * box.height, reverse=True)


def crop_face(image: Any, box: FaceBox) -> Any:
    """Cut out the face with some margin, because detectors look at the edges of a pasted face too."""
    margin_x, margin_y = int(box.width * MARGIN), int(box.height * MARGIN)
    return image.crop(
        (
            max(0, box.x - margin_x),
            max(0, box.y - margin_y),
            min(image.width, box.x + box.width + margin_x),
            min(image.height, box.y + box.height + margin_y),
        )
    ).convert("RGB")


def _band(score: float, config: MediaConfig, crop: Any) -> ModelBand:
    if min(crop.size) < config.min_reliable_side:
        return ModelBand.INCONCLUSIVE
    if score >= config.elevated_score:
        return ModelBand.ELEVATED
    if score <= config.low_score:
        return ModelBand.LOW
    return ModelBand.INCONCLUSIVE


def _predict(classifier: Any, crops: Sequence[Any]) -> list[float] | None:
    try:
        scores = classifier.predict(crops)
    except ClassifierUnavailable:
        return None
    except Exception as exc:  # noqa: BLE001 - one detector failing never stops the check.
        logger.warning("Face region scoring failed: %s", type(exc).__name__)
        return None
    if len(scores) != len(crops) or not all(0 <= score <= 1 for score in scores):
        return None
    return [float(score) for score in scores]


def analyze_faces(
    frames: Sequence[tuple[float | None, Any]],
    classifier: Any,
    config: MediaConfig,
    *,
    panel_models: Sequence[tuple[str, str]] = (),
    factory: Callable[[MediaConfig], Any] | None = None,
) -> FacesCheck:
    """Find faces in each (timestamp, image) and score them. Failures are reported, never raised."""
    limitations = list(FACES_LIMITATIONS)
    started = time.monotonic()
    regions: list[FaceRegion] = []
    crops: list[Any] = []
    examined = 0
    try:
        import cv2  # noqa: F401 - checked here so a missing library gives a clear reason.
    except ImportError:
        return FacesCheck(status=CheckStatus.UNAVAILABLE, limitations=["Finding faces needs OpenCV, which isn't installed."])
    for timestamp, image in frames:
        if time.monotonic() - started >= config.faces_time_limit_s:
            limitations.append(f"Stopped at the {config.faces_time_limit_s:.0f}-second limit, so some frames weren't examined.")
            break
        try:
            boxes = detect_faces(image)
        except Exception as exc:  # noqa: BLE001 - one bad frame never stops the rest.
            logger.warning("Face finding failed: %s", type(exc).__name__)
            limitations.append("Faces could not be looked for in part of this media.")
            continue
        examined += 1
        for box in boxes:
            if len(regions) >= config.max_faces:
                limitations.append(f"Only the first {config.max_faces} faces were scored.")
                break
            regions.append(
                FaceRegion(x=box.x, y=box.y, width=box.width, height=box.height, timestamp_s=timestamp)
            )
            crops.append(crop_face(image, box))
    if not examined:
        return FacesCheck(status=CheckStatus.UNAVAILABLE, limitations=list(dict.fromkeys(limitations)))

    if crops:
        _add_scores(regions, crops, classifier, classifier.model_id, config, limitations, counted_note=True)
        for model_id, revision in panel_models:
            if model_id == classifier.model_id or factory is None:
                continue
            if time.monotonic() - started >= config.panel_time_budget_s:
                limitations.append("Some panel detectors weren't run on the faces, because of the panel's time limit.")
                break
            try:
                detector = factory(replace(config, model_id=model_id, model_revision=revision))
            except Exception as exc:  # noqa: BLE001 - the panel's other detectors still run.
                logger.warning("Face panel detector could not be built: %s", type(exc).__name__)
                continue
            _add_scores(regions, crops, detector, model_id, config, limitations)
            del detector
            gc.collect()
    return FacesCheck(
        status=CheckStatus.COMPLETE,
        frames_examined=examined,
        faces=regions,
        limitations=list(dict.fromkeys(limitations)),
    )


def _add_scores(
    regions: list[FaceRegion],
    crops: Sequence[Any],
    classifier: Any,
    model_id: str,
    config: MediaConfig,
    limitations: list[str],
    *,
    counted_note: bool = False,
) -> None:
    scores = _predict(classifier, crops)
    if scores is None:
        limitations.append(f"The detector {model_id} gave no result for the face regions.")
        return
    for region, crop, score in zip(regions, crops, scores, strict=True):
        region.scores.append(FaceScore(model_id=model_id, score=round(score, 4), band=_band(score, config, crop)))
    if counted_note and any(min(crop.size) < config.min_reliable_side for crop in crops):
        limitations.append(
            f"Some faces are smaller than {config.min_reliable_side}px, so their scores are treated as inconclusive."
        )
