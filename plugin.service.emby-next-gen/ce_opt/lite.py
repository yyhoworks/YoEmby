"""CoreELEC pure-cinema Lite Mode pruning and lazy resource loading.

Eliminates unnecessary background threads, startup binary preloading, wasted
theme/trailer HTTP sync calls, auto-rollback flash duplication, and noisy
context menu items while keeping every feature seamlessly reversible via
`ce_lite_mode` (or master switch `ce_enabled`).
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from . import config

_BLACK_LOCK = threading.Lock()
_BLACK_CACHE: dict[str, bytes] = {}

_BLACK_RESOURCE_PREFIX = "special://home/addons/plugin.service.emby-next-gen/resources/"

# Exact extension -> (resource_filename, content_type) mapping matching upstream webservice.py
_BLACK_EXT_RULES: tuple[tuple[tuple[str, ...], str, str], ...] = (
    ((".mp4", ".m4v"), "black.mp4", "video/mp4"),
    ((".mkv",), "black.mkv", "video/x-matroska"),
    ((".avi",), "black.avi", "video/x-msvideo"),
    ((".ts", ".m2ts", ".mts"), "black.ts", "video/mp2t"),
    ((".mpg", ".mpeg", ".mpe"), "black.mpeg", "video/mpeg"),
    ((".webm",), "black.webm", "video/webm"),
    ((".mov",), "black.mov", "video/quicktime"),
    ((".wmv",), "black.wmv", "video/x-ms-wmv"),
    ((".ogv",), "black.ogv", "video/ogg"),
    ((".3gp",), "black.3gp", "video/3gpp"),
    ((".flv",), "black.flv", "video/x-flv"),
    ((".mxf",), "black.mxf", "application/mxf"),
    ((".vob",), "black.vob", "video/dvd"),
    ((".asf",), "black.asf", "video/x-ms-asf"),
)

# Noisy / unsafe / unused context menu Window(10000) properties suppressed in pure-cinema Lite Mode
LITE_SUPPRESSED_CONTEXT_PROPS: frozenset[str] = frozenset(
    {
        "EmbyRemote",
        "EmbyDownload",
        "EmbyRecording",
        "EmbyPlayRandom",
        "EmbySimilar",
        "EmbySettings",
        "EmbyDelete",
    }
)


def is_lite_mode() -> bool:
    """Return True when CoreELEC pure-cinema Lite Mode is active."""
    return config.is_enabled("ce_lite_mode")


def should_start_themes_thread(audio_enabled: bool, video_enabled: bool) -> bool:
    """Only start the background theme monitor thread when needed."""
    if not is_lite_mode():
        return True
    return bool(audio_enabled or video_enabled)


def should_create_rollback() -> bool:
    """Skip duplicating the addon directory into rollback/ on every version bump in Lite Mode."""
    return not is_lite_mode()


def should_skip_theme_sync(audio_enabled: bool, video_enabled: bool) -> bool:
    """Skip per-movie/per-series Emby theme HTTP lookups when theme playback is disabled."""
    if not is_lite_mode():
        return False
    return not bool(audio_enabled or video_enabled)


def should_skip_trailer_sync(cinema_movies: bool, cinema_episodes: bool) -> bool:
    """Skip local trailer HTTP lookups and global trailer folder sync when Cinema Mode is off."""
    if not is_lite_mode():
        return False
    return not bool(cinema_movies or cinema_episodes)


def should_enable_context_prop(prop_name: str, upstream_value: bool) -> bool:
    """Filter Window(10000) context menu properties in pure-cinema Lite Mode."""
    if is_lite_mode() and prop_name in LITE_SUPPRESSED_CONTEXT_PROPS:
        return False
    return bool(upstream_value)


def apply_context_window_properties(window_obj: Any, props_map: dict[str, bool]) -> None:
    """Apply filtered context menu flags to Kodi Window(10000)."""
    for prop_name, upstream_value in props_map.items():
        window_obj.setProperty(prop_name, str(should_enable_context_prop(prop_name, upstream_value)))


def _resolve_black_spec(payload: str) -> tuple[str, str]:
    low = (payload or "").lower()
    for exts, fname, mime in _BLACK_EXT_RULES:
        if any(low.endswith(ext) for ext in exts):
            return fname, mime
    return "black.mp4", "video/mp4"


def get_black_media_response(payload: str, read_binary_fn: Callable[[str], bytes]) -> bytes:
    """Lazily load and cache the HTTP 200 dummy black video response for the given payload extension."""
    fname, mime = _resolve_black_spec(payload)
    cached = _BLACK_CACHE.get(fname)
    if cached is not None:
        return cached

    with _BLACK_LOCK:
        cached = _BLACK_CACHE.get(fname)
        if cached is not None:
            return cached
        raw = read_binary_fn(f"{_BLACK_RESOURCE_PREFIX}{fname}") or b""
        header = (
            "HTTP/1.1 200 OK\r\n"
            "Server: Emby-Next-Gen\r\n"
            "Connection: close\r\n"
            f"Content-Length: {len(raw)}\r\n"
            f"Content-Type: {mime}\r\n"
            "Accept-Ranges: none\r\n\r\n"
        ).encode()
        resp = header + raw
        _BLACK_CACHE[fname] = resp
        return resp


def clear_black_cache() -> None:
    """Clear lazy black media cache (for tests)."""
    with _BLACK_LOCK:
        _BLACK_CACHE.clear()


def get_black_cache_keys() -> tuple[str, ...]:
    """Return currently loaded black.* filenames (for tests/diagnostics)."""
    with _BLACK_LOCK:
        return tuple(sorted(_BLACK_CACHE.keys()))
