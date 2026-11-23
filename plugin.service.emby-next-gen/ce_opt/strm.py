"""Fast-path routing decisions for HTTP STRM sources (e.g. YoLink 302 gateways).

Keeps Kodi's stored ``http://127.0.0.1:57342/http/...`` URL contract intact
for YoPlayer ``embypath.py`` while eliminating blocking remote HEAD probes
(which can wrongly trigger HLS transcoding on 302/timeout) and avoiding an
extra Emby proxy hop for LAN HTTP STRM gateways.
"""

import ipaddress
from urllib.parse import urlsplit

from ce_opt import config


def is_http_url(url):
    """Return True if url is an http:// or https:// URL."""
    if not isinstance(url, str):
        return False
    lower = url.strip().lower()
    return lower.startswith("http://") or lower.startswith("https://")


def is_lan_http_url(url):
    """Return True if url is an HTTP(S) URL targeting a LAN/loopback host."""
    if not is_http_url(url):
        return False

    try:
        parsed = urlsplit(url.strip())
    except Exception:
        return False

    host = (parsed.hostname or "").strip().lower()
    if not host:
        return False

    if host == "localhost" or host.endswith(".local") or host.endswith(".lan"):
        return True

    try:
        ip_obj = ipaddress.ip_address(host)
        return bool(ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local)
    except ValueError:
        return False


def should_skip_remote_head(meta_data, media_source, followhttp=False):
    """Decide whether to skip blocking HEAD /videos/{Id}/stream verification."""
    del followhttp  # Reserved for future policy expansion
    if not (config.is_enabled("STRM_FAST_PATH") and config.is_enabled("STRM_SKIP_REMOTE_HEAD")):
        return False

    if not meta_data or not meta_data.get("isHttp"):
        return False

    source_path = (media_source or {}).get("Path", "")
    return is_http_url(source_path)


def should_direct_redirect_http(meta_data, media_source, data="", followhttp=False):
    """Decide whether send_redirect should 307 directly to the HTTP STRM URL.

    Never bypasses Emby when HLS transcoding (``main.m3u8``) is requested.
    """
    if not meta_data or not meta_data.get("isHttp"):
        return False

    if data and "main.m3u8" in data:
        return False

    source_path = (media_source or {}).get("Path", "")
    if not is_http_url(source_path):
        return False

    if followhttp:
        return True

    if config.is_enabled("STRM_FAST_PATH") and config.is_enabled("STRM_LAN_DIRECT_REDIRECT"):
        return is_lan_http_url(source_path)

    return False
