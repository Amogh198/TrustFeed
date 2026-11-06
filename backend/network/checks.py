"""Explanation checks: what the network lane searched, found and cannot show.

The shape follows the draft for ``GET /api/cases/{id}/explanation``. If the version T3
publishes differs, it wins. ``benchmark`` stays null because nothing here is measured
on labelled real data, and no number is ever invented to fill it.
"""

from collections import Counter
from typing import Any

MODULE = "network"
_NOT_PROOF = (
    "Posting the same items close together does not establish intent, common control, automation "
    "or who is behind an account."
)
_EARLIEST = (
    "The earliest post found is only the earliest found. It is not shown to be the source, "
    "and earlier posts may exist elsewhere or may be deleted."
)
_AUTHENTICITY = "This describes how content spread, not whether the content is authentic or true."
_MATCH_WORDING = {
    "link": "carry the submitted link",
    "page_link": "link to a page where the image was found, and may be about something else on that page",
    "hashtag": "use the searched hashtag, which may be used for other things too",
    "text": "contain the submitted text",
}


from backend.network.significance import significance_checks  # noqa: E402


def _check(
    check_id: str,
    label: str,
    result: str,
    reasoning: str,
    limitations: list[str],
    artifacts: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "module": MODULE,
        "label": label,
        "result": result,
        "reasoning": reasoning,
        "benchmark": None,
        "artifacts": artifacts or [],
        "limitations": limitations,
    }


def _search_check(coverage: dict[str, Any] | None, synthetic: bool) -> dict[str, Any]:
    label = "Public platforms searched"
    if coverage is None:
        if synthetic:
            result = "No platform was searched. This case uses synthetic demo data."
        else:
            result = "No public-platform search ran for this case."
        return _check(
            "network.platform_search",
            label,
            result,
            "Spread can only be described from posts that were actually read.",
            ["Without a search, nothing can be said about how this content spread on real platforms."],
        )

    platforms = coverage["platforms"]
    read = [item["label"] for item in platforms if item["status"] in ("searched", "partial")]
    prefix = "Replayed synthetic posts from" if coverage.get("synthetic") else "Searched"
    result = f"{prefix} {len(read)} of {len(platforms)} connected platforms: {', '.join(read) or 'none'}."
    notes = [f"{item['label']}: {note}" for item in platforms for note in item.get("notes", [])]
    not_connected = [
        f"Not connected, {item['platform']}: {item['reason']}" for item in coverage.get("not_connected", [])
    ]
    return _check(
        "network.platform_search",
        label,
        result,
        "This sets the limit of everything else in this module: only these platforms were read.",
        [
            "Public search does not return every post, so finding nothing does not show the content wasn't shared.",
            *notes,
            *not_connected,
        ],
    )


def _posts_check(coverage: dict[str, Any] | None) -> dict[str, Any] | None:
    if coverage is None:
        return None
    spread = coverage["spread"]
    label = "Matching public posts"
    if not spread:
        return _check(
            "network.matching_posts",
            label,
            "No matching public posts were found.",
            "A post counts only if it really carries the searched link, hashtag or text.",
            ["This is inconclusive. The content may exist on these platforms or elsewhere without being found."],
        )

    counts = Counter(item.get("matched_on", "unspecified") for item in spread)
    first = spread[0]
    parts = [f"{count} {_MATCH_WORDING.get(kind, kind + ' match')}" for kind, count in sorted(counts.items())]
    limitations = [_EARLIEST]
    if counts["hashtag"]:
        limitations.append("A hashtag shows a shared topic, not shared content, so these posts may concern other events.")
    if counts["page_link"]:
        limitations.append("Posts matched through a page link are weaker evidence than posts carrying the submitted link.")
    return _check(
        "network.matching_posts",
        label,
        f"{len(spread)} matching posts. The earliest found is from "
        f"{first.get('posted_at') or 'an undated post'} on {first.get('platform') or 'an unspecified platform'}.",
        f"Of these: {'; '.join(parts)}.",
        limitations,
    )


def _coordination_check(
    case_id: str, payload: dict[str, Any], module_result: dict[str, Any]
) -> dict[str, Any]:
    label = "Repeated co-sharing signal"
    artifacts = [{"type": "network_graph", "route": f"/api/network/{case_id}"}]
    if module_result["status"] != "complete":
        reason = module_result["limitations"][0] if module_result["limitations"] else "No reason was given."
        return _check("network.coordination_signal", label, f"Not available. {reason}", "No posts could be analyzed.", [])

    groups = {node["cluster_id"] for node in payload["nodes"] if node["in_flagged_cluster"]}
    accounts = sum(1 for node in payload["nodes"] if node["in_flagged_cluster"])
    limitations = [_NOT_PROOF, _AUTHENTICITY, "The score is a heuristic, not a calibrated probability."]
    if not groups:
        return _check(
            "network.coordination_signal",
            label,
            "Inconclusive: no group of accounts met the criteria.",
            "Accounts must repeatedly post at least 2 of the same items within 120 seconds of each other.",
            ["This does not show that coordination is absent, as only some posts were read.", *limitations],
            artifacts,
        )
    return _check(
        "network.coordination_signal",
        label,
        f"Signal for review: {accounts} accounts in {len(groups)} group(s), with a score of "
        f"{module_result['score']:.2f} out of 1.",
        "These accounts repeatedly posted the same items within 120 seconds of each other, which is "
        "unusual for unconnected accounts and is worth a person's review.",
        limitations,
        artifacts,
    )


def build_network_checks(
    case_id: str,
    payload: dict[str, Any],
    coverage: dict[str, Any] | None,
    module_result: dict[str, Any],
    tests: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build checks from stored results, so a case saved before a restart still explains itself."""
    synthetic = any(node.get("synthetic") for node in payload["nodes"])
    checks = [
        _search_check(coverage, synthetic),
        _posts_check(coverage),
        _coordination_check(case_id, payload, module_result),
    ]
    found = [check for check in checks if check is not None]
    return [*found, *significance_checks(tests, synthetic)] if tests else found
