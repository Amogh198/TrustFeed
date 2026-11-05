"""Orchestrates the checks. One failed check never stops the others."""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from pathlib import Path

from backend.media.classifier import ImageClassifier, default_classifier
from backend.media.config import MediaConfig
from backend.media.errors import ClassifierUnavailable, HashIndexUnavailable, MediaInputError
from backend.media.keyframes import STRATEGY, Keyframe, extract_keyframes
from backend.media.metadata import InputInfo, inspect_input, read_image
from backend.media.models import (
    Assessment,
    CheckStatus,
    ClassifierCheck,
    FrameEvidence,
    HashMatch,
    KeyframeCheck,
    MediaAnalysisResult,
    MediaChecks,
    MediaType,
    MetadataCheck,
    ModelBand,
    PHashCheck,
    empty_checks,
)
from backend.media.phash import HashIndex, JsonHashIndex, compute_phash

# File names and contents are never logged: uploads may be private.
logger = logging.getLogger(__name__)

SCORE_CAVEAT = "Model scores are uncalibrated triage signals, not proof that media is authentic or false."
MODEL_CAVEAT = (
    "Detector accuracy has not been validated for this deployment; recompressed media, "
    "images without faces and newer generators may be unreliable."
)
PHASH_CAVEAT = (
    "A perceptual match shows visual similarity to a reference, not who created the media or whether a claim is false."
)


def _resolve_index(config: MediaConfig, supplied: HashIndex | None) -> tuple[HashIndex | None, str | None]:
    if supplied is not None:
        return supplied, None
    if config.phash_index_path is None:
        return None, "No pHash reference index is configured, so no provenance comparison was performed."
    try:
        index = JsonHashIndex.load(config.phash_index_path)
    except HashIndexUnavailable as exc:
        return None, f"{exc} No provenance comparison was performed."
    if index.skipped:
        return index, f"{index.skipped} malformed pHash reference entries were ignored."
    return index, None


def _unavailable_classifier(classifier: ImageClassifier | None, reason: str) -> ClassifierCheck:
    return ClassifierCheck(
        status=CheckStatus.UNAVAILABLE,
        model_id=getattr(classifier, "model_id", None),
        model_revision=getattr(classifier, "model_revision", None),
        limitations=[reason],
    )


def _predict(classifier: ImageClassifier, images: Sequence[object]) -> list[float] | str:
    """Return one validated score per image, or the reason no scores are available."""
    try:
        scores = classifier.predict(images)
    except ClassifierUnavailable as exc:
        return str(exc)
    except Exception as exc:
        logger.warning("Media classifier failed: %s", type(exc).__name__)
        return "The classifier failed unexpectedly, so no model result is available."
    valid = len(scores) == len(images) and all(math.isfinite(score) and 0 <= score <= 1 for score in scores)
    return [float(score) for score in scores] if valid else "The classifier returned invalid output."


def _band(score: float, config: MediaConfig) -> ModelBand:
    if score >= config.elevated_score:
        return ModelBand.ELEVATED
    if score <= config.low_score:
        return ModelBand.LOW
    return ModelBand.INCONCLUSIVE


def _classifier_check(classifier: ImageClassifier, scores: list[float] | str, config: MediaConfig) -> ClassifierCheck:
    if isinstance(scores, str):
        return _unavailable_classifier(classifier, scores)
    if not scores:
        return _unavailable_classifier(classifier, "No frames were available for the classifier.")

    # A video scores on its strongest third of frames, so a short manipulated
    # segment is not averaged away and a single outlier does not decide alone.
    ranked = sorted(scores, reverse=True)
    top = ranked[: max(1, math.ceil(len(ranked) / 3))]
    score = sum(top) / len(top)
    low, high = ranked[-1], ranked[0]
    limitations = [SCORE_CAVEAT, MODEL_CAVEAT]
    band = _band(score, config)
    if high - low >= config.frame_disagreement:
        band = ModelBand.INCONCLUSIVE
        limitations.append(f"Keyframe scores disagree (range {low:.2f} to {high:.2f}).")
    return ClassifierCheck(
        status=CheckStatus.COMPLETE,
        model_id=classifier.model_id,
        model_revision=classifier.model_revision,
        score=round(score, 4),
        score_min=round(low, 4),
        score_max=round(high, 4),
        band=band,
        items_scored=len(scores),
        limitations=limitations,
    )


def _lookup(index: HashIndex, phash: str, config: MediaConfig) -> list[HashMatch] | None:
    try:
        return index.lookup(phash, config.phash_max_distance)
    except Exception as exc:
        logger.warning("Media pHash lookup failed: %s", type(exc).__name__)
        return None


def _base_phash_check(index: HashIndex | None, note: str | None, config: MediaConfig) -> PHashCheck:
    return PHashCheck(
        status=CheckStatus.COMPLETE,
        compared=index is not None,
        references_checked=len(index) if index is not None else 0,
        max_distance=config.phash_max_distance,
        limitations=[note] if note else [],
    )


