"""STRM / HTTP 302 path normalization and smart multiversion selection.

Handles:
1. Fixing upstream double-pipe `|redirect-limit=...` corruption on HTTP/STRM paths.
2. Safe RFC-3986 percent-encoding of HTTP 307 Location URLs (Chinese/spaces in cloud URLs).
3. Smart multiversion selection for mixed LAN SMB + cloud STRM libraries.
"""

from __future__ import annotations

from typing import Any, Sequence
from urllib.parse import quote, urlsplit, urlunsplit

from . import config, safety


def is_local_path(path: str) -> bool:
    """Return True if path points to LAN/local storage rather than HTTP/STRM/plugin."""
    if not path:
        return False
    low = path.strip().lower()
    if low.startswith(("http://", "https://", "plugin://", "dav://", "davs://")):
        return False
    if low.startswith(("\\\\", "smb://", "nfs://", "afp://", "/")):
        return True
    return False


def _append_kodi_pipe_options(url: str, extra_params: str) -> str:
    """Append Kodi curl pipe options cleanly without duplicating `|` or existing keys."""
    if not url:
        return url
    if "|" not in url:
        return f"{url}|{extra_params}"

    base, existing = url.split("|", 1)
    pairs: list[tuple[str, str]] = []
    seen: dict[str, int] = {}
    for token in (existing + "&" + extra_params).split("&"):
        if not token:
            continue
        k, sep, v = token.partition("=")
        kl = k.lower()
        if kl in seen:
            pairs[seen[kl]] = (k, v if sep else "")
        else:
            seen[kl] = len(pairs)
            pairs.append((k, v if sep else ""))
    merged = "&".join(f"{k}={v}" if v != "" else k for k, v in pairs)
    return f"{base}|{merged}"


def finalize_http_paths(
    item: dict[str, Any],
    is_http_by_emby: bool,
    follow_http: bool,
    follow_http_timeout: int,
) -> bool:
    """Normalize local proxy & STRM HTTP curl pipe options on `Item`.

    Fixes upstream bug where `core/common.py:378-392` appended `|redirect-limit=...`
    twice when `KodiPath` started with `http://127.0.0.1:57342/` and `followhttp`
    was enabled. Returns True when applied, False to let upstream code run.
    """
    if not config.is_enabled("ce_strm_path_fix"):
        return False

    kodi_path = item.get("KodiPath", "")
    is_proxy = kodi_path.startswith("http://127.0.0.1:57342/") or kodi_path.startswith("dav://127.0.0.1:57342/")
    is_audio = item.get("Type") == "Audio"

    if is_http_by_emby and follow_http:
        timeout = max(int(follow_http_timeout or 0), int(config.get("ce_strm_timeout", 15)))
        kodi_path = kodi_path.replace("/emby_addon_mode/", "http://127.0.0.1:57342/").replace(
            "dav://127.0.0.1:57342/", "http://127.0.0.1:57342/"
        )
        item["KodiPath"] = kodi_path
        item["KodiFullPath"] = f"{kodi_path}{item.get('KodiFilename', '')}"
        opts = f"redirect-limit=1000&failonerror=false&connection-timeout={timeout}"
        item["KodiFullPath"] = _append_kodi_pipe_options(item["KodiFullPath"], opts)
        item["KodiPath"] = _append_kodi_pipe_options(item["KodiPath"], opts)
        if "KodiPathParent" in item:
            item["KodiPathParent"] = _append_kodi_pipe_options(item["KodiPathParent"], opts)
        return True

    if is_proxy and not is_audio:
        opts = "redirect-limit=1000&failonerror=false"
        if is_http_by_emby:
            timeout = int(config.get("ce_strm_timeout", 15))
            opts += f"&connection-timeout={timeout}"
        item["KodiFullPath"] = _append_kodi_pipe_options(item.get("KodiFullPath", ""), opts)
        item["KodiPath"] = _append_kodi_pipe_options(kodi_path, opts)
        if "KodiPathParent" in item:
            item["KodiPathParent"] = _append_kodi_pipe_options(item["KodiPathParent"], opts)
        return True

    return True


def prepare_redirect_location(raw_url: str) -> str:
    """Safely percent-encode spaces/non-ASCII chars in HTTP 307 Location headers
    while preserving already-encoded `%XX` sequences and URL structure.
    """
    if not raw_url or not config.is_enabled("ce_strm_path_fix"):
        return raw_url
    url = raw_url.strip()
    try:
        parts = urlsplit(url)
        if not parts.scheme or not parts.netloc:
            return url
        safe_path = quote(parts.path, safe="/:@!$&'()*+,;=-._~%")
        safe_query = quote(parts.query, safe="=&/:@!$'()*+,;?-._~%")
        safe_frag = quote(parts.fragment, safe="/:?@-._~%")
        return urlunsplit((parts.scheme, parts.netloc, safe_path, safe_query, safe_frag))
    except Exception:
        return url


