"""Compare what a post's caption, on-screen text and speech say.

A conflict between them is a reason to look closer, not proof of manipulation: a caption can
rightly report what a clip contradicts, and text read from media contains errors. This has not
been measured on labelled data, so it never changes a score.
"""

from __future__ import annotations

from collections.abc import Mapping
from itertools import combinations
from typing import Any

from backend.api.app.models import CrossModalAnalysis, CrossModalConflict, ImageCaptionCheck, ModuleStatus
from backend.text.claim_report import analyze_claims
from backend.text.claims import AnalyzedClaim, split_claims
from backend.text.consistency import _pair_findings

CHANNEL_NAMES = {"caption": "the caption", "ocr": "the on-screen text", "speech": "the speech"}
_MAX_ITEMS = 40
_MAX_ITEM_CHARS = 2_000
_MAX_CONFLICTS = 15
_QUOTE_CHARS = 160

CLIP_MODEL = "openai/clip-vit-base-patch32"
CLIP_REVISION = "3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268"
CLIP_REASON = (
    f"Not run. {CLIP_MODEL} at commit {CLIP_REVISION[:7]} offers no safetensors weights, only pickle-based "
    "and other formats we don't load, and its Hub listing declares no licence."
)
LIMITATIONS = [
    "Only dates, places, figures and direct negation are compared, so most kinds of mismatch would be missed.",
    "Text read from images and speech contains errors, which can look like conflicts.",
    "A difference is a reason to look closer, not proof of manipulation. A caption can rightly dispute a clip.",
    "Finding no conflict does not show that the caption describes the media.",
    "This has not been measured on labelled data, so it does not change any score.",
]


def _clean_items(value: Any) -> list[str]:
    """Media text comes from another module and from the file itself, so its shape isn't trusted."""
    if not isinstance(value, (list, tuple)):
        return []
    # The media check sends records with a "text" field. Plain strings are accepted too.
    texts = [item.get("text") if isinstance(item, dict) else item for item in value[:_MAX_ITEMS]]
    return [item.strip()[:_MAX_ITEM_CHARS] for item in texts if isinstance(item, str) and item.strip()]


def _channels(caption: str | None, extracted: Mapping[str, Any] | None) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    if caption and caption.strip():
        found["caption"] = [caption]
    for name in ("ocr", "speech"):
        items = _clean_items((extracted or {}).get(name))
        if items:
            found[name] = items
    return found


def _quote(claim: AnalyzedClaim) -> str:
    return claim.text[:_QUOTE_CHARS]


def _channel_level(left: str, right: str, a: list[AnalyzedClaim], b: list[AnalyzedClaim]) -> list[CrossModalConflict]:
    """Media text is rarely worded like its caption, so also compare what each channel mentions overall."""
    conflicts: list[CrossModalConflict] = []
    pair = f"{CHANNEL_NAMES[left]} and {CHANNEL_NAMES[right]}"
    dates_a = [item for claim in a for item in claim.dates if not item.impossible]
    dates_b = [item for claim in b for item in claim.dates if not item.impossible]
    if dates_a and dates_b and all(x.conflicts_with(y) for x in dates_a for y in dates_b):
        conflicts.append(
            CrossModalConflict(
                channels=[left, right],
                kind="dates",
                severity="note",
                explanation=f"{pair} mention different dates, and none match: {dates_a[0].text} and {dates_b[0].text}.",
            )
        )
    places_a = {place for claim in a for place in claim.places}
    places_b = {place for claim in b for place in claim.places}
    if places_a and places_b and not places_a & places_b:
        conflicts.append(
            CrossModalConflict(
                channels=[left, right],
                kind="places",
                severity="note",
                explanation=(
                    f"{pair} mention different places, and none match: {', '.join(sorted(places_a)[:3])} and "
                    f"{', '.join(sorted(places_b)[:3])}. One place may lie inside the other."
                ),
            )
        )
    return conflicts


def _analyze(items: list[str]) -> tuple[list[AnalyzedClaim], int, str, str | None]:
    units = [unit for item in items for unit in split_claims(item)]
    report = analyze_claims(units)
    return [claim for claim in report.claims if claim.checkable], report.omitted_claims, report.ner_status, report.ner_reason


def compare_channels(caption: str | None, extracted_text: Mapping[str, Any] | None) -> CrossModalAnalysis:
    """Compare every pair of channels. Fewer than two means there was nothing to compare, and it says so."""
    image_caption = ImageCaptionCheck(status=ModuleStatus.UNAVAILABLE, reason=CLIP_REASON)
    channels = _channels(caption, extracted_text)
    base = {"channels": sorted(channels), "image_caption": image_caption, "limitations": LIMITATIONS}
    if len(channels) < 2:
        reason = (
            "No text from the media arrived, as the media check doesn't provide it yet."
            if extracted_text is None
            else "Fewer than two of caption, on-screen text and speech had any words to compare."
        )
        return CrossModalAnalysis(status=ModuleStatus.NOT_APPLICABLE, reason=reason, **base)

    analyzed = {name: _analyze(items) for name, items in channels.items()}
    conflicts: list[CrossModalConflict] = []
    for left, right in combinations(channels, 2):
        claims_a, claims_b = analyzed[left][0], analyzed[right][0]
        direct: set[str] = set()
        for a in claims_a:
            for b in claims_b:
                for kind, severity, text in _pair_findings(a, b):
                    direct.add(kind)
                    conflicts.append(
                        CrossModalConflict(
                            channels=[left, right], kind=kind, severity=severity, explanation=text, left_quote=_quote(a), right_quote=_quote(b)
                        )
                    )
        conflicts += [item for item in _channel_level(left, right, claims_a, claims_b) if item.kind not in direct]

    omitted = sum(item[1] for item in analyzed.values())
    unavailable = next((item[3] for item in analyzed.values() if item[2] != "complete"), None)
    limits = list(LIMITATIONS)
    if unavailable:
        limits.insert(0, f"Places could not be compared: {unavailable}")
    if omitted:
        limits.insert(0, f"{omitted} statements were left out, because there were too many to compare.")
    if any(item.severity == "conflict" for item in conflicts):
        assessment = "conflicts_found"
    else:
        assessment = "notes_only" if conflicts else "none_found"
    return CrossModalAnalysis(
        status=ModuleStatus.COMPLETE,
        assessment=assessment,
        channels=sorted(channels),
        conflicts=conflicts[:_MAX_CONFLICTS],
        image_caption=image_caption,
        limitations=limits,
    )


def cross_modal_checks(analysis: CrossModalAnalysis) -> list[dict[str, Any]]:
    found = len(analysis.conflicts)
    return [
        {
            "check_id": "text.cross_modal",
            "module": "text",
            "label": "Caption, on-screen text and speech",
            "status": analysis.status.value,
            "result": f"{found} difference(s) found." if analysis.status is ModuleStatus.COMPLETE else "Not compared.",
            "reasoning": [item.explanation for item in analysis.conflicts]
            or (analysis.reason or f"Compared {', '.join(analysis.channels)} and found no difference in dates, places, figures or negation."),
            "limitations": analysis.limitations,
        },
        {
            "check_id": "text.image_caption",
            "module": "text",
            "label": "Image and caption match",
            "status": analysis.image_caption.status.value,
            "result": "Not run.",
            "reasoning": analysis.image_caption.reason or "",
            "limitations": [],
        },
    ]
