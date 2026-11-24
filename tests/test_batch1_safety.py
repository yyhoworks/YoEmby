"""Unit tests for Batch 1: ce_opt.config, ce_opt.safety, and P0/P1 upstream fixes."""

from __future__ import annotations

import errno
import sys
import unittest
from pathlib import Path

ADDON_ROOT = Path(__file__).resolve().parent.parent / "plugin.service.emby-next-gen"
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

from ce_opt import config, safety


class FakeAddon:
    def __init__(self, settings: dict[str, str]):
        self._settings = settings

    def getSetting(self, key: str) -> str:
        return self._settings.get(key, "")


class TestConfig(unittest.TestCase):
    def tearDown(self) -> None:
        config.reset_defaults()

    def test_defaults_and_master_switch(self) -> None:
        config.reset_defaults()
        self.assertTrue(config.is_enabled("ce_safe_workers"))
        self.assertTrue(config.is_enabled("ce_sync_fingerprint"))
        config.set_override(ce_enabled=False)
        self.assertFalse(config.is_enabled("ce_safe_workers"))
        self.assertFalse(config.is_enabled("ce_sync_fingerprint"))

    def test_reload_coerces_and_clamps_values(self) -> None:
        addon = FakeAddon(
            {
                "ce_enabled": "true",
                "ce_sync_debounce_sec": "999",
                "ce_widget_debounce_sec": "0.1",
                "ce_db_cache_kb": "128",
                "ce_strm_timeout": "25",
                "ce_artwork_quality": "120",
                "ce_multiversion_policy": "invalid_mode",
                "ce_skip_chapter_bookmarks": "true",
            }
        )
        state = config.reload(addon)
        self.assertEqual(state["ce_sync_debounce_sec"], 60.0)
        self.assertEqual(state["ce_widget_debounce_sec"], 1.0)
        self.assertEqual(state["ce_db_cache_kb"], 2048)
        self.assertEqual(state["ce_strm_timeout"], 25)
        self.assertEqual(state["ce_artwork_quality"], 100)
        self.assertEqual(state["ce_multiversion_policy"], "prefer_local")
        self.assertTrue(state["ce_skip_chapter_bookmarks"])


class TestSafetyHelpers(unittest.TestCase):
    def tearDown(self) -> None:
        config.reset_defaults()

    def test_highest_res_webservice_handles_empty_strm_streams(self) -> None:
        media_sources = [
            [{"Name": "ep 1080p", "Path": "http://cdn/a_1080p.mkv"}, []],
            [{"Name": "ep 2160p", "Path": "http://cdn/b_2160p.mkv"}, []],
        ]
        self.assertEqual(safety.safe_highest_resolution_index_webservice(media_sources), 1)

        media_sources_mixed = [
            [{"Name": "streamless", "Path": "http://cdn/x"}, []],
            [{"Name": "probed", "Path": "http://cdn/y"}, [{"Width": 3840}]],
            [{"Name": "hd", "Path": "http://cdn/z"}, [{"Width": 1920}]],
        ]
        self.assertEqual(safety.safe_highest_resolution_index_webservice(media_sources_mixed), 1)

    def test_highest_res_native_handles_missing_and_multiple_streams(self) -> None:
        # MediaSources tuples: (EmbyId, MediaSourceId, Path, Name, Size, ...)
        media_sources = [
            (1, "ms1", r"\\nas\m_1080p.mkv", "Movie 1080p", 5000),
            (1, "ms2", r"\\nas\m_2160p.mkv", "Movie 2160p", 20000),
        ]
        # Empty VideoStreams (unprobed STRM) must not crash
        self.assertEqual(safety.safe_highest_resolution_index_native(media_sources, []), 1)

        # Populated per-source VideoStreams: (EmbyId, StreamIndex, Codec, BitRate, Width)
        video_streams = [
            (1, 0, "hevc", 8000000, 1920),
            (1, 1, "hevc", 25000000, 3840),
        ]
        self.assertEqual(safety.safe_highest_resolution_index_native(media_sources, video_streams), 1)

        # None Width must not raise TypeError
        video_streams_none = [(1, 0, "hevc", None, None)]
        self.assertEqual(safety.safe_highest_resolution_index_native(media_sources, video_streams_none), 1)

    def test_match_external_subtitle_empty_default_does_not_match_all(self) -> None:
        sub = {"DisplayTitle": "Chinese Simplified", "language": "chi", "Forced": False}
        self.assertFalse(safety.match_external_subtitle("", sub))
        self.assertFalse(safety.match_external_subtitle("   ", sub))
        self.assertTrue(safety.match_external_subtitle("chi", sub))
        self.assertTrue(safety.match_external_subtitle("chinese", sub))
        self.assertFalse(safety.match_external_subtitle("forced_only", sub))
        self.assertTrue(safety.match_external_subtitle("forced_only", {**sub, "Forced": True}))

    def test_preserve_embedded_subtitles_switch(self) -> None:
        config.set_override(ce_enabled=True, ce_fix_subtitle_select=True)
        self.assertFalse(safety.should_disable_subtitles_on_no_external_match(None))
        # FileSettings index 9 is SubtitleEnable
        self.assertTrue(safety.should_disable_subtitles_on_no_external_match([0] * 9 + [0]))
        self.assertFalse(safety.should_disable_subtitles_on_no_external_match([0] * 9 + [1]))

        # Turning switch off restores upstream behavior
        config.set_override(ce_fix_subtitle_select=False)
        self.assertTrue(safety.should_disable_subtitles_on_no_external_match(None))

    def test_socket_close_error_detection(self) -> None:
        ebadf = OSError(errno.EBADF, "Bad file descriptor")
        self.assertTrue(safety.is_expected_socket_close_error(ebadf, True, False))
        self.assertTrue(safety.is_expected_socket_close_error(RuntimeError("x"), False, False))
        self.assertTrue(safety.is_expected_socket_close_error(RuntimeError("x"), True, True))
        self.assertFalse(safety.is_expected_socket_close_error(ValueError("unexpected"), True, False))

    def test_decode_http_request(self) -> None:
        text, parts = safety.decode_http_request(b"GET /picture/123 HTTP/1.1\r\nHost: localhost\r\n\r\n")
        self.assertTrue(text.startswith("GET "))
        self.assertEqual(parts, ["GET", "/picture/123", "HTTP/1.1"])
        self.assertEqual(safety.decode_http_request(b""), ("", []))
        _, bad_parts = safety.decode_http_request(b"\xff\xfe")
        self.assertEqual(len(bad_parts), 1)


if __name__ == "__main__":
    unittest.main()
