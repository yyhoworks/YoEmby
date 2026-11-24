"""CoreELEC avdvplus HDR / Dolby Vision Profile / Spatial Audio metadata enrichment.

Maps Emby 4.8+ stream fields (`VideoRangeType`, `ExtendedVideoSubType`, audio
`Profile` & `DisplayTitle`) into CoreELEC `avdvplus` extended `streamdetails`
columns (`strHdrTypeAlt`, `strDvProfile`, `strAudioProfile`) when present.
"""

from __future__ import annotations

import re
import threading
from typing import Any, Sequence

from . import config

_SCHEMA_LOCK = threading.Lock()
_SCHEMA_CACHE: dict[int, bool] = {}

_DOVI_PROFILE_MAP = {
    "doviprofile42": ("4.2", "4.2"),
    "doviprofile50": ("5.0", "5"),
    "doviprofile76": ("7.6", "7"),
    "doviprofile81": ("8.1", "8.1"),
    "doviprofile84": ("8.4", "8.4"),
    "doviprofile92": ("9.2", "9.2"),
    "doviprofile10": ("10.0", "10"),
}

_DOVI_PROFILE_RE = re.compile(r"(?:dovi|dv)[\s._-]*profile[\s._-]*(\d+(?:\.\d+)?)", re.IGNORECASE)


def enrich_video_stream(raw_stream: dict[str, Any], stream_data: dict[str, Any]) -> dict[str, Any]:
    """Enrich upstream `StreamData` dict with Emby 4.8+ HDR10+/DV Profile metadata."""
    if not config.is_enabled("ce_avdvplus_badges"):
        return stream_data

    video_range = str(raw_stream.get("VideoRange") or "").strip().lower()
    range_type = str(raw_stream.get("VideoRangeType") or "").strip().lower()
    ext_type = str(raw_stream.get("ExtendedVideoType") or "").strip().lower()
    ext_sub = str(raw_stream.get("ExtendedVideoSubType") or "").strip().lower()
    title_blob = f"{raw_stream.get('DisplayTitle') or ''} {raw_stream.get('Title') or ''}".lower()

    hdr_type = stream_data.get("hdrtype")
    hdr_alt = ""
    dv_profile = ""
    hdr_detail = stream_data.get("hdrdetail") or ""

    # 1. Detect Dolby Vision & base compatibility layer
    is_dovi = (
        hdr_type == "dolbyvision"
        or "dovi" in range_type
        or "dolby" in video_range
        or ext_type == "dolbyvision"
        or "dolby vision" in title_blob
    )
    if is_dovi:
        hdr_type = "dolbyvision"
        if "hdr10plus" in range_type or "hdr10+" in title_blob:
            hdr_alt = "hdr10plus"
        elif "hdr10" in range_type or "el" in range_type:
            hdr_alt = "hdr10"
        elif "hlg" in range_type:
            hdr_alt = "hlg"

        if ext_sub in _DOVI_PROFILE_MAP:
            dv_profile, detail = _DOVI_PROFILE_MAP[ext_sub]
            if not hdr_detail:
                hdr_detail = detail
        else:
            m = _DOVI_PROFILE_RE.search(f"{ext_sub} {title_blob}")
            if m:
                raw_p = m.group(1)
                dv_profile = raw_p if "." in raw_p else f"{raw_p}.0"
                if not hdr_detail:
                    hdr_detail = raw_p
    else:
        # 2. Detect HDR10+ / HDR10 / HLG (including Emby 4.8+ where VideoRange="HDR")
        is_hdr10plus = (
            range_type == "hdr10plus"
            or ext_type == "hdr10plus"
            or "hdr10+" in video_range
            or "hdr10plus" in video_range
            or "hdr10+" in title_blob
        )
        if is_hdr10plus:
            hdr_type = "hdr10"
            hdr_alt = "hdr10plus"
        elif not hdr_type:
            if range_type == "hlg" or ext_type == "hyperloggamma" or video_range == "hlg":
                hdr_type = "hlg"
            elif range_type == "hdr10" or ext_type == "hdr10" or video_range in ("hdr", "hdr10", "hdr 10"):
                hdr_type = "hdr10"

    stream_data["hdrtype"] = hdr_type
    stream_data["hdrdetail"] = hdr_detail
    stream_data["ce_hdr_alt"] = hdr_alt
    stream_data["ce_dv_profile"] = dv_profile
    return stream_data


