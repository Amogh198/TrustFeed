"""Turns a media result into explanation checks: what ran, what it found, why, and how far to trust it.

A benchmark figure appears only if it was measured for this exact model, at these exact bands,
on this kind of media. Otherwise it is null, which the dashboard shows as "Not measured".
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.media.config import MediaConfig
from backend.media.models import (
    CheckStatus,
    ClassifierCheck,
    KeyframeCheck,
    MediaAnalysisResult,
    MediaType,
    MetadataCheck,
    ModelBand,
    PHashCheck,
)

BENCHMARK_PATH = Path(__file__).resolve().parents[2] / "data" / "eval" / "commons_2026-11-05.json"
BENCHMARK_APPLIES_TO = (
    "Whole images from Wikimedia Commons: AI-generated and edited fakes, and real photos of people."
)
BENCHMARK_GAPS = (
    "The benchmark did not measure face swaps, real images other than people, or images re-saved by social media."
)
METADATA_UNTRUSTED = "Metadata comes from the file, so it can be missing, removed or false."
PHASH_MEANING = "A perceptual match shows visual similarity to a reference, not who made the media or if a claim is true."


@lru_cache(maxsize=4)
def _read_results(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def load_benchmark(
    model_id: str | None, revision: str | None, config: MediaConfig, path: Path = BENCHMARK_PATH
) -> dict[str, Any] | None:
    """Return the test-split figures for this model at these bands, or None if unmeasured."""
    raw = _read_results(path)
    if raw is None or model_id is None:
        return None
    try:
        document = json.loads(raw)
        settings = document["settings"]
        if settings["elevated_score"] != config.elevated_score or settings["low_score"] != config.low_score:
            return None
        for model in document["models"]:
            if model["model_id"] == model_id and model["model_revision"] == revision and model["status"] == "complete":
                split = model["current_bands"]["test_split"]
                if split["too_few_to_conclude"]:
                    return None
                return {
                    "dataset": document["sources"][0]["name"],
                    "n_real": split["n"]["real"],
                    "n_fake": split["n"]["fake"],
                    "recall": split["recall"]["value"],
                    "recall_ci95": split["recall"]["ci95"],
                    "false_positive_rate": split["false_positive_rate"]["value"],
                    "fpr_ci95": split["false_positive_rate"]["ci95"],
                    "auc": split["auc"],
                    "flagged_fake": split["confusion"]["fake"]["elevated"],
                    "flagged_real": split["confusion"]["real"]["elevated"],
                    "low_fake": split["confusion"]["fake"]["low"],
                    "low_real": split["confusion"]["real"]["low"],
                    "measured_at": document["generated_at"][:10],
                    "applies_to": BENCHMARK_APPLIES_TO,
                }
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    return None


def _check(
    check_id: str,
    label: str,
    status: CheckStatus,
    result: str,
    reasoning: str,
    limitations: list[str],
    *,
    benchmark: dict[str, Any] | None = None,
    artifacts: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "module": "media",
        "label": label,
        "status": status.value,
        "result": result,
        "reasoning": reasoning,
        "benchmark": benchmark,
        "artifacts": artifacts or [],
        "limitations": list(dict.fromkeys(limitations)),
    }


def _band_reasoning(band: ModelBand | None, benchmark: dict[str, Any] | None) -> str:
    if band is ModelBand.LOW:
        text = "The score is in the low band. This does not show the image is authentic."
        if benchmark:
            text += (
                f" When measured, {benchmark['low_fake']} of {benchmark['n_fake']} fake images also scored low, "
                "so a low score is weak evidence."
            )
        return text
    if band is ModelBand.ELEVATED:
        text = "The score is in the elevated band, so a person should review this media. It is not proof."
        if benchmark:
            text += (
                f" When measured, this band caught {benchmark['flagged_fake']} of {benchmark['n_fake']} fake images "
                f"and wrongly flagged {benchmark['flagged_real']} of {benchmark['n_real']} real ones."
            )
        return text
    return "The score does not clearly point either way, so this check is inconclusive."


def _classifier(
    check: ClassifierCheck, media_type: MediaType, config: MediaConfig, heatmap_url: str | None
) -> dict[str, Any]:
    label = "AI image detector"
    if check.status is not CheckStatus.COMPLETE or check.score is None:
        return _check(
            "media.classifier",
            label,
            check.status,
            "No model result",
            "The detector did not produce a score, so it says nothing about this media.",
            check.limitations,
        )
    # The benchmark used single images, so its figures don't describe a video's combined score.
    benchmark = (
        load_benchmark(check.model_id, check.model_revision, config) if media_type is MediaType.IMAGE else None
    )
    reasoning = (
        f"Model {check.model_id} estimated how likely the media belongs to its synthetic class. "
        f"{_band_reasoning(check.band, benchmark)}"
    )
    if media_type is MediaType.VIDEO:
        reasoning += " Accuracy on video has not been measured."
    limitations = list(check.limitations)
    if benchmark:
        limitations.append(
            f"At the current bands this detector flags very few fakes: {benchmark['flagged_fake']} of "
            f"{benchmark['n_fake']} when measured."
        )
        limitations.append(BENCHMARK_GAPS)
    band = check.band.value if check.band else "no"
    artifacts = [{"kind": "occlusion_heatmap", "url": heatmap_url}] if heatmap_url else []
    return _check(
        "media.classifier",
        label,
        check.status,
        f"{check.score:.4f}, {band} band",
        reasoning,
        limitations,
        benchmark=benchmark,
        artifacts=artifacts,
    )


def _metadata(check: MetadataCheck) -> dict[str, Any]:
    label = "File metadata"
    if check.status is not CheckStatus.COMPLETE:
        return _check(
            "media.metadata", label, check.status, "No metadata read", "The file's metadata was not read.", check.limitations
        )
    parts = [check.format or "Unknown format"]
    if check.width and check.height:
        parts.append(f"{check.width} x {check.height}")
    if check.duration_s is not None:
        parts.append(f"{check.duration_s:.1f} seconds")
    if check.exif_present is not None:
        parts.append("EXIF present" if check.exif_present else "no EXIF")
    if check.has_gps:
        parts.append("GPS data present, not shown")
    if check.generator_hint:
        reasoning = "The metadata names a generator or editing tool, which is worth a person's review."
    else:
        reasoning = "The metadata names no generator. Most sites strip metadata, so this shows very little."
    if check.indicators:
        reasoning += " Found: " + " ".join(check.indicators)
    return _check(
        "media.metadata", label, check.status, ", ".join(parts), reasoning, [*check.limitations, METADATA_UNTRUSTED]
    )


def _phash(check: PHashCheck) -> dict[str, Any]:
    label = "Reference list match"
    if check.status is not CheckStatus.COMPLETE:
        return _check(
            "media.phash", label, check.status, "No comparison", "The perceptual hash was not available.", check.limitations
        )
    if not check.compared:
        result = "Not compared"
        reasoning = "No reference list was available, so this check found nothing either way."
    elif check.matches:
        result = f"{len(check.matches)} matches in {check.references_checked} references"
        reasoning = "The media looks like at least one image on the team's reference list."
    else:
        result = f"No match in {check.references_checked} references"
        reasoning = "Nothing on the reference list looks like this media. A short list makes that very weak evidence."
    return _check("media.phash", label, check.status, result, reasoning, [*check.limitations, PHASH_MEANING])


def _keyframes(check: KeyframeCheck) -> dict[str, Any]:
    label = "Video keyframes"
    if check.status is CheckStatus.NOT_APPLICABLE:
        return _check("media.keyframes", label, check.status, "Not applicable", "This is not a video.", check.limitations)
    if check.status is not CheckStatus.COMPLETE:
        return _check("media.keyframes", label, check.status, "No keyframes", "No frames were sampled.", check.limitations)
    scored = [frame for frame in check.frames if frame.model_score is not None]
    result = f"{len(check.frames)} keyframes"
    if scored:
        strongest = max(scored, key=lambda frame: frame.model_score or 0)
        result += f", strongest score {strongest.model_score:.4f} at {strongest.timestamp_s:.1f}s"
    reasoning = "Frames were sampled at scene changes and scored one at a time. Frames between them were not checked."
    return _check("media.keyframes", label, check.status, result, reasoning, check.limitations)


def build_checks(
    result: MediaAnalysisResult, *, config: MediaConfig | None = None, heatmap_url: str | None = None
) -> list[dict[str, Any]]:
    config = config or MediaConfig.from_env()
    return [
        _classifier(result.checks.classifier, result.media_type, config, heatmap_url),
        _metadata(result.checks.metadata),
        _phash(result.checks.phash),
        _keyframes(result.checks.keyframes),
    ]
