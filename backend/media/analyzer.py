"""Orchestrates the checks. One failed check never stops the others."""

from __future__ import annotations

import gc
import logging
import math
import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path

from backend.media.audio import (
    AudioDetector,
    AudioReaderMissing,
    AudioUnavailable,
    SpeechTranscriber,
    WhisperTranscriber,
    detect_synthetic_speech,
    extract_audio,
    transcribe_speech,
)
from backend.media.classifier import ImageClassifier, default_classifier
from backend.media.config import MediaConfig
from backend.media.content_credentials import INVALID, SIGNED, _with_time_limit, declares_ai, read_credentials
from backend.media.errors import ClassifierUnavailable, HashIndexUnavailable, MediaInputError
from backend.media.faces import analyze_faces
from backend.media.frames import FRAMES_LIMITATIONS, score_frames
from backend.media.forensics import ADDS_NOTHING, run_forensics
from backend.media.keyframes import STRATEGY, Keyframe, extract_keyframes
from backend.media.metadata import InputInfo, inspect_input, read_image
from backend.media.models import (
    out_of_100,
    Assessment,
    CheckStatus,
    ClassifierCheck,
    AudioSyntheticCheck,
    ContentCredentialsCheck,
    DetectorPanelCheck,
    DetectorResult,
    FacesCheck,
    FingerprintCheck,
    ForensicsCheck,
    FrameEvidence,
    FramesCheck,
    HashMatch,
    KeyframeCheck,
    MediaAnalysisResult,
    MediaChecks,
    MediaType,
    MetadataCheck,
    ModelBand,
    OcrCheck,
    PHashCheck,
    SpeechCheck,
    empty_checks,
)
from backend.media.ocr import read_text
from backend.media.local_features import frame_features
from backend.media.fingerprint import (
    EXACT_COPY,
    CaseFingerprintStore,
    QueryFrame,
    compute_fingerprints,
    find_matches,
)
from backend.media.panel import PANEL_MODELS, build_classifier
from backend.media.phash import HashIndex, JsonHashIndex, compute_phash

ClassifierFactory = Callable[[MediaConfig], ImageClassifier]

# File names and contents are never logged: uploads may be private.
logger = logging.getLogger(__name__)

