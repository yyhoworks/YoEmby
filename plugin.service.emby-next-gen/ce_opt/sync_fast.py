"""Sync acceleration: WebSocket LibraryChanged coalescing, item fingerprinting,
and widget refresh debouncing.

All mechanisms are strictly switch-controlled via `ce_opt.config` and avoid
permanent high-frequency polling threads (using one-shot Timers only when work
is actually queued).
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from typing import Any, Callable

from . import config

# Bounded LRU cache: (server_id, item_id) -> sha1 hex digest
_MAX_FINGERPRINTS = 25000
_FP_LOCK = threading.Lock()
_FINGERPRINTS: OrderedDict[tuple[str, str], str] = OrderedDict()

# Stats counters (used by maintenance diagnostics & tests)
_STATS_LOCK = threading.Lock()
_STATS = {
    "fingerprint_skipped": 0,
    "fingerprint_written": 0,
    "ws_events_received": 0,
    "ws_batches_flushed": 0,
    "widget_refreshes_coalesced": 0,
    "widget_refreshes_executed": 0,
}

_FINGERPRINT_TYPES = frozenset(("Episode", "Movie", "Series", "Season", "Video"))


def _inc_stat(key: str, delta: int = 1) -> None:
    with _STATS_LOCK:
        _STATS[key] = _STATS.get(key, 0) + delta


def get_stats() -> dict[str, int]:
    with _STATS_LOCK:
        return dict(_STATS)


def reset_state() -> None:
    """Clear caches and counters (used on full resync or unit tests)."""
    with _FP_LOCK:
        _FINGERPRINTS.clear()
    with _STATS_LOCK:
        for k in list(_STATS):
            _STATS[k] = 0


def compute_item_fingerprint(item: dict[str, Any]) -> str:
    """Compute a deterministic SHA-1 digest of all Emby item fields written to Kodi DB.

    Includes both metadata AND UserData playstate fields so any real change
    invalidates the fingerprint, while identical repeated season pushes from
    Emby's LibraryChanged event produce the exact same hash.
    """
    media_sources_sig = []
    for ms in item.get("MediaSources") or ():
        if not isinstance(ms, dict):
            continue
        streams_sig = [
            (
                s.get("Type"),
                s.get("Index"),
                s.get("Codec"),
                s.get("Profile"),
                s.get("Width"),
                s.get("Height"),
                s.get("BitRate"),
                s.get("Channels"),
                s.get("Language"),
                s.get("DisplayTitle"),
                s.get("VideoRange"),
                s.get("VideoRangeType"),
                s.get("ExtendedVideoSubType"),
                s.get("IsExternal"),
                s.get("IsDefault"),
                s.get("IsForced"),
            )
            for s in (ms.get("MediaStreams") or ())
            if isinstance(s, dict)
        ]
        chapters_sig = [
            (c.get("StartPositionTicks"), c.get("Name"), c.get("MarkerType"), c.get("ImageTag"))
            for c in (ms.get("Chapters") or ())
            if isinstance(c, dict)
        ]
        media_sources_sig.append(
            (
                ms.get("Id"),
                ms.get("Path"),
                ms.get("Name"),
                ms.get("Size"),
                ms.get("RunTimeTicks"),
                ms.get("Container"),
                streams_sig,
                chapters_sig,
            )
        )

    ud = item.get("UserData") or {}
    userdata_sig = (
        ud.get("Played"),
        ud.get("PlayCount"),
        ud.get("PlaybackPositionTicks"),
        ud.get("IsFavorite"),
        ud.get("LastPlayedDate"),
    )

    people_sig = [
        (p.get("Id"), p.get("Name"), p.get("Type"), p.get("Role"), p.get("PrimaryImageTag"))
        for p in (item.get("People") or ())
        if isinstance(p, dict)
    ]

    chapters_top = [
        (c.get("StartPositionTicks"), c.get("Name"), c.get("MarkerType"), c.get("ImageTag"))
        for c in (item.get("Chapters") or ())
        if isinstance(c, dict)
    ]

    payload = {
        "Id": item.get("Id"),
        "Type": item.get("Type"),
        "LibraryId": item.get("LibraryId"),
        "Etag": item.get("Etag"),
        "DateModified": item.get("DateModified"),
        "Name": item.get("Name"),
        "OriginalTitle": item.get("OriginalTitle"),
        "SortName": item.get("SortName"),
        "Overview": item.get("Overview"),
        "ProductionYear": item.get("ProductionYear"),
        "PremiereDate": item.get("PremiereDate"),
        "DateCreated": item.get("DateCreated"),
        "RunTimeTicks": item.get("RunTimeTicks"),
        "CommunityRating": item.get("CommunityRating"),
        "CriticRating": item.get("CriticRating"),
        "OfficialRating": item.get("OfficialRating"),
        "IndexNumber": item.get("IndexNumber"),
        "ParentIndexNumber": item.get("ParentIndexNumber"),
        "SeriesId": item.get("SeriesId"),
        "SeasonId": item.get("SeasonId"),
        "Path": item.get("Path"),
        "Container": item.get("Container"),
        "PresentationUniqueKey": item.get("PresentationUniqueKey"),
        "ImageTags": item.get("ImageTags"),
        "BackdropImageTags": item.get("BackdropImageTags"),
        "ProviderIds": item.get("ProviderIds"),
        "Genres": item.get("Genres"),
        "GenreItems": item.get("GenreItems"),
        "Studios": item.get("Studios"),
        "TagItems": item.get("TagItems"),
        "SpecialFeatureCount": item.get("SpecialFeatureCount"),
        "People": people_sig,
        "MediaSources": media_sources_sig,
        "Chapters": chapters_top,
        "UserData": userdata_sig,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def check_or_prepare_fingerprint(
    server_id: str,
    item: dict[str, Any],
    incremental_sync: Any,
    sqls: dict[str, Any] | None = None,
) -> tuple[bool, str | None]:
    """Check whether an incremental update item is unchanged BEFORE mutation.

    Returns `(should_skip, pre_mutation_digest)`. Callers MUST compute this
    before `ClassObject.change(item, ...)` because upstream mutates `item`
    in-place, then pass `pre_mutation_digest` to `commit_fingerprint()` once
    the DB write completes.
    """
    if not config.is_enabled("ce_sync_fingerprint"):
        return False, None

    item_type = item.get("Type")
    item_id = item.get("Id")
    if item_type not in _FINGERPRINT_TYPES or not item_id:
        return False, None

    digest = compute_item_fingerprint(item)
    if not incremental_sync:
        # Full sync / repair still records the latest digest, never skips.
        return False, digest

    key = (str(server_id), str(item_id))
    with _FP_LOCK:
        cached = _FINGERPRINTS.get(key)
        if cached is not None and cached == digest:
            if sqls and "emby" in sqls and sqls["emby"] is not None:
                try:
                    if not sqls["emby"].get_item_by_id(item_id, item_type):
                        _FINGERPRINTS.pop(key, None)
                        return False, digest
                except Exception:
                    return False, digest
            _FINGERPRINTS.move_to_end(key)
            _inc_stat("fingerprint_skipped")
            return True, digest

    return False, digest


def commit_fingerprint(server_id: str, item_id: Any, digest: str | None) -> None:
    """Persist the pre-mutation digest after a successful DB write."""
    if not digest or not item_id or not config.is_enabled("ce_sync_fingerprint"):
        return
    key = (str(server_id), str(item_id))
    with _FP_LOCK:
        _FINGERPRINTS[key] = digest
        _FINGERPRINTS.move_to_end(key)
        while len(_FINGERPRINTS) > _MAX_FINGERPRINTS:
            _FINGERPRINTS.popitem(last=False)
    _inc_stat("fingerprint_written")


def should_skip_unchanged(
    server_id: str,
    item: dict[str, Any],
    incremental_sync: Any,
    sqls: dict[str, Any] | None = None,
) -> bool:
    skip, _ = check_or_prepare_fingerprint(server_id, item, incremental_sync, sqls)
    return skip


def record_item_fingerprint(server_id: str, item: dict[str, Any]) -> None:
    """Store the fingerprint of an item after it has been written to DB."""
    if not config.is_enabled("ce_sync_fingerprint"):
        return
    item_type = item.get("Type")
    item_id = item.get("Id")
    if item_type not in _FINGERPRINT_TYPES or not item_id:
        return
    commit_fingerprint(server_id, item_id, compute_item_fingerprint(item))


def invalidate_item_fingerprint(server_id: str, item_ids: Any) -> None:
    """Remove cached fingerprints when items are deleted or force-refreshed."""
    if not item_ids:
        return
    if isinstance(item_ids, (str, int)):
        item_ids = (item_ids,)
    sid = str(server_id)
    with _FP_LOCK:
        for item_id in item_ids:
            _FINGERPRINTS.pop((sid, str(item_id)), None)


def clear_server_fingerprints(server_id: str) -> None:
    """Drop all cached fingerprints for a server (e.g. on full repair/sync)."""
    sid = str(server_id)
    with _FP_LOCK:
        for k in [key for key in _FINGERPRINTS if key[0] == sid]:
            _FINGERPRINTS.pop(k, None)


class LibraryChangedCoalescer:
    """Debounces and deduplicates bursts of Emby WebSocket LibraryChanged events.

    Emby emits one LibraryChanged per episode during season imports, each listing
    every episode already in the season. Coalescing over a short window collapses
    bursts into a single ordered (remove -> update) dispatch.
    """

    def __init__(self, emit_fn: Callable[[tuple[Any, ...]], None], max_wait_factor: float = 3.0):
        self._emit = emit_fn
        self._max_wait_factor = max_wait_factor
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._first_event_ts: float = 0.0
        self._pending_removes: list[Any] = []
        self._pending_remove_set: set[str] = set()
        self._pending_updates: OrderedDict[str, tuple[Any, str, str]] = OrderedDict()

    def submit(self, removed_ids: list[Any], update_items: list[tuple[Any, str, str]]) -> None:
        _inc_stat("ws_events_received")
        if not config.is_enabled("ce_sync_debounce"):
            self._dispatch_direct(removed_ids, update_items)
            return

        debounce = float(config.get("ce_sync_debounce_sec", 4.0))
        max_wait = debounce * self._max_wait_factor
        now = time.monotonic()

        flush_now = False
        with self._lock:
            if not self._first_event_ts:
                self._first_event_ts = now

            for rid in removed_ids or ():
                rkey = str(rid)
                if rkey not in self._pending_remove_set:
                    self._pending_remove_set.add(rkey)
                    self._pending_removes.append(rid)
                self._pending_updates.pop(rkey, None)

            for item in update_items or ():
                ukey = str(item[0])
                if ukey not in self._pending_remove_set:
                    self._pending_updates[ukey] = item

            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

            if (now - self._first_event_ts) >= max_wait:
                flush_now = True
            else:
                remaining = min(debounce, max(0.05, max_wait - (now - self._first_event_ts)))
                self._timer = threading.Timer(remaining, self.flush)
                self._timer.daemon = True
                self._timer.start()

        if flush_now:
            self.flush()

    def _dispatch_direct(self, removed_ids: list[Any], update_items: list[tuple[Any, str, str]]) -> None:
        batch = []
        if removed_ids:
            batch.append(("remove", list(removed_ids)))
        if update_items:
            batch.append(("update", list(update_items)))
        if batch:
            _inc_stat("ws_batches_flushed")
            self._emit(tuple(batch))

    def flush(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            removes = self._pending_removes
            updates = list(self._pending_updates.values())
            self._pending_removes = []
            self._pending_remove_set.clear()
            self._pending_updates.clear()
            self._first_event_ts = 0.0

        self._dispatch_direct(removes, updates)

    def cancel(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._pending_removes.clear()
            self._pending_remove_set.clear()
            self._pending_updates.clear()
            self._first_event_ts = 0.0


class WidgetRefreshDebouncer:
    """Coalesces repeated `refresh_widgets(isVideo)` calls into a bounded rate."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_run: dict[bool, float] = {True: 0.0, False: 0.0}
        self._timers: dict[bool, threading.Timer | None] = {True: None, False: None}

    def trigger(self, is_video: bool, run_fn: Callable[[bool], None]) -> bool:
        """Run immediately if outside cooldown window, otherwise schedule a single trailing run.

        Returns True if executed synchronously, False if coalesced into a trailing timer.
        """
        if not config.is_enabled("ce_widget_debounce"):
            _inc_stat("widget_refreshes_executed")
            run_fn(is_video)
            return True

        cooldown = float(config.get("ce_widget_debounce_sec", 20.0))
        now = time.monotonic()

        with self._lock:
            elapsed = now - self._last_run[is_video]
            if elapsed >= cooldown and self._timers[is_video] is None:
                self._last_run[is_video] = now
                execute_now = True
            else:
                execute_now = False
                _inc_stat("widget_refreshes_coalesced")
                if self._timers[is_video] is None:
                    delay = max(0.1, cooldown - elapsed)
                    timer = threading.Timer(delay, self._fire, args=(is_video, run_fn))
                    timer.daemon = True
                    self._timers[is_video] = timer
                    timer.start()

        if execute_now:
            _inc_stat("widget_refreshes_executed")
            run_fn(is_video)
        return execute_now

    def _fire(self, is_video: bool, run_fn: Callable[[bool], None]) -> None:
        with self._lock:
            self._timers[is_video] = None
            self._last_run[is_video] = time.monotonic()
        _inc_stat("widget_refreshes_executed")
        try:
            run_fn(is_video)
        except Exception:
            pass

    def cancel_all(self) -> None:
        with self._lock:
            for key in (True, False):
                t = self._timers[key]
                if t is not None:
                    t.cancel()
                    self._timers[key] = None
                self._last_run[key] = 0.0


widget_debouncer = WidgetRefreshDebouncer()
