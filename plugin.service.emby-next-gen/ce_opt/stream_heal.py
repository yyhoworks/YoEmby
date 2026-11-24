"""Self-healing backfill for cloud STRM items missing Emby MediaStreams.

When Emby never probed a `.strm` item (logging `No mediastreams found`), Kodi's
FFmpeg still probes real stream metadata during playback and writes it to
`MyVideos*.db` (`streamdetails`). This module copies those newly probed video,
audio, and subtitle streams back into `emby_*.db` (`VideoStreams`, `AudioStreams`,
`Subtitles`) so YoPlayer's `infuse_preplay.py` track picker and media badges
work immediately on subsequent views—strictly preserving the YoPlayer DB schema.
"""

from __future__ import annotations

import threading
from typing import Any

from . import config

_KODI_TO_EMBY_TABLE = {
    "movie": "Movie",
    "episode": "Episode",
    "video": "Video",
    "videoversion": "Video",
}

_STATS_LOCK = threading.Lock()
_HEALED_COUNT = 0


def get_healed_count() -> int:
    with _STATS_LOCK:
        return _HEALED_COUNT


def _build_audio_display_title(codec: str, channels: Any, lang: str, profile: str = "", prop_name: str = "") -> str:
    if prop_name:
        return prop_name
    parts = []
    if lang:
        parts.append(lang.upper())
    if profile:
        parts.append(profile)
    elif codec:
        parts.append(codec.upper())
    if channels:
        ch_map = {8: "7.1", 6: "5.1", 2: "2.0", 1: "1.0"}
        parts.append(ch_map.get(int(channels), f"{channels}ch"))
    return " ".join(parts) or "Audio"


def _build_sub_display_title(lang: str, prop_name: str = "") -> str:
    if prop_name:
        return prop_name
    return lang.upper() if lang else "Subtitle"


def extract_probed_streams(
    video_cur: Any,
    kodi_file_id: int,
    player_props: dict[str, Any] | None = None,
) -> tuple[list[tuple], list[tuple], list[tuple]]:
    """Read Kodi's probed `streamdetails` rows for `kodi_file_id` and map them to
    `(video_rows, audio_rows, subtitle_rows)` tuples ready for emby.db.
    """
    cols = {r[1] for r in video_cur.execute("PRAGMA table_info(streamdetails)").fetchall()}
    has_audio_profile = "strAudioProfile" in cols
    select_audio_prof = "strAudioProfile" if has_audio_profile else "NULL"

    rows = video_cur.execute(
        f"SELECT iStreamType, strVideoCodec, iVideoWidth, strAudioCodec, iAudioChannels, "
        f"strAudioLanguage, {select_audio_prof}, strSubtitleLanguage "
        f"FROM streamdetails WHERE idFile = ? ORDER BY rowid",
        (kodi_file_id,),
    ).fetchall()

    prop_audios = (player_props or {}).get("audiostreams") or []
    prop_subs = (player_props or {}).get("subtitles") or []

    video_out: list[tuple] = []
    audio_out: list[tuple] = []
    sub_out: list[tuple] = []

    stream_idx = 0
    audio_pos = 0
    sub_pos = 0

    for stype, vcodec, vwidth, acodec, ach, alang, aprof, slang in rows:
        if stype == 0:
            video_out.append((stream_idx, (vcodec or "").lower(), 0, int(vwidth or 0)))
            stream_idx += 1
        elif stype == 1:
            p_name = ""
            if audio_pos < len(prop_audios) and isinstance(prop_audios[audio_pos], dict):
                p_name = str(prop_audios[audio_pos].get("name") or "").strip()
            title = _build_audio_display_title(acodec or "", ach, alang or "", aprof or "", p_name)
            audio_out.append((stream_idx, title, (acodec or "").lower(), 0))
            audio_pos += 1
            stream_idx += 1
        elif stype == 2:
            p_name = ""
            if sub_pos < len(prop_subs) and isinstance(prop_subs[sub_pos], dict):
                p_name = str(prop_subs[sub_pos].get("name") or "").strip()
            lang = slang or "und"
            title = _build_sub_display_title(lang, p_name)
            sub_out.append((stream_idx, "sub", lang, title, 0))
            sub_pos += 1
            stream_idx += 1

    return video_out, audio_out, sub_out


