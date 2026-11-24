"""Unit tests for Batch 3: avdvplus badges, STRM stream healing, 302 path fix & multiversion."""

from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

ADDON_ROOT = Path(__file__).resolve().parent.parent / "plugin.service.emby-next-gen"
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

from ce_opt import config, stream_heal, stream_meta, strm


class TestAvdvplusStreamMeta(unittest.TestCase):
    def setUp(self) -> None:
        config.reset_defaults()
        stream_meta.clear_schema_cache()

    def tearDown(self) -> None:
        config.reset_defaults()
        stream_meta.clear_schema_cache()

    def test_enrich_dovi_profile_and_hdr10plus(self) -> None:
        dv_raw = {
            "VideoRange": "DolbyVision",
            "VideoRangeType": "DOVIWithHDR10",
            "ExtendedVideoSubType": "DoviProfile81",
        }
        dv_data = {"hdrtype": "dolbyvision", "hdrdetail": "8.1"}
        stream_meta.enrich_video_stream(dv_raw, dv_data)
        self.assertEqual(dv_data["hdrtype"], "dolbyvision")
        self.assertEqual(dv_data["ce_dv_profile"], "8.1")
        self.assertEqual(dv_data["ce_hdr_alt"], "hdr10")

        # Emby 4.8+ generic VideoRange="HDR" + VideoRangeType="HDR10Plus"
        hdrp_raw = {"VideoRange": "HDR", "VideoRangeType": "HDR10Plus"}
        hdrp_data = {"hdrtype": None, "hdrdetail": ""}
        stream_meta.enrich_video_stream(hdrp_raw, hdrp_data)
        self.assertEqual(hdrp_data["hdrtype"], "hdr10")
        self.assertEqual(hdrp_data["ce_hdr_alt"], "hdr10plus")

        # DoviProfile76 -> "7.6"
        dv7_raw = {"VideoRange": "HDR", "VideoRangeType": "DOVIWithEL", "ExtendedVideoSubType": "DoviProfile76"}
        dv7_data = {"hdrtype": None, "hdrdetail": ""}
        stream_meta.enrich_video_stream(dv7_raw, dv7_data)
        self.assertEqual(dv7_data["hdrtype"], "dolbyvision")
        self.assertEqual(dv7_data["ce_dv_profile"], "7.6")
        self.assertEqual(dv7_data["ce_hdr_alt"], "hdr10")

    def test_enrich_audio_profiles(self) -> None:
        a1 = {"codec": "truehd"}
        stream_meta.enrich_audio_stream({"DisplayTitle": "English TrueHD Dolby Atmos 7.1"}, a1)
        self.assertEqual(a1["ce_audio_profile"], "Dolby Atmos")

        a2 = {"codec": "dtshd_ma"}
        stream_meta.enrich_audio_stream({"Profile": "DTS-HD MA + DTS:X"}, a2)
        self.assertEqual(a2["ce_audio_profile"], "DTS:X")

        a3 = {"codec": "aac"}
        stream_meta.enrich_audio_stream({"Profile": "LC"}, a3)
        self.assertEqual(a3["ce_audio_profile"], "AAC-LC")

    def test_write_avdvplus_streamdetails_with_and_without_extended_columns(self) -> None:
        # 1. avdvplus schema (20 columns) -> handled by ce_opt
        con = sqlite3.connect(":memory:")
        cur = con.cursor()
        cur.execute(
            "CREATE TABLE streamdetails ("
            "idFile integer, iStreamType integer, strVideoCodec text, fVideoAspect float, "
            "iVideoWidth integer, iVideoHeight integer, strAudioCodec text, iAudioChannels integer, "
            "strAudioLanguage text, strSubtitleLanguage text, iVideoDuration integer, strStereoMode text, "
            "strVideoLanguage text, strHdrType text, strHdrTypeAlt text, strDvProfile text, "
            "strAudioProfile text, iAudioObjects integer, iAudioObjectChannels integer, iAudioBedChannels integer)"
        )
        v = [{"codec": "hevc", "aspect": 1.777, "width": 3840, "height": 2160, "stereomode": "", "language": "eng", "hdrtype": "dolbyvision", "ce_hdr_alt": "hdr10", "ce_dv_profile": "8.1"}]
        a = [{"codec": "eac3", "channels": 6, "language": "eng", "ce_audio_profile": "Dolby Atmos"}]
        s = [{"external": "0", "language": "chi"}, {"external": "1", "language": "eng"}]

        handled = stream_meta.write_avdvplus_streamdetails(cur, 42, v, a, s, 7200, video_db_version=131)
        self.assertTrue(handled)
        vrow = cur.execute("SELECT strHdrType, strHdrTypeAlt, strDvProfile FROM streamdetails WHERE idFile=42 AND iStreamType=0").fetchone()
        self.assertEqual(vrow, ("dolbyvision", "hdr10", "8.1"))
        arow = cur.execute("SELECT strAudioCodec, strAudioProfile FROM streamdetails WHERE idFile=42 AND iStreamType=1").fetchone()
        self.assertEqual(arow, ("eac3", "Dolby Atmos"))
        srows = cur.execute("SELECT strSubtitleLanguage FROM streamdetails WHERE idFile=42 AND iStreamType=2").fetchall()
        self.assertEqual(srows, [("chi",)])  # external sub skipped in streamdetails just like upstream
        con.close()

        # 2. Vanilla Kodi 21 schema (no strDvProfile) -> returns False (falls back to upstream)
        con2 = sqlite3.connect(":memory:")
        cur2 = con2.cursor()
        cur2.execute(
            "CREATE TABLE streamdetails (idFile integer, iStreamType integer, strVideoCodec text, strHdrType text)"
        )
        self.assertFalse(stream_meta.write_avdvplus_streamdetails(cur2, 42, v, a, s, 7200, video_db_version=131))
        con2.close()


