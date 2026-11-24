"""Central configuration and feature switches for YoEmby ce_opt modules.

Designed to work both inside Kodi (reading `ce_*` settings from `xbmcaddon`)
and outside Kodi (unit tests / CLI scripts) with zero hard Kodi dependency.
"""

from __future__ import annotations

import threading
from typing import Any

_LOCK = threading.RLock()

# Default values for all ce_opt behavioral switches and tuning parameters.
# Setting `ce_enabled` to False disables all behavioral optimizations and
# restores upstream defaults seamlessly.
DEFAULTS: dict[str, Any] = {
    # Master kill switch for behavioral optimizations
    "ce_enabled": True,
    # Batch 1: Stability & safety guards
    "ce_safe_workers": True,
    "ce_fix_subtitle_select": True,
    # Batch 2: Sync acceleration, debounce & SQLite optimization
    "ce_sync_debounce": True,
    "ce_sync_debounce_sec": 4.0,
    "ce_sync_fingerprint": True,
    "ce_widget_debounce": True,
    "ce_widget_debounce_sec": 20.0,
    "ce_db_indexes": True,
    "ce_db_pragmas": True,
    "ce_db_cache_kb": 16384,  # 16 MB SQLite page cache (passed as negative KiB)
    "ce_pause_sync_during_playback": True,
    "ce_lazy_httpcache": True,
    # Batch 3: CoreELEC avdvplus badges, STRM self-healing & multiversion policy
    "ce_avdvplus_badges": True,
    "ce_strm_heal": True,
    "ce_strm_path_fix": True,
    "ce_strm_timeout": 15,
    "ce_multiversion_policy": "prefer_local",  # upstream | prefer_local | prefer_resolution
    # Batch 4: Artwork 307 optimization, WebP & optional chapter bookmark pruning
    "ce_artwork_307_opt": True,
    "ce_artwork_poster_width": 800,
    "ce_artwork_backdrop_width": 1920,
    "ce_artwork_quality": 85,
    "ce_artwork_webp": True,
    "ce_skip_chapter_bookmarks": False,
}

_STATE: dict[str, Any] = dict(DEFAULTS)


def _coerce(default: Any, raw: str) -> Any:
    if raw is None or raw == "":
        return default
    if isinstance(default, bool):
        low = str(raw).strip().lower()
        if low in ("true", "1", "yes", "on"):
            return True
        if low in ("false", "0", "no", "off"):
            return False
        return default
    if isinstance(default, int):
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return default
    if isinstance(default, float):
        try:
            return float(raw)
        except (TypeError, ValueError):
            return default
    return str(raw).strip()


def reload(addon=None) -> dict[str, Any]:
    """Reload `ce_*` settings from a Kodi xbmcaddon.Addon object (or defaults)."""
    if addon is None:
        try:
            import xbmcaddon  # type: ignore

            addon = xbmcaddon.Addon("plugin.service.emby-next-gen")
        except Exception:
            addon = None

    next_state = dict(DEFAULTS)
    if addon is not None:
        for key, default in DEFAULTS.items():
            try:
                raw = addon.getSetting(key)
            except Exception:
                raw = ""
            if raw not in (None, ""):
                next_state[key] = _coerce(default, raw)

    # Keep numeric parameters in safe bounds
    next_state["ce_sync_debounce_sec"] = max(0.5, min(60.0, float(next_state["ce_sync_debounce_sec"])))
    next_state["ce_widget_debounce_sec"] = max(1.0, min(300.0, float(next_state["ce_widget_debounce_sec"])))
    next_state["ce_db_cache_kb"] = max(2048, min(131072, int(next_state["ce_db_cache_kb"])))
    next_state["ce_strm_timeout"] = max(3, min(120, int(next_state["ce_strm_timeout"])))
    next_state["ce_artwork_poster_width"] = max(0, min(3840, int(next_state["ce_artwork_poster_width"])))
    next_state["ce_artwork_backdrop_width"] = max(0, min(3840, int(next_state["ce_artwork_backdrop_width"])))
    next_state["ce_artwork_quality"] = max(50, min(100, int(next_state["ce_artwork_quality"])))
    if next_state["ce_multiversion_policy"] not in ("upstream", "prefer_local", "prefer_resolution"):
        next_state["ce_multiversion_policy"] = DEFAULTS["ce_multiversion_policy"]

    with _LOCK:
        _STATE.clear()
        _STATE.update(next_state)
        return dict(_STATE)


def get(key: str, default: Any = None) -> Any:
    """Get a ce_opt setting value."""
    with _LOCK:
        if key in _STATE:
            return _STATE[key]
        return DEFAULTS.get(key, default)


def is_enabled(flag: str) -> bool:
    """Return True iff master `ce_enabled` AND the given boolean flag are True."""
    with _LOCK:
        if not _STATE.get("ce_enabled", True):
            return False
        return bool(_STATE.get(flag, False))


def set_override(**kwargs: Any) -> None:
    """Override settings in-memory (primarily for unit tests)."""
    with _LOCK:
        for key, value in kwargs.items():
            if key in DEFAULTS:
                _STATE[key] = value


def reset_defaults() -> None:
    """Reset in-memory state back to DEFAULTS."""
    with _LOCK:
        _STATE.clear()
        _STATE.update(DEFAULTS)


def snapshot() -> dict[str, Any]:
    """Return a shallow copy of current configuration."""
    with _LOCK:
        return dict(_STATE)
