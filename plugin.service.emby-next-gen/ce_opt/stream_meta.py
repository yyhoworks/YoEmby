"""Enhanced HDR10+/Atmos/DTS:X codec mapping and STRM streamdetails backfill.

All codec tokens align with Kodi 21 ``streamdetails`` and YoPlayer·Infuse skin
badges (``hdr10plus``, ``dolbyvision``, ``hdr10``, ``hlg``, ``truehd_atmos``,
``eac3_ddp_atmos``, ``dtsx``, ``dtshd_ma``, ``dtshd_hra``).
"""

import re

from ce_opt import config

_DOVI_PROFILE_MAP = {
    "DoviProfile50": "5",
    "DoviProfile76": "7",
    "DoviProfile81": "8.1",
    "DoviProfile84": "8.4",
    "DoviProfile92": "9.2",
    "DoviProfile10": "10",
}

_RES_MAP = {
    "4k": (3840, 2160),
    "2160": (3840, 2160),
    "1440": (2560, 1440),
    "1080": (1920, 1080),
    "720": (1280, 720),
    "576": (720, 576),
    "480": (720, 480),
}

_RE_RES_2160 = re.compile(r"(?:^|[\s._\-\[\(])(?:2160p|4k|uhd)(?:$|[\s._\-\]\)])", re.I)
_RE_RES_1080 = re.compile(r"(?:^|[\s._\-\[\(])1080[pi](?:$|[\s._\-\]\)])", re.I)
_RE_RES_720 = re.compile(r"(?:^|[\s._\-\[\(])720p(?:$|[\s._\-\]\)])", re.I)

_RE_VCODEC_HEVC = re.compile(r"(?:^|[\s._\-\[\(])(?:hevc|h\.?265|x265)(?:$|[\s._\-\]\)])", re.I)
_RE_VCODEC_AV1 = re.compile(r"(?:^|[\s._\-\[\(])av1(?:$|[\s._\-\]\)])", re.I)
_RE_VCODEC_H264 = re.compile(r"(?:^|[\s._\-\[\(])(?:avc|h\.?264|x264)(?:$|[\s._\-\]\)])", re.I)

_RE_HDR_DV = re.compile(r"(?:^|[\s._\-\[\(])(?:dv|dovi|dolby[\s._\-]?vision)(?:$|[\s._\-\]\)])", re.I)
_RE_HDR_10PLUS = re.compile(r"hdr\s*10\s*\+|hdr10plus", re.I)
_RE_HDR_10 = re.compile(r"(?:^|[\s._\-\[\(])hdr(?:10)?(?:$|[\s._\-\]\)])", re.I)
_RE_HDR_HLG = re.compile(r"(?:^|[\s._\-\[\(])hlg(?:$|[\s._\-\]\)])", re.I)

_RE_ATMOS = re.compile(r"atmos", re.I)
_RE_TRUEHD = re.compile(r"truehd", re.I)
_RE_EAC3 = re.compile(r"(?:^|[\s._\-\[\(])(?:ddp|dd\+|e[\-.]?ac3|eac3)(?:[\s._\-]?\d|\b)", re.I)
_RE_DTSX = re.compile(r"dts[\s._\-:]?x(?:$|[\s._\-\]\)])", re.I)
_RE_DTSHD_MA = re.compile(r"dts[\s._\-]?hd[\s._\-]?ma", re.I)
_RE_DTSHD_HRA = re.compile(r"dts[\s._\-]?hd(?:[\s._\-]?hra)?", re.I)
_RE_DTS = re.compile(r"(?:^|[\s._\-\[\(])dts(?:$|[\s._\-\]\)])", re.I)
_RE_AC3 = re.compile(r"(?:^|[\s._\-\[\(])(?:ac3|dd5\.?1)(?:$|[\s._\-\]\)])", re.I)
_RE_FLAC = re.compile(r"(?:^|[\s._\-\[\(])flac(?:$|[\s._\-\]\)])", re.I)
_RE_AAC = re.compile(r"(?:^|[\s._\-\[\(])aac(?:$|[\s._\-\]\)])", re.I)