SCORE_CAVEAT = "Model scores are uncalibrated triage signals, not proof that media is authentic or false."
MODEL_CAVEAT = (
    "Detector accuracy has not been validated for this deployment; recompressed media, "
    "images without faces and newer generators may be unreliable."
)
EDITED_CAVEAT = (
    "Edited photos are a known weak spot: no detector tested separated them reliably from ordinary photos, "
    "so a low score says little about whether a photo was edited."
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
    limitations = [SCORE_CAVEAT, MODEL_CAVEAT, EDITED_CAVEAT]
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


def _apply_size_limit(check: ClassifierCheck, image, config: MediaConfig) -> ClassifierCheck:
    if check.status is CheckStatus.COMPLETE and min(image.size) < config.min_reliable_side:
        check.band = ModelBand.INCONCLUSIVE
        check.limitations.append(
            f"The image is smaller than {config.min_reliable_side}px on one side, so the model score is unreliable."
        )
    return check


def _detector_result(check: ClassifierCheck, model_id: str, revision: str, *, counted: bool) -> DetectorResult:
    return DetectorResult(
        model_id=model_id,
        model_revision=revision,
        status=check.status,
        score=check.score,
        band=check.band,
        counted=counted,
        limitations=check.limitations,
    )


def _detector_panel(
    images: Sequence[object],
    in_use: ClassifierCheck,
    config: MediaConfig,
    factory: ClassifierFactory,
    *,
    is_image: bool,
) -> DetectorPanelCheck:
    """Run each detector in turn, releasing it before the next, because all of them need over 2 GB together."""
    started = time.monotonic()
    detectors: list[DetectorResult] = []
    for model_id, revision in PANEL_MODELS:
        if model_id == in_use.model_id and revision == in_use.model_revision:
            detectors.append(_detector_result(in_use, model_id, revision, counted=True))
            continue
        if time.monotonic() - started >= config.panel_time_budget_s:
            check = ClassifierCheck(
                status=CheckStatus.UNAVAILABLE,
                limitations=[f"Not run: the panel's {config.panel_time_budget_s:.0f}-second limit was reached."],
            )
            detectors.append(_detector_result(check, model_id, revision, counted=False))
            continue
        try:
            classifier = factory(replace(config, model_id=model_id, model_revision=revision))
        except Exception as exc:
            logger.warning("Media panel detector could not be built: %s", type(exc).__name__)
            check = ClassifierCheck(status=CheckStatus.UNAVAILABLE, limitations=["The detector could not be set up."])
        else:
            check = _classifier_check(classifier, _predict(classifier, images), config)
            del classifier
            gc.collect()
        if is_image:
            check = _apply_size_limit(check, images[0], config)
        detectors.append(_detector_result(check, model_id, revision, counted=False))

    ran = any(detector.status is CheckStatus.COMPLETE for detector in detectors)
    limitations = [SCORE_CAVEAT, "Only the detector in use affects the overall result."]
    if not any(detector.counted for detector in detectors):
        limitations.append("The detector in use is not on the panel, so no detector here affects the overall result.")
    return DetectorPanelCheck(
        status=CheckStatus.COMPLETE if ran else CheckStatus.UNAVAILABLE, detectors=detectors, limitations=limitations
    )


def _resolve_cases(config: MediaConfig, supplied: CaseFingerprintStore | None) -> tuple[list, str | None]:
    if supplied is not None:
        return supplied.entries, None
    if config.case_fingerprints_path is None:
        return [], "No earlier-case fingerprints are configured, so earlier cases were not compared."
    try:
        store = CaseFingerprintStore.load(config.case_fingerprints_path)
    except HashIndexUnavailable as exc:
        return [], f"{exc} Earlier cases were not compared."
    if store.skipped:
        return store.entries, f"{store.skipped} malformed earlier-case entries were ignored."
    return store.entries, None


def _safe_fingerprints(image) -> dict[str, str]:
    try:
        return compute_fingerprints(image)
    except Exception as exc:
        logger.warning("Media fingerprint failed: %s", type(exc).__name__)
        return {}


def _safe_local_features(images) -> list[str]:
    try:
        return frame_features(images)
    except Exception as exc:
        logger.warning("Media local features failed: %s", type(exc).__name__)
        return []


def _fingerprint_check(
    sha256: str | None,
    frames: Sequence[QueryFrame],
    whole_image: dict[str, str],
    index: HashIndex | None,
    cases: CaseFingerprintStore | None,
    config: MediaConfig,
) -> FingerprintCheck:
    """Compare only hashes, so nothing from the upload needs to be stored to do this."""
    limitations = []
    hashed = [frame for frame in frames if frame.hashes]
    if frames and not hashed:
        limitations.append("Image fingerprints could not be computed; check that imagehash is installed.")
    if not sha256 and not hashed:
        return FingerprintCheck(status=CheckStatus.UNAVAILABLE, limitations=limitations)
    # Other index types only offer a pHash lookup, which the separate pHash check already reports.
    references = list(getattr(index, "entries", []))
    only_phash = sum(1 for entry in references if not (entry.dhash or entry.whash))
    if only_phash:
        limitations.append(
            f"{only_phash} references have only a pHash, so they can't be matched here. "
            "Add them again to compare them fully."
        )
    earlier, note = _resolve_cases(config, cases)
    if note:
        limitations.append(note)
    if not references:
        limitations.append("No reference list was available, so no references were compared.")
    return FingerprintCheck(
        status=CheckStatus.COMPLETE,
        sha256=sha256,
        hashes=whole_image,
        frames_hashed=len(hashed),
        compared=bool(references or earlier),
        references_checked=len(references),
        earlier_cases_checked=len(earlier),
        matches=find_matches(sha256, hashed, references, earlier),
        limitations=limitations,
    )


def _fingerprint_evidence(check: FingerprintCheck | None) -> list[str]:
    if check is None:
        return []
    lines = []
    for match in check.matches:
        target = f"reference {match.label!r}" if match.found_in == "reference" else f"earlier case {match.case_id!r}"
        line = (
            f"Same file as {target}" if match.kind == EXACT_COPY else f"Fingerprints look like the same image as {target}"
        )
        if match.first_seen:
            line += f", recorded {match.first_seen}"
        if match.timestamp_s is not None:
            line += f", at {match.timestamp_s:.1f}s"
        lines.append(line + ".")
    return lines


def _credentials_evidence(check: ContentCredentialsCheck | None) -> list[str]:
    """An unsigned file adds no line here, because having no credentials shows nothing."""
    if check is None or check.status is not CheckStatus.COMPLETE:
        return []
    if check.state == INVALID:
        lines = ["Content Credentials are present but did not validate."]
        if declares_ai(check):
            lines.append("Those unverified credentials claim AI-generated content.")
        return lines
    if check.state != SIGNED:
        return []
    lines = ["Content Credentials are present and valid: the file has not changed since it was signed."]
    if declares_ai(check):
        lines.append("The signed credentials declare AI-generated content.")
    return lines


def _forensics_evidence(check: ForensicsCheck | None) -> list[str]:
    if check is None or check.status is not CheckStatus.COMPLETE:
        return []
    # Tests measured as adding nothing stay in the check, but aren't offered as evidence.
    flagged = sum(1 for test in check.tests if test.flagged and test.name not in ADDS_NOTHING)
    if not flagged:
        return []
    return [f"Pixel forensics tests read as unusual: {flagged}. Ordinary editing and re-saving can also cause this."]


def _extracted_text(ocr: OcrCheck | None, speech: SpeechCheck | None) -> dict[str, list[dict[str, object]]]:
    """The shape the claim checker reads. All of this text is untrusted data."""
    return {
        "ocr": [line.model_dump() for line in ocr.lines] if ocr else [],
        "speech": [segment.model_dump() for segment in speech.segments] if speech else [],
    }


def _not_requested(check_type, note: str | None = None):
    limitations = ["This is slow on CPU, so it runs on request. Tick the deep check when uploading, set MEDIA_RUN_HEAVY_CHECKS=1 or pass run_heavy=True."]
    if note:
        limitations.append(note)
    return check_type(status=CheckStatus.UNAVAILABLE, limitations=limitations)


def _faces(frames, classifier, config, panel_factory) -> FacesCheck:
    if panel_factory:
        return analyze_faces(frames, classifier, config, panel_models=PANEL_MODELS, factory=panel_factory)
    return analyze_faces(frames, classifier, config)


def _audio_checks(
    path: Path, config: MediaConfig, transcriber: SpeechTranscriber | None, detectors
) -> tuple[SpeechCheck, AudioSyntheticCheck]:
    """Run the speech checks, each within its limit. A stuck model keeps running in the background, unused."""
    try:
        track = extract_audio(path, config)
    except AudioUnavailable as exc:
        return (
            SpeechCheck(status=CheckStatus.UNAVAILABLE, limitations=[str(exc)]),
            AudioSyntheticCheck(status=CheckStatus.UNAVAILABLE, limitations=[str(exc)]),
        )
    active = transcriber or WhisperTranscriber(config)
    try:
        speech = _with_time_limit(lambda: transcribe_speech(track, config, active), config.speech_time_limit_s)
    except TimeoutError:
        speech = SpeechCheck(
            status=CheckStatus.UNAVAILABLE,
            limitations=[f"Speech-to-text didn't finish within {config.speech_time_limit_s:.0f} seconds."],
        )
    try:
        synthetic = _with_time_limit(lambda: detect_synthetic_speech(track, config, detectors), config.audio_time_limit_s + 30)
    except TimeoutError:
        synthetic = AudioSyntheticCheck(
            status=CheckStatus.UNAVAILABLE,
            limitations=[f"Synthetic speech checks didn't finish within {config.audio_time_limit_s + 30:.0f} seconds."],
        )
    return speech, synthetic


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
                f"Model synthetic-class signal of {out_of_100(check.score)} across {check.items_scored} keyframes "
                f"(range {check.score_min * 100:.2f} to {check.score_max * 100:.2f})."
            )
        ]
        elevated = [f"{f.timestamp_s:.1f}s" for f in frames if (f.model_score or 0) >= config.elevated_score]
        if elevated:
            lines.append(f"Keyframes with elevated model signals: {', '.join(elevated)}.")
    else:
        lines = [f"Model synthetic-class signal of {out_of_100(check.score)}."]
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
    panel: DetectorPanelCheck | None = None,
    fingerprint: FingerprintCheck | None = None,
    credentials: ContentCredentialsCheck | None = None,
    forensics: ForensicsCheck | None = None,
    extras: dict[str, object] | None = None,
) -> MediaAnalysisResult:
    evidence = [
        *_classifier_evidence(classifier, keyframes.frames, config),
        *_phash_evidence(phash),
        *metadata.indicators,
        *_fingerprint_evidence(fingerprint),
        *_credentials_evidence(credentials),
        *_forensics_evidence(forensics),
    ]
    limitations = [*extra_limitations]
    if classifier.band is ModelBand.LOW and (phash.matches or metadata.generator_hint):
        limitations.append("Signals disagree: the model score is low, but other checks found signals.")
    for check in (classifier, phash, metadata, keyframes):
        limitations.extend(check.limitations)
    if phash.matches:
        limitations.append(PHASH_CAVEAT)

    assessment, summary = _assess(metadata, classifier, phash)
    extras = extras or {}
    return MediaAnalysisResult(
        extracted_text=_extracted_text(extras.get("ocr"), extras.get("speech")),
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
        checks=MediaChecks(
            metadata=metadata,
            classifier=classifier,
            phash=phash,
            keyframes=keyframes,
            detector_panel=panel,
            fingerprint=fingerprint,
            content_credentials=credentials,
            forensics=forensics,
            **extras,
        ),
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


def _analyze_image(path, info, classifier, index, note, config, panel_factory=None, cases=None) -> MediaAnalysisResult:
    try:
        image, metadata, limitations = read_image(path, config)
    except ImportError:
        return _rejected(MediaInputError("dependency_missing", "Pillow is not installed."), info)
    except MediaInputError as exc:
        return _rejected(exc, info)

    check = _apply_size_limit(_classifier_check(classifier, _predict(classifier, [image]), config), image, config)
    hashes = _safe_fingerprints(image)
    fingerprint = _fingerprint_check(info.sha256, [QueryFrame(None, hashes)], hashes, index, cases, config)
    fingerprint.local_features = _safe_local_features([image])
    return _finish(
        info,
        metadata,
        check,
        _image_phash(image, index, note, config),
        KeyframeCheck(status=CheckStatus.NOT_APPLICABLE),
        limitations,
        config,
        _detector_panel([image], check, config, panel_factory, is_image=True) if panel_factory else None,
        fingerprint,
        read_credentials(path, config),
        run_forensics(path, image, info.container, config),
        {
            "faces": _faces([(None, image)], classifier, config, panel_factory),
            "ocr": read_text([(None, image)], config),
        },
    )


def _analyze_video(
    path, info, classifier, index, note, config, panel_factory=None, cases=None, run_heavy=False, transcriber=None, detectors=None
) -> MediaAnalysisResult:
    try:
        video, frames, limitations = extract_keyframes(path, config)
    except ImportError:
        return _rejected(MediaInputError("dependency_missing", "OpenCV is not installed."), info)
    except MediaInputError as exc:
        return _rejected(exc, info)

    scores = _predict(classifier, [frame.image for frame in frames])
    phash, hashes = _video_phash(frames, index, note, config)
    frame_scores: Sequence[float | None] = scores if isinstance(scores, list) else [None] * len(frames)
    frame_hashes = [_safe_fingerprints(frame.image) for frame in frames]
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
                fingerprints=frame_fingerprints,
            )
            for frame, frame_hash, score, frame_fingerprints in zip(
                frames, hashes, frame_scores, frame_hashes, strict=True
            )
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
    check = _classifier_check(classifier, scores, config)
    panel = None
    if panel_factory:
        panel = _detector_panel([frame.image for frame in frames], check, config, panel_factory, is_image=False)
    queries = [QueryFrame(frame.timestamp_s, value) for frame, value in zip(frames, frame_hashes, strict=True)]
    fingerprint = _fingerprint_check(info.sha256, queries, {}, index, cases, config)
    fingerprint.local_features = _safe_local_features(frame.image for frame in frames)
    credentials = read_credentials(path, config)
    forensics = ForensicsCheck(
        status=CheckStatus.NOT_APPLICABLE,
        limitations=["Pixel forensics run on images only. Video compression hides these traces, and video wasn't measured."],
    )
    timed_frames = [(frame.timestamp_s, frame.image) for frame in frames]
    if run_heavy:
        speech, synthetic = _audio_checks(path, config, transcriber, detectors)
        frame_scores_check = score_frames(path, classifier, config)
    else:
        speech = _not_requested(SpeechCheck)
        synthetic = _not_requested(AudioSyntheticCheck)
        frame_scores_check = _not_requested(FramesCheck, FRAMES_LIMITATIONS[-1])
    extras = {
        "faces": _faces(timed_frames, classifier, config, panel_factory),
        "ocr": read_text(timed_frames, config),
        "speech": speech,
        "audio_synthetic": synthetic,
        "frames": frame_scores_check,
    }
    return _finish(info, metadata, check, phash, keyframes, [], config, panel, fingerprint, credentials, forensics, extras)