def enrich_audio_stream(raw_stream: dict[str, Any], stream_data: dict[str, Any]) -> dict[str, Any]:
    """Enrich upstream audio `StreamData` dict with Dolby Atmos / DTS:X / codec profile."""
    if not config.is_enabled("ce_avdvplus_badges"):
        return stream_data

    codec = str(stream_data.get("codec") or "").lower()
    profile_raw = str(raw_stream.get("Profile") or "").strip()
    display = str(raw_stream.get("DisplayTitle") or "")
    title = str(raw_stream.get("Title") or "")
    blob = f"{profile_raw} {display} {title}".lower()

    audio_profile = ""
    if "atmos" in blob:
        audio_profile = "Dolby Atmos"
    elif "dts:x" in blob or "dts-x" in blob or "dtsx" in blob:
        audio_profile = "DTS:X"
    elif codec == "dtshd_ma" or "dts-hd ma" in blob:
        audio_profile = "DTS-HD MA"
    elif codec == "dtshd_hra" or "dts-hd hra" in blob:
        audio_profile = "DTS-HD HRA"
    elif codec == "truehd":
        audio_profile = "Dolby TrueHD"
    elif codec == "aac":
        pl = profile_raw.lower()
        if pl == "lc" or "aac-lc" in blob:
            audio_profile = "AAC-LC"
        elif "he-aac" in pl or "he-aac" in blob:
            audio_profile = "HE-AAC"

    stream_data["ce_audio_profile"] = audio_profile
    return stream_data


def has_avdvplus_streamdetails_columns(cursor: Any) -> bool:
    """Return True if the video DB's `streamdetails` table has avdvplus extended columns."""
    conn_key = id(getattr(cursor, "connection", cursor))
    with _SCHEMA_LOCK:
        cached = _SCHEMA_CACHE.get(conn_key)
    if cached is not None:
        return cached

    try:
        cols = {row[1] for row in cursor.execute("PRAGMA table_info(streamdetails)").fetchall()}
        supported = {"strHdrTypeAlt", "strDvProfile", "strAudioProfile"}.issubset(cols)
    except Exception:
        supported = False

    with _SCHEMA_LOCK:
        if len(_SCHEMA_CACHE) > 64:
            _SCHEMA_CACHE.clear()
        _SCHEMA_CACHE[conn_key] = supported
    return supported


def clear_schema_cache() -> None:
    with _SCHEMA_LOCK:
        _SCHEMA_CACHE.clear()


def write_avdvplus_streamdetails(
    cursor: Any,
    kodi_file_id: int,
    videostream: Sequence[dict[str, Any]],
    audiostream: Sequence[dict[str, Any]],
    subtitlestream: Sequence[dict[str, Any]],
    runtime: Any,
    video_db_version: int = 131,
) -> bool:
    """Write `streamdetails` including avdvplus extended columns when supported.

    Returns True if handled (caller should return early), False to fall back to
    upstream `VideoDatabase.add_streams()`.
    """
    if not config.is_enabled("ce_avdvplus_badges"):
        return False
    # Kodi 22 (v144+) has its own native strHdrDetail schema; let upstream handle it
    if video_db_version >= 144:
        return False
    if not has_avdvplus_streamdetails_columns(cursor):
        return False

    cursor.execute("DELETE FROM streamdetails WHERE idFile = ?", (kodi_file_id,))
    rows = []

    for track in videostream:
        rows.append(
            (
                kodi_file_id,
                0,
                track.get("codec"),
                track.get("aspect"),
                track.get("width"),
                track.get("height"),
                runtime,
                track.get("stereomode"),
                track.get("language"),
                track.get("hdrtype"),
                track.get("ce_hdr_alt", "") or None,
                track.get("ce_dv_profile", "") or None,
                None,
                None,
                None,
                None,
                None,
            )
        )

    for track in audiostream:
        rows.append(
            (
                kodi_file_id,
                1,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                track.get("codec"),
                track.get("channels"),
                track.get("language"),
                track.get("ce_audio_profile", "") or None,
                None,
            )
        )

    for track in subtitlestream:
        if str(track.get("external", "0")) == "0":
            rows.append(
                (
                    kodi_file_id,
                    2,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    track.get("language"),
                )
            )

    if rows:
        cursor.executemany(
            "INSERT INTO streamdetails("
            "idFile, iStreamType, strVideoCodec, fVideoAspect, iVideoWidth, iVideoHeight, "
            "iVideoDuration, strStereoMode, strVideoLanguage, strHdrType, strHdrTypeAlt, strDvProfile, "
            "strAudioCodec, iAudioChannels, strAudioLanguage, strAudioProfile, strSubtitleLanguage"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    return True