class TestStreamHeal(unittest.TestCase):
    def tearDown(self) -> None:
        config.reset_defaults()

    def test_backfills_missing_strm_streams_and_skips_existing(self) -> None:
        emby_con = sqlite3.connect(":memory:")
        ec = emby_con.cursor()
        ec.execute("CREATE TABLE Episode (EmbyId INTEGER PRIMARY KEY, KodiFileId INTEGER)")
        ec.execute("CREATE TABLE VideoStreams (EmbyId INTEGER, StreamIndex INTEGER, Codec TEXT, BitRate INTEGER, Width INTEGER, PRIMARY KEY(EmbyId, StreamIndex))")
        ec.execute("CREATE TABLE AudioStreams (EmbyId INTEGER, StreamIndex INTEGER, DisplayTitle TEXT, Codec TEXT, BitRate INTEGER, PRIMARY KEY(EmbyId, StreamIndex))")
        ec.execute("CREATE TABLE Subtitles (EmbyId INTEGER, StreamIndex INTEGER, Codec TEXT, Language TEXT, DisplayTitle TEXT, External BOOL, PRIMARY KEY(EmbyId, StreamIndex))")
        ec.execute("INSERT INTO Episode VALUES (9001, 555)")

        vid_con = sqlite3.connect(":memory:")
        vc = vid_con.cursor()
        vc.execute(
            "CREATE TABLE streamdetails (idFile integer, iStreamType integer, strVideoCodec text, iVideoWidth integer, "
            "strAudioCodec text, iAudioChannels integer, strAudioLanguage text, strAudioProfile text, strSubtitleLanguage text)"
        )
        vc.execute("INSERT INTO streamdetails VALUES (555, 0, 'hevc', 3840, NULL, NULL, NULL, NULL, NULL)")
        vc.execute("INSERT INTO streamdetails VALUES (555, 1, NULL, NULL, 'eac3', 6, 'chi', 'Dolby Atmos', NULL)")
        vc.execute("INSERT INTO streamdetails VALUES (555, 2, NULL, NULL, NULL, NULL, NULL, NULL, 'chi')")

        self.assertTrue(stream_heal.backfill_emby_streams_from_cursors(ec, vc, 9001, "episode"))
        self.assertEqual(ec.execute("SELECT Codec, Width FROM VideoStreams WHERE EmbyId=9001").fetchall(), [("hevc", 3840)])
        self.assertEqual(ec.execute("SELECT DisplayTitle, Codec FROM AudioStreams WHERE EmbyId=9001").fetchall(), [("CHI Dolby Atmos 5.1", "eac3")])
        self.assertEqual(ec.execute("SELECT Language, DisplayTitle, External FROM Subtitles WHERE EmbyId=9001").fetchall(), [("chi", "CHI", 0)])

        # Second call sees existing VideoStreams -> fast-path False
        self.assertFalse(stream_heal.backfill_emby_streams_from_cursors(ec, vc, 9001, "episode"))
        emby_con.close()
        vid_con.close()