def _image_phash(image, index: HashIndex | None, note: str | None, config: MediaConfig) -> PHashCheck:
    try:
        phash = compute_phash(image)
    except Exception as exc:
        logger.warning("Media pHash failed: %s", type(exc).__name__)
        return PHashCheck(
            status=CheckStatus.UNAVAILABLE,
            limitations=["The perceptual hash could not be computed; check that imagehash is installed."],
        )
    check = _base_phash_check(index, note, config)
    check.phash = phash
    if index is not None:
        matches = _lookup(index, phash, config)
        if matches is None:
            check.compared = False
            check.limitations.append("The pHash reference lookup failed, so no comparison was completed.")
        else:
            check.matches = matches
    return check


def _video_phash(
    frames: Sequence[Keyframe], index: HashIndex | None, note: str | None, config: MediaConfig
) -> tuple[PHashCheck, list[str | None]]:
    check = _base_phash_check(index, note, config)
    hashes: list[str | None] = []
    best: dict[str, HashMatch] = {}
    lookup_failed = False
    for frame in frames:
        try:
            phash = compute_phash(frame.image)
        except Exception as exc:
            logger.warning("Media pHash failed: %s", type(exc).__name__)
            hashes.append(None)
            continue
        hashes.append(phash)
        if index is None:
            continue
        matches = _lookup(index, phash, config)
        if matches is None:
            lookup_failed = True
            continue
        for match in matches:
            current = best.get(match.phash)
            if current is None or match.distance < current.distance:
                best[match.phash] = match.model_copy(update={"timestamp_s": frame.timestamp_s})
    if not any(hashes):
        return (
            PHashCheck(
                status=CheckStatus.UNAVAILABLE,
                limitations=["Perceptual hashes could not be computed; check that imagehash is installed."],
            ),
            hashes,
        )
    if lookup_failed:
        check.limitations.append("Some pHash reference lookups failed, so the comparison is incomplete.")
    check.matches = sorted(best.values(), key=lambda match: match.distance)
    return check, hashes


def _classifier_evidence(check: ClassifierCheck, frames: Sequence[FrameEvidence], config: MediaConfig) -> list[str]:
    if check.status is not CheckStatus.COMPLETE or check.score is None:
        return []
    if frames:
        lines = [
            (
                f"Model synthetic-class signal of {check.score:.2f} across {check.items_scored} keyframes "
                f"(range {check.score_min:.2f} to {check.score_max:.2f})."
            )
        ]
        elevated = [f"{f.timestamp_s:.1f}s" for f in frames if (f.model_score or 0) >= config.elevated_score]
        if elevated:
            lines.append(f"Keyframes with elevated model signals: {', '.join(elevated)}.")
    else:
        lines = [f"Model synthetic-class signal of {check.score:.2f}."]
    if check.band is ModelBand.INCONCLUSIVE:
        lines.append("Inconclusive: the model result does not clearly point either way.")
    return lines


def _phash_evidence(check: PHashCheck) -> list[str]:
    lines = []
    for match in check.matches:
        line = f"Perceptual match (distance {match.distance}) to reference {match.label!r}"
        if match.first_seen:
            line += f", first seen {match.first_seen}"
        if match.source:
            line += f", source {match.source!r}"
        if match.timestamp_s is not None:
            line += f", at {match.timestamp_s:.1f}s"
        lines.append(line + ".")
    if check.compared and not check.matches and check.references_checked:
        lines.append(
            f"No perceptual match within distance {check.max_distance} across {check.references_checked} references."
        )
    return lines


def _assess(metadata: MetadataCheck, classifier: ClassifierCheck, phash: PHashCheck) -> tuple[Assessment, str]:
    if classifier.band is ModelBand.ELEVATED or phash.matches or metadata.generator_hint:
        return (
            Assessment.SIGNALS_PRESENT,
            "Signals worth human review were found. This is a triage result, not a verdict on authenticity.",
        )
    if classifier.band is ModelBand.LOW:
        return (
            Assessment.NO_STRONG_SIGNALS,
            "No strong signals were found. This does not establish that the media is authentic.",
        )
    return Assessment.INCONCLUSIVE, "Inconclusive: the available checks do not support a clear triage result."


