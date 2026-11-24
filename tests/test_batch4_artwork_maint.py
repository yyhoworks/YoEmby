"""Unit tests for Batch 4: ce_opt.artwork, ce_opt.maintenance & settings.xml validity."""

from __future__ import annotations

import sqlite3
import struct
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ADDON_ROOT = Path(__file__).resolve().parent.parent / "plugin.service.emby-next-gen"
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

from ce_opt import artwork, config, db_opt, maintenance


class TestArtwork(unittest.TestCase):
    def tearDown(self) -> None:
        config.reset_defaults()

    def test_build_artwork_redirect_url_poster_and_backdrop(self) -> None:
        poster = artwork.build_artwork_redirect_url(
            "http://emby:8096", "tok", "123", "Primary", "0", "abc123", False
        )
        self.assertIn("tag=abc123", poster)
        self.assertIn("maxWidth=800", poster)
        self.assertIn("quality=85", poster)
        self.assertNotIn("?&", poster)

        backdrop = artwork.build_artwork_redirect_url(
            "http://emby:8096", "tok", "123", "Backdrop", "0", "def456", True
        )
        self.assertIn("maxWidth=1920", backdrop)
        self.assertIn("EnableImageEnhancers=True", backdrop)

        # Disabled switch falls back to upstream format
        config.set_override(ce_artwork_307_opt=False)
        fallback = artwork.build_artwork_redirect_url(
            "http://emby:8096", "tok", "123", "Primary", "0", "abc123", False
        )
        self.assertNotIn("maxWidth=", fallback)
        self.assertIn("api_key=tok", fallback)

    def test_parse_webp_vp8x_vp8_vp8l(self) -> None:
        # VP8X: 1200x1800 -> stored as (w-1, h-1) 24-bit LE at offsets 24..30
        w_m1 = (1200 - 1).to_bytes(3, "little")
        h_m1 = (1800 - 1).to_bytes(3, "little")
        vp8x = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"VP8X" + b"\x0a\x00\x00\x00" + b"\x00\x00\x00\x00" + w_m1 + h_m1
        self.assertEqual(artwork.parse_webp_dimensions(vp8x), (1200, 1800))

        # VP8 lossy: 1920x1080
        vp8 = b"RIFF\x00\x00\x00\x00WEBPVP8 \x00\x00\x00\x00\x00\x00\x00\x9d\x01\x2a" + struct.pack("<HH", 1920, 1080)
        self.assertEqual(artwork.parse_webp_dimensions(vp8), (1920, 1080))

        # VP8L lossless: 800x600
        bits = ((800 - 1) & 0x3FFF) | (((600 - 1) & 0x3FFF) << 14)
        vp8l = b"RIFF\x00\x00\x00\x00WEBPVP8L\x00\x00\x00\x00\x2f" + struct.pack("<I", bits) + b"\x00" * 10
        self.assertEqual(artwork.parse_webp_dimensions(vp8l), (800, 600))

        # Invalid bytes
        self.assertEqual(artwork.parse_webp_dimensions(b"NOT_WEBP_DATA"), (0, 0))


