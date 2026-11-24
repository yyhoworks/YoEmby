"""Artwork 307 redirect optimization and WebP dimension parser.

1. Appends `tag={ImageTag}` and bounded `maxWidth`/`quality` query parameters on
   live HTTP 307 redirects so Kodi caches appropriately sized images instead of
   raw multi-MB 4K originals (preventing Thumbnails/ bloat on S905X4 eMMC).
2. Adds pure-stdlib WebP header dimension parsing (VP8, VP8L, VP8X) for
   `helper/artworkcache.py` so WebP posters from Emby 4.8+ don't fail metadata checks.
"""

from __future__ import annotations

import struct
from urllib.parse import urlencode

from . import config

_BACKDROP_TYPES = frozenset(("Backdrop", "Banner"))
_CHAPTER_TYPES = frozenset(("Chapter",))


def build_artwork_redirect_url(
    server_url: str,
    access_token: str,
    emby_id: str,
    image_type: str,
    image_index: str,
    image_tag: str,
    enable_cover_art: bool,
) -> str:
    """Build Emby artwork target URL for 307 redirect in `hooks/webservice.py`."""
    base = f"{server_url}/emby/Items/{emby_id}/Images/{image_type}/{image_index}"
    enhancers = "True" if enable_cover_art else "False"

    if not config.is_enabled("ce_artwork_307_opt"):
        return f"{base}?&api_key={access_token}&EnableImageEnhancers={enhancers}"

    params: list[tuple[str, str]] = [
        ("api_key", str(access_token)),
        ("EnableImageEnhancers", enhancers),
    ]

    tag_clean = str(image_tag or "").strip()
    if tag_clean and tag_clean.lower() not in ("0", "none", "noimage"):
        params.append(("tag", tag_clean))

    if image_type in _BACKDROP_TYPES:
        max_w = int(config.get("ce_artwork_backdrop_width", 1920))
    elif image_type in _CHAPTER_TYPES:
        max_w = 480
    else:
        max_w = int(config.get("ce_artwork_poster_width", 800))

    if max_w > 0:
        params.append(("maxWidth", str(max_w)))

    quality = int(config.get("ce_artwork_quality", 85))
    if 50 <= quality < 100:
        params.append(("quality", str(quality)))

    return f"{base}?{urlencode(params)}"


def parse_webp_dimensions(data: bytes) -> tuple[int, int]:
    """Parse (width, height) from RIFF WEBP binary data (VP8, VP8L, VP8X).

    Returns `(0, 0)` if `data` is not a valid WebP image or WebP support is disabled.
    """
    if not config.is_enabled("ce_artwork_webp"):
        return 0, 0
    if not data or len(data) < 30:
        return 0, 0
    if data[0:4] != b"RIFF" or data[8:12] != b"WEBP":
        return 0, 0

    chunk = data[12:16]
    try:
        if chunk == b"VP8X" and len(data) >= 30:
            # Canvas width-1 (24-bit LE at bytes 24..27), height-1 (24-bit LE at bytes 27..30)
            w = 1 + (data[24] | (data[25] << 8) | (data[26] << 16))
            h = 1 + (data[27] | (data[28] << 8) | (data[29] << 16))
            return w, h

        if chunk == b"VP8 " and len(data) >= 30:
            # Lossy VP8 bitstream: keyframe start code 0x9d 0x01 0x2a at offset 23..26
            if data[23:26] == b"\x9d\x01\x2a":
                raw_w, raw_h = struct.unpack("<HH", data[26:30])
                return raw_w & 0x3FFF, raw_h & 0x3FFF

        if chunk == b"VP8L" and len(data) >= 25:
            # Lossless VP8L: signature byte 0x2f at offset 20, followed by 14-bit w-1 & 14-bit h-1
            if data[20] == 0x2F:
                bits = struct.unpack("<I", data[21:25])[0]
                w = (bits & 0x3FFF) + 1
                h = ((bits >> 14) & 0x3FFF) + 1
                return w, h
    except Exception:
        return 0, 0

    return 0, 0