def backfill_emby_streams_from_cursors(
    emby_cur: Any,
    video_cur: Any,
    emby_id: int,
    kodi_type: str,
    player_props: dict[str, Any] | None = None,
) -> bool:
    """Backfill `VideoStreams`/`AudioStreams`/`Subtitles` in `emby_cur` from `video_cur`
    if and only if `emby_id` currently has zero `VideoStreams` rows.

    Returns True when rows were backfilled.
    """
    if not config.is_enabled("ce_strm_heal"):
        return False

    table = _KODI_TO_EMBY_TABLE.get(str(kodi_type or "").lower())
    if not table or not emby_id:
        return False

    # Fast path: skip if Emby already had VideoStreams
    if emby_cur.execute("SELECT 1 FROM VideoStreams WHERE EmbyId = ? LIMIT 1", (emby_id,)).fetchone():
        return False

    row = emby_cur.execute(f"SELECT KodiFileId FROM {table} WHERE EmbyId = ? LIMIT 1", (emby_id,)).fetchone()
    if not row or not row[0]:
        return False
    kodi_file_id = int(row[0])

    v_rows, a_rows, s_rows = extract_probed_streams(video_cur, kodi_file_id, player_props)
    if not v_rows:
        return False

    emby_cur.executemany(
        "INSERT OR REPLACE INTO VideoStreams (EmbyId, StreamIndex, Codec, BitRate, Width) VALUES (?, ?, ?, ?, ?)",
        [(emby_id, idx, codec, br, w) for idx, codec, br, w in v_rows],
    )
    if a_rows:
        emby_cur.executemany(
            "INSERT OR REPLACE INTO AudioStreams (EmbyId, StreamIndex, DisplayTitle, Codec, BitRate) VALUES (?, ?, ?, ?, ?)",
            [(emby_id, idx, title, codec, br) for idx, title, codec, br in a_rows],
        )
    if s_rows:
        emby_cur.executemany(
            "INSERT OR REPLACE INTO Subtitles (EmbyId, StreamIndex, Codec, Language, DisplayTitle, External) VALUES (?, ?, ?, ?, ?, ?)",
            [(emby_id, idx, codec, lang, title, ext) for idx, codec, lang, title, ext in s_rows],
        )

    global _HEALED_COUNT
    with _STATS_LOCK:
        _HEALED_COUNT += 1
    return True


def heal_after_playback(
    server_id: str,
    emby_id: Any,
    kodi_type: str,
    dbio_module: Any,
    player_props: dict[str, Any] | None = None,
) -> bool:
    """High-level entry called from `helper/player.py:stop_playback` via a 1-line hook.

    Fast-checks RO first so normal plays with existing streams never open RW locks.
    """
    if not config.is_enabled("ce_strm_heal"):
        return False
    table = _KODI_TO_EMBY_TABLE.get(str(kodi_type or "").lower())
    if not table or not server_id or not emby_id:
        return False

    try:
        eid = int(emby_id)
    except (TypeError, ValueError):
        return False

    # Fast RO check: zero RW lock overhead for items that already have streams
    emby_ro = None
    try:
        emby_ro = dbio_module.DBOpenRO(server_id, "ce_strm_heal_ro")
        has_video = emby_ro.cursor.execute(
            "SELECT 1 FROM VideoStreams WHERE EmbyId = ? LIMIT 1", (eid,)
        ).fetchone()
        if has_video:
            return False
        frow = emby_ro.cursor.execute(
            f"SELECT KodiFileId FROM {table} WHERE EmbyId = ? LIMIT 1", (eid,)
        ).fetchone()
        if not frow or not frow[0]:
            return False
        kodi_file_id = int(frow[0])
    except Exception:
        return False
    finally:
        if emby_ro is not None:
            try:
                dbio_module.DBCloseRO(server_id, "ce_strm_heal_ro")
            except Exception:
                pass

    # Check Kodi video DB RO to see if FFmpeg probed streams during playback
    video_ro = None
    try:
        video_ro = dbio_module.DBOpenRO("video", "ce_strm_heal_vid")
        v_rows, a_rows, s_rows = extract_probed_streams(video_ro.cursor, kodi_file_id, player_props)
    except Exception:
        return False
    finally:
        if video_ro is not None:
            try:
                dbio_module.DBCloseRO("video", "ce_strm_heal_vid")
            except Exception:
                pass

    if not v_rows:
        return False

    # Write back into emby_*.db RW
    sqls: dict[str, Any] = {}
    try:
        dbio_module.DBOpenRW(server_id, "ce_strm_heal_rw", sqls)
        cur = sqls["emby"].cursor
        cur.executemany(
            "INSERT OR REPLACE INTO VideoStreams (EmbyId, StreamIndex, Codec, BitRate, Width) VALUES (?, ?, ?, ?, ?)",
            [(eid, idx, codec, br, w) for idx, codec, br, w in v_rows],
        )
        if a_rows:
            cur.executemany(
                "INSERT OR REPLACE INTO AudioStreams (EmbyId, StreamIndex, DisplayTitle, Codec, BitRate) VALUES (?, ?, ?, ?, ?)",
                [(eid, idx, title, codec, br) for idx, title, codec, br in a_rows],
            )
        if s_rows:
            cur.executemany(
                "INSERT OR REPLACE INTO Subtitles (EmbyId, StreamIndex, Codec, Language, DisplayTitle, External) VALUES (?, ?, ?, ?, ?, ?)",
                [(eid, idx, codec, lang, title, ext) for idx, codec, lang, title, ext in s_rows],
            )
        global _HEALED_COUNT
        with _STATS_LOCK:
            _HEALED_COUNT += 1
        return True
    except Exception:
        return False
    finally:
        if sqls.get("emby") is not None:
            try:
                dbio_module.DBCloseRW(server_id, "ce_strm_heal_rw", sqls)
            except Exception:
                pass