def _score_source(path: str, name: str, width: int, bitrate: int, size: int, policy: str) -> tuple[int, int, int, int]:
    eff_width = width if width > 0 else safety.infer_width_from_text(f"{name} {path}")
    local_flag = 1 if is_local_path(path) else 0
    if policy == "prefer_local":
        return (local_flag, eff_width, bitrate, size)
    # prefer_resolution
    return (eff_width, local_flag, bitrate, size)


def select_best_mediasource_webservice(media_sources: Sequence[Any]) -> int:
    """Select best MediaSource index for webservice MetaData respecting `ce_multiversion_policy`."""
    policy = str(config.get("ce_multiversion_policy", "prefer_local")) if config.get("ce_enabled", True) else "upstream"
    if policy == "upstream" or not media_sources:
        return safety.safe_highest_resolution_index_webservice(media_sources)

    best_idx = 0
    best_score = (-1, -1, -1, -1)
    for idx, source in enumerate(media_sources):
        info = source[0] if len(source) > 0 and isinstance(source[0], dict) else {}
        vstreams = source[1] if len(source) > 1 and source[1] else []
        v0 = vstreams[0] if vstreams and isinstance(vstreams[0], dict) else {}
        score = _score_source(
            path=str(info.get("Path") or ""),
            name=str(info.get("Name") or ""),
            width=safety.safe_int(v0.get("Width"), 0),
            bitrate=safety.safe_int(v0.get("BitRate"), 0),
            size=safety.safe_int(info.get("Size"), 0),
            policy=policy,
        )
        if score > best_score:
            best_score = score
            best_idx = idx
    return best_idx


def select_best_mediasource_native(media_sources: Sequence[Any], video_streams: Sequence[Any]) -> int:
    """Select best MediaSource index for native direct-path playback."""
    policy = str(config.get("ce_multiversion_policy", "prefer_local")) if config.get("ce_enabled", True) else "upstream"
    if policy == "upstream" or not media_sources:
        return safety.safe_highest_resolution_index_native(media_sources, video_streams)

    best_idx = 0
    best_score = (-1, -1, -1, -1)
    for idx, source in enumerate(media_sources):
        path = str(source[2] or "") if len(source) > 2 else ""
        name = str(source[3] or "") if len(source) > 3 else ""
        size = safety.safe_int(source[4], 0) if len(source) > 4 else 0
        width = 0
        bitrate = 0
        if video_streams and idx < len(video_streams):
            width = safety.safe_int(video_streams[idx][4], 0)
            bitrate = safety.safe_int(video_streams[idx][3], 0)
        score = _score_source(path, name, width, bitrate, size, policy)
        if score > best_score:
            best_score = score
            best_idx = idx
    return best_idx


def should_prefer_movie_version(
    cand_path: str,
    cand_width: int,
    cur_path: str,
    cur_width: int,
) -> bool:
    """Decide whether candidate movie version should replace current default in `add_multiversion`.

    Fixes upstream bug where `cur_width == 0` (unprobed STRM) prevented upgrading
    to a probed higher-resolution or local SMB version.
    """
    policy = str(config.get("ce_multiversion_policy", "prefer_local")) if config.get("ce_enabled", True) else "upstream"
    cand_w = safety.safe_int(cand_width, 0) or safety.infer_width_from_text(cand_path)
    cur_w = safety.safe_int(cur_width, 0) or safety.infer_width_from_text(cur_path)

    if policy == "upstream":
        return cand_w > cur_w
    if policy == "prefer_local":
        cand_local = 1 if is_local_path(cand_path) else 0
        cur_local = 1 if is_local_path(cur_path) else 0
        return (cand_local, cand_w) > (cur_local, cur_w)
    # prefer_resolution
    cand_local = 1 if is_local_path(cand_path) else 0
    cur_local = 1 if is_local_path(cur_path) else 0
    return (cand_w, cand_local) > (cur_w, cur_local)


def format_version_label(name: str, size_text: str, path: str) -> str:
    """Format a clear multiversion selection label indicating local SMB vs cloud STRM."""
    if not config.get("ce_enabled", True):
        return f"{name} - {size_text} - {path}"
    tag = "[SMB]" if is_local_path(path) else "[STRM]"
    return f"{tag} {name} - {size_text} - {path}"