def _audio_only(path: Path) -> bool:
    """True for a video container holding sound and no pictures, such as a voice note saved as WebM."""
    try:
        import av

        with av.open(str(path)) as container:
            kinds = {stream.type for stream in container.streams}
    except Exception:  # noqa: BLE001 - an unreadable file is reported by the video path.
        return False
    return "audio" in kinds and "video" not in kinds


def _analyze_audio(path, info, config, transcriber=None, detectors=None) -> MediaAnalysisResult:
    """Read and check speech in an audio file. It gets no score, because no measured detector gives one."""
    track = None
    try:
        track = extract_audio(path, config)
    except AudioReaderMissing:
        pass  # The file may be fine, so it isn't rejected. The checks below report what's missing.
    except AudioUnavailable as exc:
        return _rejected(MediaInputError("corrupt_media", str(exc)), info)
    else:
        if track is None:
            return _rejected(MediaInputError("corrupt_media", "This file has no audio track."), info)
    speech, synthetic = _audio_checks(path, config, transcriber, detectors)
    base = empty_checks("This check is for images and video, so it wasn't run on an audio file.")
    not_run = {
        name: getattr(base, name).model_copy(update={"status": CheckStatus.NOT_APPLICABLE})
        for name in ("classifier", "phash", "keyframes", "fingerprint", "content_credentials", "forensics", "faces", "ocr")
    }
    metadata = MetadataCheck(status=CheckStatus.COMPLETE, format=info.container, duration_s=track.duration_s if track else None)
    evidence = [
        f"{result.model_id} gave a mean synthetic speech score of {out_of_100(result.score_mean)} over {result.windows_scored} window(s)."
        for result in synthetic.detectors
        if result.status is CheckStatus.COMPLETE and result.score_mean is not None
    ]
    if speech.segments:
        evidence.append(f"Speech was read in {len(speech.segments)} section(s).")
    ran = CheckStatus.COMPLETE in (speech.status, synthetic.status)
    return MediaAnalysisResult(
        extracted_text=_extracted_text(None, speech),
        media_type=info.media_type,
        status=CheckStatus.COMPLETE if ran else CheckStatus.UNAVAILABLE,
        score=None,
        assessment=Assessment.INCONCLUSIVE,
        summary=(
            "Speech was read and checked by synthetic speech models. These scores are signals, not proof that a voice is real or synthetic."
            if ran
            else "The speech checks could not run on this audio."
        ),
        evidence=evidence,
        limitations=_dedupe([*speech.limitations, *synthetic.limitations]),
        sha256=info.sha256,
        size_bytes=info.size_bytes,
        checks=MediaChecks(metadata=metadata, speech=speech, audio_synthetic=synthetic, **not_run),
    )


