"""The smallest interface for running monitors from the API, with limits.

Nothing runs in the background: a watch polls only when ``poll_watch`` is called.
Starting one requires the user's opt-in, because polling sends the watched terms to
outside services. Watches live in this process's memory and end by themselves.
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.network.monitor import Monitor
from backend.network.sources import Fetch, Source, live_fetch

MAX_WATCHES = 5
MIN_POLL_INTERVAL_SECONDS = 60
WATCH_LIFETIME_SECONDS = 24 * 60 * 60


class WatchError(Exception):
    """A watch request was refused. The message is safe to show to users."""


@dataclass
class _Watch:
    monitor: Monitor
    started_at: float
    last_poll_at: float | None = None


_watches: dict[str, _Watch] = {}
_lock = threading.Lock()


def _remove_expired(now: float) -> None:
    for watch_id in [key for key, watch in _watches.items() if now - watch.started_at > WATCH_LIFETIME_SECONDS]:
        del _watches[watch_id]


def start_watch(
    watch_id: str,
    *,
    opted_in: bool,
    text: str | None = None,
    urls: tuple[str, ...] = (),
    hashtags: tuple[str, ...] = (),
    sources: list[Source] | None = None,
    fetch: Fetch = live_fetch,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Register a watch. It sends nothing until the first poll."""
    if opted_in is not True:
        raise WatchError("Monitoring sends the watched terms to outside services, so it needs the user's opt-in.")
    now = clock()
    with _lock:
        _remove_expired(now)
        if watch_id in _watches:
            raise WatchError("A watch with this id is already running.")
        if len(_watches) >= MAX_WATCHES:
            raise WatchError(f"At most {MAX_WATCHES} watches can run at once.")
        try:
            monitor = Monitor(watch_id, text=text, urls=urls, hashtags=hashtags, sources=sources, fetch=fetch)
        except ValueError as error:
            raise WatchError(str(error)) from error
        _watches[watch_id] = _Watch(monitor, now)
    return {
        "watch_id": watch_id,
        "min_poll_interval_seconds": MIN_POLL_INTERVAL_SECONDS,
        "expires_in_seconds": WATCH_LIFETIME_SECONDS,
    }


def poll_watch(watch_id: str, clock: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    """Poll once and return the snapshot. Too-soon polls are refused, so no service is hammered."""
    now = clock()
    with _lock:
        _remove_expired(now)
        watch = _watches.get(watch_id)
        if watch is None:
            raise WatchError("No such watch. It may have expired or been stopped.")
        if watch.last_poll_at is not None:
            wait = MIN_POLL_INTERVAL_SECONDS - (now - watch.last_poll_at)
            if wait > 0:
                raise WatchError(f"Polled too soon. Try again in {int(wait) + 1} seconds.")
        watch.last_poll_at = now
    return watch.monitor.poll()


def stop_watch(watch_id: str) -> bool:
    """Stop a watch. Returns False if it wasn't running. Its last results stay readable."""
    with _lock:
        return _watches.pop(watch_id, None) is not None


def list_watches(clock: Callable[[], float] = time.monotonic) -> list[str]:
    with _lock:
        _remove_expired(clock())
        return sorted(_watches)