_RE_CH_71 = re.compile(r"(?:^|[\s._\-\[\(a-z])7\.1(?:$|[\s._\-\]\)])", re.I)
_RE_CH_51 = re.compile(r"(?:^|[\s._\-\[\(a-z])5\.1(?:$|[\s._\-\]\)])", re.I)
_RE_CH_20 = re.compile(r"(?:^|[\s._\-\[\(a-z])2\.0(?:$|[\s._\-\]\)])", re.I)


def normalize_audio_codec(stream, base_codec):
    """Map Emby audio stream codec/profile/title to fine-grained Kodi/Infuse tokens."""
    codec = (base_codec or "").lower().replace("-", "")
    if not config.is_enabled("STREAM_META_ENHANCED"):
        return codec

    profile = (stream.get("Profile") or "").lower()
    title = f"{stream.get('DisplayTitle') or ''} {stream.get('Title') or ''}".lower()
    combined = f"{profile} {title}"

    if codec == "dts":
        if "dts:x" in combined or "dtsx" in combined or "dts-x" in combined or "ma + x" in combined:
            return "dtsx"
        if "dts-hd ma" in profile or "dtshd_ma" in combined or "dts-hd ma" in combined:
            return "dtshd_ma"
        if "dts-hd hra" in profile or "dtshd_hra" in combined or "dts-hd hra" in combined:
            return "dtshd_hra"
    elif codec == "truehd":
        if "atmos" in combined:
            return "truehd_atmos"
    elif codec in ("eac3", "ec3"):
        if "atmos" in combined:
            return "eac3_ddp_atmos"
        return "eac3"

    return codec


def detect_hdr_type(stream):
    """Detect (hdrtype, hdrdetail) including HDR10+, Dolby Vision, HDR10, and HLG."""
    video_range = (stream.get("VideoRange") or "").strip().lower()
    ext_type = (stream.get("ExtendedVideoType") or "").strip().lower()
    ext_sub = (stream.get("ExtendedVideoSubType") or "").strip()
    display_title = (stream.get("DisplayTitle") or "").strip().lower()

    if not config.is_enabled("STREAM_META_ENHANCED"):
        if video_range == "hdr 10":
            return "hdr10", ""
        if video_range == "hlg":
            return "hlg", ""
        if video_range == "dolbyvision":
            return "dolbyvision", _DOVI_PROFILE_MAP.get(ext_sub, "")
        return None, ""

    # Dolby Vision takes priority (e.g. DOVIWithHDR10 / DolbyVision)
    if (
        "dolbyvision" in video_range
        or "dovi" in video_range
        or "dolbyvision" in ext_type
        or "dolby vision" in display_title
    ):
        return "dolbyvision", _DOVI_PROFILE_MAP.get(ext_sub, "")

    # HDR10+ (Emby ExtendedVideoType='Hdr10Plus' or VideoRange='HDR10+')
    if (
        "hdr10plus" in ext_type
        or "hdr10+" in video_range
        or "hdr 10+" in video_range
        or "hdr10plus" in video_range
        or "hdr10+" in display_title
        or "hdr10plus" in display_title
    ):
        return "hdr10plus", ""

    # HLG
    if video_range == "hlg" or "hlg" in ext_type or "hyperloggamma" in ext_type:
        return "hlg", ""

    # Standard HDR10
    if video_range in ("hdr 10", "hdr10", "hdr") or ext_type == "hdr10":
        return "hdr10", ""

    return None, ""


