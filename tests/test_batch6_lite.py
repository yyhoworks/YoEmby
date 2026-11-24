"""Unit tests for Batch 6: CoreELEC pure-cinema Lite Mode & lazy black.* media."""

from __future__ import annotations

import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ADDON_ROOT = Path(__file__).resolve().parent.parent / "plugin.service.emby-next-gen"
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

from ce_opt import config, lite


class _FakeWindow:
    def __init__(self) -> None:
        self.props: dict[str, str] = {}

    def setProperty(self, key: str, value: str) -> None:
        self.props[key] = value


class TestLiteModeGuards(unittest.TestCase):
    def setUp(self) -> None:
        config.reset_defaults()
        lite.clear_black_cache()

    def tearDown(self) -> None:
        config.reset_defaults()
        lite.clear_black_cache()

    def test_lazy_black_media_loads_on_demand_and_caches(self) -> None:
        reads: list[str] = []

        def fake_read(path: str) -> bytes:
            reads.append(path)
            return b"FAKE_VIDEO_PAYLOAD"

        self.assertEqual(lite.get_black_cache_keys(), ())

        resp1 = lite.get_black_media_response("/http/movies/demo.mkv", fake_read)
        self.assertEqual(len(reads), 1)
        self.assertTrue(reads[0].endswith("/resources/black.mkv"))
        self.assertIn(b"HTTP/1.1 200 OK\r\n", resp1)
        self.assertIn(b"Content-Type: video/x-matroska\r\n", resp1)
        self.assertIn(f"Content-Length: {len(b'FAKE_VIDEO_PAYLOAD')}\r\n".encode(), resp1)
        self.assertTrue(resp1.endswith(b"\r\n\r\nFAKE_VIDEO_PAYLOAD"))

        # Second call for .mkv hits memory cache without re-reading disk
        resp2 = lite.get_black_media_response("/http/episodes/another.MKV", fake_read)
        self.assertEqual(resp1, resp2)
        self.assertEqual(len(reads), 1)

        # .m2ts maps to black.ts, unknown extension defaults to black.mp4
        resp_ts = lite.get_black_media_response("/http/bd/00001.m2ts", fake_read)
        self.assertIn(b"Content-Type: video/mp2t\r\n", resp_ts)
        resp_def = lite.get_black_media_response("/http/unknown.xyz", fake_read)
        self.assertIn(b"Content-Type: video/mp4\r\n", resp_def)
        self.assertEqual(lite.get_black_cache_keys(), ("black.mkv", "black.mp4", "black.ts"))

    def test_themes_rollback_and_trailer_guards_and_reversibility(self) -> None:
        # Default Lite Mode ON
        self.assertTrue(lite.is_lite_mode())
        self.assertFalse(lite.should_start_themes_thread(False, False))
        self.assertTrue(lite.should_start_themes_thread(True, False))
        self.assertFalse(lite.should_create_rollback())
        self.assertTrue(lite.should_skip_theme_sync(False, False))
        self.assertFalse(lite.should_skip_theme_sync(False, True))
        self.assertTrue(lite.should_skip_trailer_sync(False, False))
        self.assertFalse(lite.should_skip_trailer_sync(True, False))

        # Disable ce_lite_mode -> restores all upstream behavior
        config.set_override(ce_lite_mode=False)
        self.assertFalse(lite.is_lite_mode())
        self.assertTrue(lite.should_start_themes_thread(False, False))
        self.assertTrue(lite.should_create_rollback())
        self.assertFalse(lite.should_skip_theme_sync(False, False))
        self.assertFalse(lite.should_skip_trailer_sync(False, False))

        # Master kill switch ce_enabled=False also restores upstream behavior
        config.set_override(ce_lite_mode=True, ce_enabled=False)
        self.assertFalse(lite.is_lite_mode())
        self.assertTrue(lite.should_start_themes_thread(False, False))
        self.assertTrue(lite.should_create_rollback())

    def test_context_menu_property_filtering(self) -> None:
        win = _FakeWindow()
        raw_props = {
            "EmbyRemote": True,
            "EmbyDownload": True,
            "EmbyRecording": True,
            "EmbyPlayRandom": True,
            "EmbySimilar": True,
            "EmbySettings": True,
            "EmbyDelete": True,
            "EmbySpecials": True,
            "EmbyGoto": True,
            "EmbyRefresh": True,
            "EmbyFavourite": True,
        }
        lite.apply_context_window_properties(win, raw_props)
        for hidden in lite.LITE_SUPPRESSED_CONTEXT_PROPS:
            self.assertEqual(win.props[hidden], "False")
        for kept in ("EmbySpecials", "EmbyGoto", "EmbyRefresh", "EmbyFavourite"):
            self.assertEqual(win.props[kept], "True")

        # Turning off Lite Mode restores all upstream values
        config.set_override(ce_lite_mode=False)
        win2 = _FakeWindow()
        lite.apply_context_window_properties(win2, raw_props)
        self.assertEqual(win2.props["EmbyRemote"], "True")
        self.assertEqual(win2.props["EmbyDelete"], "True")

    def test_settings_xml_hides_unused_categories_and_groups_safely(self) -> None:
        root = ET.parse(ADDON_ROOT / "resources" / "settings.xml").getroot()
        cats = {c.attrib.get("id"): c for c in root.iter("category")}

        # Hidden dead categories still keep their setting definitions intact for load_settings()
        for hidden_cat in ("Themes", "cinema", "DynamicInfos", "Backup"):
            self.assertEqual(cats[hidden_cat].findtext("visible"), "false")

        # Essential categories remain visible
        for visible_cat in ("general", "sync", "playback", "Interface", "Advanced", "ce_opt"):
            self.assertNotEqual(cats[visible_cat].findtext("visible"), "false")

        # Hidden setting IDs remain present in XML so Addon.getSetting never misses defaults
        all_ids = {s.attrib.get("id") for s in root.iter("setting")}
        for upstream_id in ("theme_enable_audio", "enableCinemaMovies", "transcode_h264", "backupPath", "enableSkipIntro"):
            self.assertIn(upstream_id, all_ids)

        # Playback Skip Intro/Credits (group 3) stays visible while Transcode (group 7) is hidden
        pb_groups = list(cats["playback"].findall("group"))
        g3 = next(g for g in pb_groups if g.attrib.get("id") == "3")
        g7 = next(g for g in pb_groups if g.attrib.get("id") == "7")
        self.assertNotEqual(g3.findtext("visible"), "false")
        self.assertEqual(g7.findtext("visible"), "false")


if __name__ == "__main__":
    unittest.main()
