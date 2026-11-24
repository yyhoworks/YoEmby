"""Pure safety helpers for upstream P0/P1 bugfixes.

Keeps defensive logic concise, unit-testable, and out of upstream hot paths.
"""

from __future__ import annotations

import errno
import re
from typing import Any, Sequence

from . import config

_RES_RE = re.compile(r"(?:^|[^0-9])(2160|1440|1080|720|576|480)[pi](?:[^0-9]|$)|\b(4k|uhd|8k)\b", re.IGNORECASE)
_RES_WIDTH = {
    "8k": 7680,
    "4k": 3840,
    "uhd": 3840,
    "2160": 3840,
    "1440": 2560,
    "1080": 1920,
    "720": 1280,
    "576": 1024,
    "480": 854,
}


def infer_width_from_text(text: str) -> int:
    """Infer approximate video width from filename/title when stream metadata is absent."""
    if not text:
        return 0
    m = _RES_RE.search(text)
    if not m:
        return 0
    token = (m.group(1) or m.group(2) or "").lower()
    return _RES_WIDTH.get(token, 0)


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_highest_resolution_index_webservice(media_sources: Sequence[Any]) -> int:
    """Safely select the MediaSource with highest video width in webservice MetaData.

    Upstream crashed with IndexError when a STRM MediaSource had empty VideoStreams
    (`MediaSource[1] == []`) or non-integer Width.
    """
    if not media_sources:
        return 0

    best_idx = 0
    best_width = -1
    for idx, source in enumerate(media_sources):
        width = 0
        try:
            video_streams = source[1] if len(source) > 1 else None
            if video_streams and isinstance(video_streams[0], dict):
                width = safe_int(video_streams[0].get("Width"), 0)
        except Exception:
            width = 0
        if width <= 0:
            try:
                info = source[0] if len(source) > 0 and isinstance(source[0], dict) else {}
                width = infer_width_from_text(f"{info.get('Name', '')} {info.get('Path', '')}")
            except Exception:
                width = 0
        if width > best_width:
            best_width = width
            best_idx = idx
    return best_idx


def safe_highest_resolution_index_native(
    media_sources: Sequence[Any],
    video_streams: Sequence[Any],
) -> int:
    """Safely select highest resolution MediaSource in native direct-path playback.

    Upstream indexed `VideoStreams[0][4]` in every loop iteration (ignoring per-source
    differences and crashing with IndexError/TypeError when VideoStreams was empty or
    Width was None).
    """
    if not media_sources:
        return 0

    best_idx = 0
    best_width = -1
    for idx, source in enumerate(media_sources):
        width = 0
        # When emby.db has one VideoStreams row per MediaSource in order, use matching row.
        if video_streams and idx < len(video_streams):
            try:
                width = safe_int(video_streams[idx][4], 0)
            except Exception:
                width = 0
        if width <= 0:
            # Fallback to Name (col 3) and Path (col 2) resolution markers.
            name = source[3] if len(source) > 3 and source[3] else ""
            path = source[2] if len(source) > 2 and source[2] else ""
            width = infer_width_from_text(f"{name} {path}")
        if width > best_width:
            best_width = width
            best_idx = idx
    return best_idx


def match_external_subtitle(default_lang: str, subtitle: dict[str, Any]) -> bool:
    """Safely check whether an external subtitle matches Kodi's default subtitle language.

    Fixes upstream bug where empty `default_lang == ""` matched every subtitle because
    `"" in str` is always True in Python.
    """
    lang = (default_lang or "").strip().lower()
    if not lang:
        return False
    if lang == "forced_only":
        return bool(subtitle.get("Forced", False))
    display = str(subtitle.get("DisplayTitle") or "").lower()
    sub_lang = str(subtitle.get("language") or "").lower()
    return (lang in display) or (lang in sub_lang)


def should_disable_subtitles_on_no_external_match(file_settings: Any) -> bool:
    """Determine whether SubTitlesAdd should disable subtitles when no external sub matched.

    When `ce_fix_subtitle_select` is enabled, we avoid turning off embedded subtitles
    unless `file_settings` explicitly recorded subtitles disabled for this file.
    """
    if not config.is_enabled("ce_fix_subtitle_select"):
        return True
    if file_settings:
        try:
            return not bool(file_settings[9])
        except Exception:
            return False
    return False


def is_expected_socket_close_error(error: BaseException, running: bool, shutting_down: bool) -> bool:
    """Return True if an OSError (such as EBADF) is expected during socket teardown."""
    if shutting_down or not running:
        return True
    err_no = getattr(error, "errno", None)
    if err_no in (errno.EBADF, errno.ECONNRESET, errno.ESHUTDOWN):
        return True
    msg = str(error).lower()
    return "bad file descriptor" in msg or "errno 9" in msg


def decode_http_request(raw: bytes) -> tuple[str, list[str]]:
    """Decode incoming local HTTP proxy bytes safely and split request line tokens."""
    if not raw:
        return "", []
    text = raw.decode("utf-8", errors="replace")
    first_line = text.split("\r\n", 1)[0].split("\n", 1)[0].strip()
    if not first_line:
        return text, []
    return text, first_line.split(" ")