class TestStrmAndMultiversion(unittest.TestCase):
    def tearDown(self) -> None:
        config.reset_defaults()

    def test_finalize_http_paths_prevents_double_pipe(self) -> None:
        item = {
            "Type": "Movie",
            "KodiPath": "http://127.0.0.1:57342/http/movies/srv/1/0/99/m-1-1-/",
            "KodiFilename": "unknown.mkv",
            "KodiFullPath": "http://127.0.0.1:57342/http/movies/srv/1/0/99/m-1-1-/unknown.mkv",
        }
        handled = strm.finalize_http_paths(item, is_http_by_emby=True, follow_http=True, follow_http_timeout=5)
        self.assertTrue(handled)
        self.assertEqual(item["KodiFullPath"].count("|"), 1)
        self.assertEqual(item["KodiPath"].count("|"), 1)
        self.assertIn("connection-timeout=15", item["KodiFullPath"])
        self.assertIn("redirect-limit=1000", item["KodiFullPath"])

    def test_prepare_redirect_location_encodes_spaces_and_unicode(self) -> None:
        raw = "http://192.168.1.10:5244/d/电影/星际穿越 (2014).mkv?sign=abc%20def&t=1"
        encoded = strm.prepare_redirect_location(raw)
        self.assertNotIn(" ", encoded)
        self.assertIn("%20", encoded)
        self.assertIn("sign=abc%20def&t=1", encoded)
        self.assertTrue(encoded.startswith("http://192.168.1.10:5244/d/"))

    def test_multiversion_prefer_local_over_strm(self) -> None:
        config.set_override(ce_multiversion_policy="prefer_local")
        ws_sources = [
            [{"Name": "Cloud 4K", "Path": "http://cdn.example/movie_2160p.mkv", "Size": 20000}, [{"Width": 3840, "BitRate": 20000000}]],
            [{"Name": "LAN 1080p", "Path": r"\\192.168.1.168\sata1\movie_1080p.mkv", "Size": 10000}, [{"Width": 1920, "BitRate": 10000000}]],
        ]
        self.assertEqual(strm.select_best_mediasource_webservice(ws_sources), 1)

        config.set_override(ce_multiversion_policy="prefer_resolution")
        self.assertEqual(strm.select_best_mediasource_webservice(ws_sources), 0)

        # Movie default version upgrade works even when current default is unprobed STRM (width=0)
        config.set_override(ce_multiversion_policy="prefer_local")
        self.assertTrue(strm.should_prefer_movie_version("smb://nas/m.mkv", 1920, "http://127.0.0.1:57342/http/x", 0))
        self.assertFalse(strm.should_prefer_movie_version("http://127.0.0.1:57342/http/x", 3840, "smb://nas/m.mkv", 1920))

    def test_format_version_label(self) -> None:
        self.assertTrue(strm.format_version_label("4K", "20 GB", r"\\nas\a.mkv").startswith("[SMB] "))
        self.assertTrue(strm.format_version_label("4K", "20 GB", "http://cdn/a.mkv").startswith("[STRM] "))


if __name__ == "__main__":
    unittest.main()
