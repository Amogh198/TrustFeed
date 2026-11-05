"""Watch public platforms for a topic: poll, keep what's new and re-analyze the spread.

This is repeated polling of public search, not a complete feed of any platform. Each
snapshot says which platforms were really read on that poll.

Run it from the command line with ``python -m backend.network.watch``.
"""

import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.network.config import CoordinationConfig
from backend.network.dataset import format_timestamp
from backend.network.service import store_trace
from backend.network.sources import (
    Budgeted,
    Fetch,
    PublicPost,
    SearchQuery,
    Source,
    default_sources,
    live_fetch,
)
from backend.network.trace import Collected, TraceResult, assemble_result, collect

_POLL_BUDGET_SECONDS = 25
_READ_STATUSES = ("searched", "partial")


class Monitor:
    """Keep a growing picture of one topic across repeated polls."""

    def __init__(
        self,
        watch_id: str,
        *,
        text: str | None = None,
        url: str | None = None,
        urls: tuple[str, ...] = (),
        hashtags: tuple[str, ...] = (),
        sources: list[Source] | None = None,
        fetch: Fetch = live_fetch,
        config: CoordinationConfig | None = None,
        state_path: Path | None = None,
    ) -> None:
        self.watch_id = watch_id
        self.query = SearchQuery.from_submission(text=text, url=url, watched_urls=urls, hashtags=hashtags)
        if self.query.is_empty():
            raise ValueError("A watch needs text, a link or a hashtag to search for")
        self.sources = default_sources() if sources is None else sources
        self.config = config or CoordinationConfig()
        self.state_path = state_path
        self._fetch = fetch
        self._collected = Collected()
        self._flagged_accounts: set[str] = set()
        self._platforms_read_before: set[str] = set()
        self.polls = 0
        self.latest: TraceResult | None = None
        if state_path and state_path.exists():
            self._load(state_path)

    def poll(self, now: datetime | None = None) -> dict[str, Any]:
        """Search once, store the updated analysis and report what changed."""
        now = now or datetime.now(UTC)
        before = set(self._collected.on_topic)
        budgeted = Budgeted(self._fetch, _POLL_BUDGET_SECONDS)
        collect(self.query, self.sources, budgeted, self._collected)
        result = assemble_result(self.watch_id, self._collected, self.query, self.sources, budgeted, self.config, now)
        self.latest = result
        self.polls += 1
        store_trace(self.watch_id, result)

        snapshot = self._snapshot(result, before, now)
        if self.state_path:
            self._save(self.state_path)
        return snapshot

    def _snapshot(self, result: TraceResult, before: set[str], now: datetime) -> dict[str, Any]:
        new_ids = set(self._collected.on_topic) - before
        platforms = result.coverage["platforms"]
        read = [item["platform"] for item in platforms if item["status"] in _READ_STATUSES]
        new_posts = {
            item["platform"]: sum(1 for post_id in new_ids if self._collected.posts[post_id].platform == item["platform"])
            for item in platforms
        }
        alerts = self._coordination_alerts(result)
        alerts += [
            {
                "type": "platform_unreachable",
                "platform": item["platform"],
                "message": f"{item['label']} could be read before but not on this poll: {'; '.join(item['notes'])}",
            }
            for item in platforms
            if item["platform"] in self._platforms_read_before and item["status"] == "failed"
        ]
        self._platforms_read_before |= set(read)
        return {
            "watch_id": self.watch_id,
            "poll": self.polls,
            "polled_at": format_timestamp(now),
            "platforms_read": read,
            "platforms": platforms,
            "not_connected": result.coverage["not_connected"],
            "new_posts": new_posts,
            "total_matching_posts": len(self._collected.on_topic),
            "alerts": alerts,
            "module_result": result.module_result,
            "synthetic": result.coverage["synthetic"],
        }

    def _coordination_alerts(self, result: TraceResult) -> list[dict[str, Any]]:
        alerts = []
        for cluster in result.analysis.clusters:
            if not cluster["flagged"]:
                continue
            new_accounts = set(cluster["members"]) - self._flagged_accounts
            if new_accounts:
                alerts.append(
                    {
                        "type": "coordination_signal",
                        "cluster_id": cluster["id"],
                        "accounts": cluster["size"],
                        "new_accounts": len(new_accounts),
                        "coordination_risk_score": cluster["coordination_risk_score"],
                        "message": (
                            "A group of accounts repeatedly co-shared items. This is a signal for a person "
                            "to review, not proof of coordination, intent or who is behind it."
                        ),
                    }
                )
            self._flagged_accounts |= new_accounts
        return alerts

    def _save(self, path: Path) -> None:
        state = {
            "watch_id": self.watch_id,
            "polls": self.polls,
            "posts": [asdict(post) for post in self._collected.posts.values()],
            "on_topic": self._collected.on_topic,
            "histories_read": sorted(self._collected.histories_read),
            "flagged_accounts": sorted(self._flagged_accounts),
            "platforms_read_before": sorted(self._platforms_read_before),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)

    def _load(self, path: Path) -> None:
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("watch_id") != self.watch_id:
            raise ValueError(f"{path} belongs to a different watch: {state.get('watch_id')!r}")
        posts = [
            PublicPost(**{**item, "hashtags": tuple(item["hashtags"]), "mentions": tuple(map(tuple, item["mentions"]))})
            for item in state["posts"]
        ]
        self._collected.posts = {post.id: post for post in posts}
        self._collected.on_topic = state["on_topic"]
        self._collected.histories_read = set(state["histories_read"])
        self._flagged_accounts = set(state["flagged_accounts"])
        self._platforms_read_before = set(state["platforms_read_before"])
        self.polls = state["polls"]
