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
from backend.media.content_credentials import (
    CONTENT_CHANGED,
    INVALID,
    NOT_ON_TRUST_LIST,
    ON_TRUST_LIST,
    RULES_FAILED,
    SOURCE_MEANINGS,
    UNSIGNED,
)
from backend.media.fingerprint import EXACT_COPY, MATCH_LIMITS, MATCHES_NEEDED
from backend.media.models import (
    CheckStatus,
    ClassifierCheck,
    ContentCredentialsCheck,
    DetectorPanelCheck,
    DetectorResult,
    FingerprintCheck,
    FingerprintMatch,
    KeyframeCheck,
    MediaAnalysisResult,
    MediaType,
    MetadataCheck,
    ModelBand,
    PHashCheck,
)

BENCHMARK_PATH = Path(__file__).resolve().parents[2] / "data" / "eval" / "commons_licensed_2026-11-05.json"
BENCHMARK_APPLIES_TO = (
    "Whole images from Wikimedia Commons: AI-generated and edited fakes, and real photos of people, landscapes, "
    "animals and architecture."
)
BENCHMARK_GAPS = "The benchmark did not measure face swaps, video, or images re-saved by social media."
# Below this AUC, fake and real images are barely separated, and the result should say so.
NEAR_GUESSING_AUC = 0.6
FINGERPRINT_RESULTS_PATH = BENCHMARK_PATH.with_name("fingerprints_2026-11-05.json")
FINGERPRINT_RULE = "any_two_structural"
FINGERPRINT_MEANING = (
    "A fingerprint is not a signature. A match shows that images look alike or that files are identical, not who made "
    "the media, where it first appeared or whether a claim about it is true. A recorded date is only the earliest one "
    "on that list."
)
CREDENTIALS_MEANING = (
    "Content Credentials can show who signed a file and that it hasn't changed since. They don't show that what it "
    "depicts is true, and a signature means only as much as the signer does."
)
UNSIGNED_REASONING = (
    "No Content Credentials were found. This proves nothing: most files have none, and most sites remove them when "
    "they re-save a file. It doesn't make the media more or less likely to be fake."
)
INVALID_MEANING = (
    "This doesn't show the media is fake. Ordinary edits by tools that don't update credentials can cause it too. "
    "Nothing the credentials say is shown, because it can't be tied to this file."
)
RULES_FAILED_MEANING = (
    "Files signed properly at the time can end up like this, so it isn't a sign of tampering, and it doesn't show the "
    "media is fake. But the signature can't be relied on, so what follows is unverified."
)
TRUST_SENTENCES = {
    ON_TRUST_LIST: "The signing certificate leads to an authority on the trust list.",
    NOT_ON_TRUST_LIST: "The signing certificate doesn't lead to anyone on the trust list, so names in it are only claims.",
}
TRUST_NOT_CHECKED = (
    "The signing certificate was not compared with a trust list. Anyone can make a certificate with any name in it, "
    "so names in it are only claims."
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
        if benchmark["auc"] is not None and benchmark["auc"] < NEAR_GUESSING_AUC:
            limitations.append(
                f"When measured, this detector separated fake from real images little better than guessing "
                f"(AUC {benchmark['auc']:.2f}, where 0.50 is guessing)."
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


def load_fingerprint_figures(path: Path = FINGERPRINT_RESULTS_PATH) -> dict[str, dict[str, Any]] | None:
    """Return the test-split figures for the match rule in use, or None if they can't be read or don't apply."""
    raw = _read_results(path)
    if raw is None:
        return None
    try:
        document = json.loads(raw)
        rule = document["test_split"][FINGERPRINT_RULE]
        if rule["limits"] != MATCH_LIMITS or rule["needed"] != MATCHES_NEEDED:
            return None
        return rule
    except (KeyError, TypeError, ValueError):
        return None


def _fingerprint_figures_sentence() -> str:
    rule = load_fingerprint_figures()
    if rule is None:
        return "How well this match rule works has not been measured."
    copies = rule["copies_matched"]

    def share(name: str) -> str:
        return f"{copies[name]['count']} of {copies[name]['total']}"

    wrong = rule["false_match_rate"]
    return (
        f"When measured on simulated changes, the rule found {share('recompressed_low_quality')} recompressed copies, "
        f"{share('cropped_5_percent_each_side')} cropped copies, {share('caption_bar_added')} captioned copies and "
        f"{share('mirrored')} mirrored copies, and {wrong['count']} of {wrong['total']} unrelated pairs matched."
    )


def _describe_target(match: FingerprintMatch) -> str:
    if match.found_in == "reference":
        return f"reference {match.label!r}"
    return f"earlier case {match.case_id!r}"


def _match_artifact(match: FingerprintMatch) -> dict[str, str]:
    artifact = {"kind": "fingerprint_match", "match": match.kind, "found_in": match.found_in}
    for name in ("label", "case_id", "first_seen", "source"):
        value = getattr(match, name)
        if value:
            artifact[name] = str(value)
    if match.distances:
        artifact["distances"] = ", ".join(f"{kind} {value}" for kind, value in match.distances.items())
    if match.timestamp_s is not None:
        artifact["timestamp_s"] = f"{match.timestamp_s:.1f}"
    return artifact


def _fingerprint(check: FingerprintCheck) -> dict[str, Any]:
    label = "Image fingerprints"
    if check.status is not CheckStatus.COMPLETE:
        return _check(
            "media.fingerprint", label, check.status, "No fingerprints", "The fingerprints were not made.", check.limitations
        )
    artifacts = [_match_artifact(match) for match in check.matches]
    if check.hashes or check.sha256:
        artifacts.insert(0, {"kind": "fingerprints", **({"sha256": check.sha256} if check.sha256 else {}), **check.hashes})
    exact = [match for match in check.matches if match.kind == EXACT_COPY]
    visual = [match for match in check.matches if match.kind != EXACT_COPY]
    if not check.compared:
        result = "Made, not compared"
        reasoning = "Fingerprints were made, but there was nothing to compare them with, so this found nothing either way."
    elif check.matches:
        parts = []
        if exact:
            parts.append(f"{len(exact)} exact {'copy' if len(exact) == 1 else 'copies'}")
        if visual:
            parts.append(f"{len(visual)} likely same {'image' if len(visual) == 1 else 'images'}")
        result = ", ".join(parts)
        reasoning = "Matched " + "; ".join(_describe_target(match) for match in check.matches) + "."
        if exact:
            reasoning += " An exact copy means the file is byte-for-byte the same."
        if visual:
            reasoning += " A likely match means at least two kinds of fingerprint agree, so the picture may have been changed."
    else:
        result = f"No match in {check.references_checked} references and {check.earlier_cases_checked} earlier cases"
        reasoning = "Nothing compared looks like this media. It doesn't show the media is new, only that these lists don't hold it."
    if check.frames_hashed > 1:
        reasoning += f" {check.frames_hashed} video keyframes were compared one at a time."
    return _check(
        "media.fingerprint",
        label,
        check.status,
        result,
        f"{reasoning} {_fingerprint_figures_sentence()}",
        [*check.limitations, FINGERPRINT_MEANING],
        artifacts=artifacts,
    )


def _credentials_artifact(check: ContentCredentialsCheck) -> dict[str, str]:
    values = {
        "kind": "content_credentials",
        "state": check.state,
        "signer_trust": check.signer_trust,
        "invalid_reason": check.invalid_reason,
        "signer_organisation": check.signer_organisation,
        "claim_generator": check.claim_generator,
        "signed_at": check.signed_at,
        "declared_sources": ", ".join(check.declared_sources),
        "declared_in_history": ", ".join(check.declared_in_history),
        "failure_codes": ", ".join(check.failure_codes),
    }
    return {name: value for name, value in values.items() if value}


def _describe_claims(check: ContentCredentialsCheck) -> list[str]:
    parts = []
    if check.signer_organisation:
        parts.append(f"The certificate names {check.signer_organisation!r}.")
    if check.claim_generator:
        parts.append(f"The credentials say they were written by {check.claim_generator!r}.")
    if check.signed_at:
        parts.append(f"They give the signing time as {check.signed_at}.")
    if check.declared_sources:
        declared = "; ".join(SOURCE_MEANINGS[source] for source in check.declared_sources)
        parts.append(f"They declare the media was {declared}.")
    if check.declared_in_history:
        declared = "; ".join(SOURCE_MEANINGS[source] for source in check.declared_in_history)
        parts.append(f"Earlier steps in its history declare it was {declared}.")
    if check.declared_sources or check.declared_in_history:
        parts.append("That is the signer's statement, not something TrustFeed tested.")
    return parts


def _rules_failed_finding(check: ContentCredentialsCheck) -> str:
    reasons = []
    if "signingCredential.expired" in check.failure_codes:
        reasons.append(
            "the signing certificate has expired"
            + ("" if check.signed_at else " and no timestamp shows it was signed before that")
        )
    if "signingCredential.invalid" in check.failure_codes:
        reasons.append("the signing certificate doesn't meet the standard's requirements")
    if "assertion.action.malformed" in check.failure_codes:
        reasons.append("the recorded actions don't follow the standard's format")
    return f"The file matches its Content Credentials, but they break the standard's rules: {'; '.join(reasons)}."


def _invalid_reasoning(check: ContentCredentialsCheck) -> str:
    if check.invalid_reason == RULES_FAILED:
        return " ".join([_rules_failed_finding(check), RULES_FAILED_MEANING, *_describe_claims(check)])
    if check.invalid_reason == CONTENT_CHANGED:
        return f"The file carries Content Credentials, but it has changed since they were signed. {INVALID_MEANING}"
    return f"The file carries Content Credentials, but they are damaged or failed validation. {INVALID_MEANING}"


def _content_credentials(check: ContentCredentialsCheck) -> dict[str, Any]:
    check_id, label = "media.c2pa", "Content Credentials"
    if check.status is not CheckStatus.COMPLETE or check.state is None:
        return _check(check_id, label, check.status, "Not checked", "Whether this file is signed is unknown.", check.limitations)
    artifacts = [_credentials_artifact(check)]
    if check.state == UNSIGNED:
        return _check(check_id, label, check.status, "Unsigned", UNSIGNED_REASONING, check.limitations, artifacts=artifacts)
    no_effect = "This check does not change the overall score or assessment."
    if check.state == INVALID:
        return _check(
            check_id,
            label,
            check.status,
            "Invalid",
            _invalid_reasoning(check),
            [*check.limitations, CREDENTIALS_MEANING, no_effect],
            artifacts=artifacts,
        )
    parts = [
        "The file carries Content Credentials and the signature is valid, so it has not changed since it was signed.",
        TRUST_SENTENCES.get(check.signer_trust or "", TRUST_NOT_CHECKED),
        *_describe_claims(check),
    ]
    return _check(
        check_id,
        label,
        check.status,
        "Signed",
        " ".join(parts),
        [*check.limitations, CREDENTIALS_MEANING, no_effect],
        artifacts=artifacts,
    )


def load_comparison(path: Path = BENCHMARK_PATH) -> tuple[dict[str, dict[str, Any]], float | None]:
    """Return each model's measured comparison by "id@revision", and the baseline's test AUC."""
    raw = _read_results(path)
    if raw is None:
        return {}, None
    try:
        comparison = json.loads(raw)["comparison"]
        models = {entry["model"]: entry for entry in comparison["models"]}
        return models, models[comparison["baseline"]]["test_split"]["auc"]
    except (KeyError, TypeError, ValueError):
        return {}, None


def _why_counted(detector: DetectorResult, models: dict[str, dict[str, Any]], baseline_auc: float | None) -> str:
    if detector.counted:
        return "Counted: this is the detector behind the overall model score."
    entry = models.get(f"{detector.model_id}@{detector.model_revision}")
    measured = entry["test_split"]["auc"] if entry else None
    if measured is None or baseline_auc is None:
        return "Shown, not counted: it has not been measured."
    figures = f"AUC {measured:.2f}, against {baseline_auc:.2f} for the detector in use"
    if entry["difference_from_baseline"]["adds_value"]:
        return f"Shown, not counted: it measured better ({figures}), but counting it has not been decided."
    return f"Shown, not counted: it did not measure better ({figures})."


def _describe_detector(detector: DetectorResult, why: str) -> str:
    if detector.status is not CheckStatus.COMPLETE or detector.score is None:
        return f"{detector.model_id}: no result. {why}"
    band = detector.band.value if detector.band else "no"
    return f"{detector.model_id}: {detector.score:.4f}, {band} band. {why}"


def _detector_artifact(detector: DetectorResult, why: str) -> dict[str, str]:
    artifact = {
        "kind": "detector_result",
        "model_id": detector.model_id,
        "status": detector.status.value,
        "counted": "true" if detector.counted else "false",
        "why": why,
    }
    if detector.model_revision:
        artifact["model_revision"] = detector.model_revision
    if detector.score is not None:
        artifact["score"] = f"{detector.score:.4f}"
    if detector.band is not None:
        artifact["band"] = detector.band.value
    return artifact


def _detector_panel(check: DetectorPanelCheck, media_type: MediaType) -> dict[str, Any]:
    label = "All AI image detectors"
    models, baseline_auc = load_comparison()
    whys = [_why_counted(detector, models, baseline_auc) for detector in check.detectors]
    ran = [detector for detector in check.detectors if detector.status is CheckStatus.COMPLETE]
    bands = {band: sum(detector.band is band for detector in ran) for band in ModelBand}
    result = (
        f"{len(ran)} of {len(check.detectors)} detectors ran: {bands[ModelBand.ELEVATED]} elevated, "
        f"{bands[ModelBand.INCONCLUSIVE]} inconclusive, {bands[ModelBand.LOW]} low"
    )
    lines = [_describe_detector(detector, why) for detector, why in zip(check.detectors, whys, strict=True)]
    opening = "Each detector gave its own signal, and they are not votes."
    if bands[ModelBand.ELEVATED] and bands[ModelBand.LOW]:
        opening += " They disagree on this media, so read none of them as settled."
    if media_type is MediaType.VIDEO:
        opening += " Accuracy on video has not been measured."
    limitations = list(check.limitations)
    for detector in check.detectors:
        limitations.extend(detector.limitations)
    return _check(
        "media.detector_panel",
        label,
        check.status,
        result,
        " ".join([opening, *lines]),
        limitations,
        # Figures for several models don't fit one benchmark entry, and the dashboard reads that field as one model.
        artifacts=[_detector_artifact(d, why) for d, why in zip(check.detectors, whys, strict=True)],
    )


def build_checks(
    result: MediaAnalysisResult, *, config: MediaConfig | None = None, heatmap_url: str | None = None
) -> list[dict[str, Any]]:
    config = config or MediaConfig.from_env()
    checks = [
        _classifier(result.checks.classifier, result.media_type, config, heatmap_url),
        _metadata(result.checks.metadata),
        _phash(result.checks.phash),
        _keyframes(result.checks.keyframes),
    ]
    if result.checks.fingerprint is not None:
        checks.append(_fingerprint(result.checks.fingerprint))
    if result.checks.content_credentials is not None:
        checks.append(_content_credentials(result.checks.content_credentials))
    if result.checks.detector_panel is not None:
        checks.append(_detector_panel(result.checks.detector_panel, result.media_type))
    return checks