def infer_streams_from_name(item, media_source):
    """Infer fallback Video/Audio streamdetails from filename when Emby MediaStreams is empty.

    Never overwrites existing probed streams. Returns True if any stream was inferred.
    """
    if not config.is_enabled("STREAM_STRM_NAME_FALLBACK"):
        return False

    kodi_streams = media_source.get("KodiStreams")
    if not kodi_streams or kodi_streams.get("Video"):
        return False

    text_parts = [
        media_source.get("Name") or "",
        item.get("Path") or "",
        item.get("Name") or "",
    ]
    text = " ".join(part for part in text_parts if part)
    if not text:
        return False

    width = None
    height = None
    if _RE_RES_2160.search(text):
        width, height = 3840, 2160
    elif _RE_RES_1080.search(text):
        width, height = 1920, 1080
    elif _RE_RES_720.search(text):
        width, height = 1280, 720

    vcodec = ""
    if _RE_VCODEC_HEVC.search(text):
        vcodec = "hevc"
    elif _RE_VCODEC_AV1.search(text):
        vcodec = "av1"
    elif _RE_VCODEC_H264.search(text):
        vcodec = "h264"

    hdrtype = None
    if _RE_HDR_DV.search(text):
        hdrtype = "dolbyvision"
    elif _RE_HDR_10PLUS.search(text):
        hdrtype = "hdr10plus"
    elif _RE_HDR_HLG.search(text):
        hdrtype = "hlg"
    elif _RE_HDR_10.search(text):
        hdrtype = "hdr10"

    added = False
    if width or vcodec or hdrtype:
        aspect = round(float(width) / float(height), 6) if (width and height) else None
        kodi_streams["Video"].append(
            {
                "language": "",
                "hdrtype": hdrtype,
                "hdrdetail": "",
                "codec": vcodec,
                "height": height,
                "width": width,
                "BitRate": None,
                "Index": 0,
                "aspect": aspect,
                "stereomode": "",
                "default": True,
                "hearingimpaired": False,
            }
        )
        added = True

    if not kodi_streams.get("Audio"):
        acodec = ""
        has_atmos = bool(_RE_ATMOS.search(text))
        if _RE_TRUEHD.search(text):
            acodec = "truehd_atmos" if has_atmos else "truehd"
        elif _RE_EAC3.search(text):
            acodec = "eac3_ddp_atmos" if has_atmos else "eac3"
        elif _RE_DTSX.search(text):
            acodec = "dtsx"
        elif _RE_DTSHD_MA.search(text):
            acodec = "dtshd_ma"
        elif _RE_DTSHD_HRA.search(text):
            acodec = "dtshd_hra"
        elif _RE_DTS.search(text):
            acodec = "dts"
        elif _RE_AC3.search(text):
            acodec = "ac3"
        elif _RE_FLAC.search(text):
            acodec = "flac"
        elif _RE_AAC.search(text):
            acodec = "aac"

        channels = None
        if _RE_CH_71.search(text):
            channels = 8
        elif _RE_CH_51.search(text):
            channels = 6
        elif _RE_CH_20.search(text):
            channels = 2

        if acodec or channels:
            kodi_streams["Audio"].append(
                {
                    "SampleRate": None,
                    "BitRate": None,
                    "codec": acodec,
                    "channels": channels,
                    "language": "",
                    "Index": 1,
                    "DisplayTitle": acodec or "unknown",
                    "default": True,
                    "hearingimpaired": False,
                }
            )
            added = True

    return added


def _parse_duration_seconds(duration_str):
    if not duration_str:
        return None
    parts = duration_str.strip().split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    if len(nums) == 1:
        return nums[0]
    return None