class TestMaintenanceAndSettingsXml(unittest.TestCase):
    def tearDown(self) -> None:
        config.reset_defaults()

    def test_health_report_batch_heal_and_safe_rollback_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            emby_db = root / "emby_srv.db"
            vid_db = root / "MyVideos131.db"
            rb_dir = root / "rollback"
            rb_dir.mkdir()
            (rb_dir / "old.txt").write_bytes(b"x" * 2048)

            # Build minimal Emby DB
            ec = sqlite3.connect(emby_db)
            ec.execute("CREATE TABLE Movie (EmbyId INTEGER PRIMARY KEY, KodiFileId INTEGER, EmbyPresentationKey TEXT)")
            ec.execute("CREATE TABLE Episode (EmbyId INTEGER PRIMARY KEY, KodiFileId INTEGER, KodiParentId INTEGER, EmbyPresentationKey TEXT)")
            ec.execute("CREATE TABLE Series (EmbyId INTEGER PRIMARY KEY, EmbyPresentationKey TEXT)")
            ec.execute("CREATE TABLE Season (EmbyId INTEGER PRIMARY KEY, KodiParentId INTEGER, EmbyPresentationKey TEXT)")
            ec.execute("CREATE TABLE Video (EmbyId INTEGER PRIMARY KEY, KodiId INTEGER, KodiFileId INTEGER)")
            ec.execute("CREATE TABLE UpdateItems (EmbyId INTEGER, EmbyLibraryId TEXT)")
            ec.execute("CREATE TABLE MediaSources (EmbyId INTEGER, MediaSourceId TEXT, Path TEXT)")
            ec.execute("CREATE TABLE VideoStreams (EmbyId INTEGER, StreamIndex INTEGER, Codec TEXT, BitRate INTEGER, Width INTEGER, PRIMARY KEY(EmbyId, StreamIndex))")
            ec.execute("CREATE TABLE AudioStreams (EmbyId INTEGER, StreamIndex INTEGER, DisplayTitle TEXT, Codec TEXT, BitRate INTEGER, PRIMARY KEY(EmbyId, StreamIndex))")
            ec.execute("CREATE TABLE Subtitles (EmbyId INTEGER, StreamIndex INTEGER, Codec TEXT, Language TEXT, DisplayTitle TEXT, External BOOL, PRIMARY KEY(EmbyId, StreamIndex))")
            ec.execute("INSERT INTO Movie VALUES (101, 10, 'pk1')")
            ec.execute("INSERT INTO MediaSources VALUES (101, 'ms1', 'http://cdn/m1.mkv')")
            db_opt.ensure_emby_indexes(ec.cursor(), commit_transaction=False)
            ec.commit()

            # Build minimal avdvplus MyVideos DB
            vc = sqlite3.connect(vid_db)
            vc.execute("CREATE TABLE movie (idMovie INTEGER PRIMARY KEY, idFile INTEGER)")
            vc.execute("CREATE TABLE episode (idEpisode INTEGER PRIMARY KEY, idFile INTEGER)")
            vc.execute("CREATE TABLE bookmark (idBookmark INTEGER PRIMARY KEY)")
            vc.execute(
                "CREATE TABLE streamdetails (idFile integer, iStreamType integer, strVideoCodec text, iVideoWidth integer, "
                "strAudioCodec text, iAudioChannels integer, strAudioLanguage text, strSubtitleLanguage text, "
                "strHdrType text, strHdrTypeAlt text, strDvProfile text, strAudioProfile text)"
            )
            vc.execute("INSERT INTO movie VALUES (1, 10)")
            vc.execute("INSERT INTO streamdetails VALUES (10, 0, 'hevc', 3840, NULL, NULL, NULL, NULL, 'dolbyvision', 'hdr10', '8.1', NULL)")
            vc.execute("INSERT INTO streamdetails VALUES (10, 1, NULL, NULL, 'eac3', 6, 'eng', NULL, NULL, NULL, NULL, 'Dolby Atmos')")
            vc.commit()

            # Health report before batch heal
            rep = maintenance.collect_health_report(emby_db, vid_db, "", "", rb_dir, "")
            self.assertEqual(rep["emby_db"]["ce_indexes_present"], len(db_opt.EMBY_ADDITIVE_INDEXES))
            self.assertEqual(rep["emby_db"]["items_missing_videostreams"], 1)
            self.assertTrue(rep["video_db"]["avdvplus_columns"])
            self.assertEqual(rep["video_db"]["dv_profile_populated"], 1)
            self.assertEqual(rep["video_db"]["audio_profile_populated"], 1)
            text = maintenance.format_health_report(rep)
            self.assertIn("YoEmby CoreELEC 健康体检报告", text)

            # Batch heal backfills Movie 101 from MyVideos
            healed = maintenance.batch_heal_from_kodi_db(ec.cursor(), vc.cursor())
            ec.commit()
            self.assertEqual(healed, 1)
            self.assertEqual(ec.execute("SELECT Width FROM VideoStreams WHERE EmbyId=101").fetchone(), (3840,))
            ec.close()
            vc.close()

            # Safe rollback cleanup
            ok, freed = maintenance.safe_clear_rollback(rb_dir)
            self.assertTrue(ok)
            self.assertEqual(freed, 2048)
            self.assertFalse(rb_dir.exists())

    def test_settings_xml_well_formed_and_contains_ce_category(self) -> None:
        tree = ET.parse(ADDON_ROOT / "resources" / "settings.xml")
        root = tree.getroot()
        cats = [c.attrib.get("id") for c in root.iter("category")]
        self.assertIn("ce_opt", cats)
        setting_ids = {s.attrib.get("id") for s in root.iter("setting")}
        for expected in ("ce_enabled", "ce_sync_debounce", "ce_avdvplus_badges", "ce_strm_heal", "ce_maintenance_menu"):
            self.assertIn(expected, setting_ids)


if __name__ == "__main__":
    unittest.main()