def analyze_media(
    path: str | Path,
    *,
    classifier: ImageClassifier | None = None,
    hash_index: HashIndex | None = None,
    config: MediaConfig | None = None,
    run_panel: bool = False,
    panel_factory: ClassifierFactory = build_classifier,
    case_store: CaseFingerprintStore | None = None,
    run_heavy: bool | None = None,
    transcriber: SpeechTranscriber | None = None,
    audio_detectors: Sequence[tuple[str, str, AudioDetector]] | None = None,
) -> MediaAnalysisResult:
    """Analyze one image, video or audio file.

    Expected failures (bad input, missing weights, broken index) are reported in
    the result rather than raised, so the wider pipeline keeps working.

    ``run_panel`` also runs every detector on the panel. It is slow on CPU, so it
    is off by default, and it never changes the overall score or assessment.

    ``run_heavy`` also runs a video's speech-to-text, synthetic speech and frame by
    frame checks. Left unset, it follows MEDIA_RUN_HEAVY_CHECKS. These never change
    the overall score or assessment either.
    """
    config = config or MediaConfig.from_env()
    path = Path(path)
    try:
        info = inspect_input(path, config)
    except MediaInputError as exc:
        return _rejected(exc)

    if info.media_type is MediaType.AUDIO or (info.media_type is MediaType.VIDEO and _audio_only(path)):
        return _analyze_audio(path, replace(info, media_type=MediaType.AUDIO), config, transcriber, audio_detectors)

    classifier = classifier or default_classifier(config)
    index, note = _resolve_index(config, hash_index)
    panel = panel_factory if run_panel else None
    if info.media_type is MediaType.IMAGE:
        return _analyze_image(path, info, classifier, index, note, config, panel, case_store)
    heavy = config.run_heavy_checks if run_heavy is None else run_heavy
    return _analyze_video(path, info, classifier, index, note, config, panel, case_store, heavy, transcriber, audio_detectors)