def _dedupe(items: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _finish(
    info: InputInfo,
    metadata: MetadataCheck,
    classifier: ClassifierCheck,
    phash: PHashCheck,
    keyframes: KeyframeCheck,
    extra_limitations: Sequence[str],
    config: MediaConfig,
) -> MediaAnalysisResult:
    evidence = [
        *_classifier_evidence(classifier, keyframes.frames, config),
        *_phash_evidence(phash),
        *metadata.indicators,
    ]
    limitations = [*extra_limitations]
    if classifier.band is ModelBand.LOW and (phash.matches or metadata.generator_hint):
        limitations.append("Signals disagree: the model score is low, but other checks found signals.")
    for check in (classifier, phash, metadata, keyframes):
        limitations.extend(check.limitations)
    if phash.matches:
        limitations.append(PHASH_CAVEAT)

    assessment, summary = _assess(metadata, classifier, phash)
    return MediaAnalysisResult(
        media_type=info.media_type,
        # "complete" means a model result exists, as in the contract sketch.
        # Metadata and pHash evidence is still returned when it does not.
        status=CheckStatus.COMPLETE if classifier.status is CheckStatus.COMPLETE else CheckStatus.UNAVAILABLE,
        score=classifier.score,
        assessment=assessment,
        summary=summary,
        evidence=_dedupe(evidence),
        limitations=_dedupe(limitations),
        sha256=info.sha256,
        size_bytes=info.size_bytes,
        checks=MediaChecks(metadata=metadata, classifier=classifier, phash=phash, keyframes=keyframes),
    )


def _rejected(error: MediaInputError, info: InputInfo | None = None) -> MediaAnalysisResult:
    return MediaAnalysisResult(
        media_type=info.media_type if info else MediaType.UNKNOWN,
        status=CheckStatus.UNAVAILABLE,
        assessment=Assessment.INCONCLUSIVE,
        summary=f"Media analysis unavailable: {error.message}",
        limitations=[error.message],
        failure_code=error.code,
        sha256=info.sha256 if info else None,
        size_bytes=info.size_bytes if info else None,
        checks=empty_checks("Not run because the media could not be analyzed."),
    )


def _analyze_image(path, info, classifier, index, note, config) -> MediaAnalysisResult:
    try:
        image, metadata, limitations = read_image(path, config)
    except ImportError:
        return _rejected(MediaInputError("dependency_missing", "Pillow is not installed."), info)
    except MediaInputError as exc:
        return _rejected(exc, info)

    check = _classifier_check(classifier, _predict(classifier, [image]), config)
    if check.status is CheckStatus.COMPLETE and min(image.size) < config.min_reliable_side:
        check.band = ModelBand.INCONCLUSIVE
        check.limitations.append(
            f"The image is smaller than {config.min_reliable_side}px on one side, so the model score is unreliable."
        )
    return _finish(
        info,
        metadata,
        check,
        _image_phash(image, index, note, config),
        KeyframeCheck(status=CheckStatus.NOT_APPLICABLE),
        limitations,
        config,
    )


def _analyze_video(path, info, classifier, index, note, config) -> MediaAnalysisResult:
    try:
        video, frames, limitations = extract_keyframes(path, config)
    except ImportError:
        return _rejected(MediaInputError("dependency_missing", "OpenCV is not installed."), info)
    except MediaInputError as exc:
        return _rejected(exc, info)

    scores = _predict(classifier, [frame.image for frame in frames])
    phash, hashes = _video_phash(frames, index, note, config)
    frame_scores: Sequence[float | None] = scores if isinstance(scores, list) else [None] * len(frames)
    keyframes = KeyframeCheck(
        status=CheckStatus.COMPLETE,
        strategy=STRATEGY,
        frames=[
            FrameEvidence(
                frame_index=frame.frame_index,
                timestamp_s=frame.timestamp_s,
                scene_change_score=frame.scene_change_score,
                phash=frame_hash,
                model_score=round(score, 4) if score is not None else None,
            )
            for frame, frame_hash, score in zip(frames, hashes, frame_scores, strict=True)
        ],
        limitations=limitations,
    )
    metadata = MetadataCheck(
        status=CheckStatus.COMPLETE,
        format=info.container,
        width=video.width,
        height=video.height,
        fps=video.fps,
        frame_count=video.frame_count,
        duration_s=video.duration_s,
        limitations=["Only basic stream properties were read; container tags were not inspected."],
    )
    return _finish(info, metadata, _classifier_check(classifier, scores, config), phash, keyframes, [], config)


def analyze_media(
    path: str | Path,
    *,
    classifier: ImageClassifier | None = None,
    hash_index: HashIndex | None = None,
    config: MediaConfig | None = None,
) -> MediaAnalysisResult:
    """Analyze one image or video.

    Expected failures (bad input, missing weights, broken index) are reported in
    the result rather than raised, so the wider pipeline keeps working.
    """
    config = config or MediaConfig.from_env()
    path = Path(path)
    try:
        info = inspect_input(path, config)
    except MediaInputError as exc:
        return _rejected(exc)

    classifier = classifier or default_classifier(config)
    index, note = _resolve_index(config, hash_index)
    analyze = _analyze_image if info.media_type is MediaType.IMAGE else _analyze_video
    return analyze(path, info, classifier, index, note, config)