def collect_player_stream_info(get_infolabel_fn):
    """Collect live demuxed stream info from Kodi's active VideoPlayer InfoLabels."""
    vcodec = (get_infolabel_fn("VideoPlayer.VideoCodec") or "").strip().lower()
    vres = (get_infolabel_fn("VideoPlayer.VideoResolution") or "").strip().lower()
    vaspect_raw = (get_infolabel_fn("VideoPlayer.VideoAspect") or "").strip()
    vhdr = (get_infolabel_fn("VideoPlayer.HdrType") or "").strip().lower()
    acodec = (get_infolabel_fn("VideoPlayer.AudioCodec") or "").strip().lower()
    ach_raw = (get_infolabel_fn("VideoPlayer.AudioChannels") or "").strip()
    alang = (get_infolabel_fn("VideoPlayer.AudioLanguage") or "").strip().lower()
    duration_sec = _parse_duration_seconds(get_infolabel_fn("Player.Duration") or "")

    width, height = _RES_MAP.get(vres, (None, None))
    if not width and vres.isdigit():
        h_val = int(vres)
        if h_val >= 2000:
            width, height = 3840, 2160
        elif h_val >= 1000:
            width, height = 1920, 1080
        elif h_val >= 700:
            width, height = 1280, 720

    aspect = None
    try:
        if vaspect_raw:
            aspect = round(float(vaspect_raw), 6)
    except ValueError:
        aspect = None
    if not aspect and width and height:
        aspect = round(float(width) / float(height), 6)

    if not vcodec and not width:
        return None, duration_sec

    hdrtype = vhdr if vhdr in ("dolbyvision", "hdr10plus", "hdr10", "hlg") else None
    streams = {
        "Video": [
            {
                "language": "",
                "hdrtype": hdrtype,
                "hdrdetail": "",
                "codec": vcodec,
                "height": height,
                "width": width,
                "aspect": aspect,
                "stereomode": "",
                "default": True,
                "hearingimpaired": False,
            }
        ],
        "Audio": [],
        "Subtitle": [],
    }

    channels = int(ach_raw) if ach_raw.isdigit() else None
    if acodec or channels:
        streams["Audio"].append(
            {
                "codec": acodec,
                "channels": channels,
                "language": alang,
                "default": True,
                "hearingimpaired": False,
            }
        )

    return streams, duration_sec


def maybe_backfill_from_player(kodi_id, kodi_type, xbmc_mod, dbio_mod):
    """Backfill missing Kodi streamdetails after playback starts on an unprobed STRM.

    No-op when ``streamdetails`` already has a video row for the file.
    """
    if not config.is_enabled("STREAM_PLAYBACK_BACKFILL"):
        return False
    if not kodi_id or kodi_type not in ("movie", "episode"):
        return False

    try:
        videodb = dbio_mod.DBOpenRO("video", "ce_stream_backfill")
        try:
            if kodi_type == "movie":
                videodb.cursor.execute("SELECT idFile FROM movie WHERE idMovie = ?", (kodi_id,))
            else:
                videodb.cursor.execute("SELECT idFile FROM episode WHERE idEpisode = ?", (kodi_id,))
            row = videodb.cursor.fetchone()
            if not row or not row[0]:
                return False
            kodi_file_id = row[0]
            videodb.cursor.execute(
                "SELECT 1 FROM streamdetails WHERE idFile = ? AND iStreamType = 0 LIMIT 1",
                (kodi_file_id,),
            )
            if videodb.cursor.fetchone():
                return False
        finally:
            dbio_mod.DBCloseRO("video", "ce_stream_backfill")

        # Give Kodi's demuxer a moment to publish VideoPlayer InfoLabels
        xbmc_mod.sleep(1500)
        streams, duration_sec = collect_player_stream_info(xbmc_mod.getInfoLabel)
        if not streams:
            return False

        sqls = {}
        dbio_mod.DBOpenRW("video", "ce_stream_backfill", sqls)
        try:
            sqls["video"].add_streams(kodi_file_id, streams, duration_sec)
        finally:
            dbio_mod.DBCloseRW("video", "ce_stream_backfill", sqls)

        xbmc_mod.log(
            f"EMBY.ce_opt.stream_meta: Backfilled streamdetails for {kodi_type} idFile={kodi_file_id}",
            1,
        )
        return True
    except Exception as err:
        xbmc_mod.log(f"EMBY.ce_opt.stream_meta: Backfill skipped ({err})", 2)
        return False
