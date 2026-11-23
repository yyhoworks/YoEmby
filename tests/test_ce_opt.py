"""Unit tests for YoEmby ce_opt modules and upstream bug fixes."""

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sqlite3
import struct
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from urllib.parse import parse_qs, unquote, urlsplit

ADDON_ROOT = Path(__file__).resolve().parent.parent / "plugin.service.emby-next-gen"
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

from ce_opt import artwork, config, db_indexes, strm  # noqa: E402


def _make_png(width, height):
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr + b"\x00\x00\x00\x00"


def _make_jpeg_with_dht_before_sof0(width, height):
    # SOI + APP0 + DHT (0xC4, which tricked upstream marker >> 4 == 12) + SOF0 (0xC0) + EOI
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    dht_payload = b"\x00" * 10
    dht = b"\xff\xc4" + struct.pack(">H", len(dht_payload) + 2) + dht_payload
    sof0_payload = struct.pack(">BHHB", 8, height, width, 3) + b"\x01\x11\x00\x02\x11\x01\x03\x11\x01"
    sof0 = b"\xff\xc0" + struct.pack(">H", len(sof0_payload) + 2) + sof0_payload
    return b"\xff\xd8" + app0 + dht + sof0 + b"\xff\xd9"


def _make_webp_vp8(width, height):
    body = b"\x00\x00\x00\x9d\x01\x2a" + struct.pack("<HH", width, height) + b"\x00\x00"
    return b"RIFF" + struct.pack("<I", 4 + 8 + len(body)) + b"WEBP" + b"VP8 " + struct.pack("<I", len(body)) + body


def _make_webp_vp8l(width, height):
    bits = ((width - 1) & 0x3FFF) | (((height - 1) & 0x3FFF) << 14)
    body = b"\x2f" + struct.pack("<I", bits) + b"\x00\x00\x00\x00\x00"
    return b"RIFF" + struct.pack("<I", 4 + 8 + len(body)) + b"WEBP" + b"VP8L" + struct.pack("<I", len(body)) + body


def _make_webp_vp8x(width, height):
    w = width - 1
    h = height - 1
    body = (
        b"\x00\x00\x00\x00"
        + bytes((w & 0xFF, (w >> 8) & 0xFF, (w >> 16) & 0xFF))
        + bytes((h & 0xFF, (h >> 8) & 0xFF, (h >> 16) & 0xFF))
    )
    return b"RIFF" + struct.pack("<I", 4 + 8 + len(body)) + b"WEBP" + b"VP8X" + struct.pack("<I", len(body)) + body


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self._orig_enabled = config.ENABLED
        self._orig_quality = config.PICTURE_QUALITY
        self._orig_widths = config.PICTURE_MAX_WIDTHS.copy()
        self._orig_loaded = config._OVERRIDE_LOADED

    def tearDown(self):
        config.ENABLED = self._orig_enabled
        config.PICTURE_QUALITY = self._orig_quality
        config.PICTURE_MAX_WIDTHS = self._orig_widths
        config._OVERRIDE_LOADED = self._orig_loaded

    def test_load_overrides_applies_valid_keys_and_ignores_invalid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "ce_opt.json")
            with open(cfg_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "PICTURE_QUALITY": 78,
                        "PICTURE_MAX_WIDTHS": {"Primary": 500},
                        "ENABLED": "not_a_bool",
                        "UNKNOWN_KEY": 123,
                    },
                    handle,
                )

            applied = config.load_overrides(cfg_path)
            self.assertTrue(applied)
            self.assertEqual(config.PICTURE_QUALITY, 78)
            self.assertEqual(config.PICTURE_MAX_WIDTHS["Primary"], 500)
            self.assertEqual(config.PICTURE_MAX_WIDTHS["Backdrop"], 1920)
            self.assertTrue(config.ENABLED)

    def test_master_switch_disables_all_flags(self):
        config._OVERRIDE_LOADED = True
        config.ENABLED = False
        self.assertFalse(config.is_enabled("EXTRA_EMBY_INDEXES"))
        self.assertFalse(config.is_enabled("PICTURE_REDIRECT_OPT"))
        self.assertFalse(config.is_enabled("STRM_FAST_PATH"))


class DbIndexesTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.cursor = self.conn.cursor()
        self.cursor.execute("CREATE TABLE Movie (EmbyId INTEGER PRIMARY KEY, KodiId INTEGER, KodiFileId INTEGER)")
        self.cursor.execute("CREATE TABLE Series (EmbyId INTEGER PRIMARY KEY, KodiId INTEGER)")
        self.cursor.execute("CREATE TABLE Season (EmbyId INTEGER PRIMARY KEY, KodiId INTEGER)")
        self.cursor.execute("CREATE TABLE Episode (EmbyId INTEGER PRIMARY KEY, KodiId INTEGER, KodiFileId INTEGER)")
        for i in range(1, 50):
            self.cursor.execute("INSERT INTO Episode VALUES (?, ?, ?)", (i + 1000, i, i + 5000))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_ensure_and_drop_kodi_id_indexes(self):
        created = db_indexes.ensure_kodi_id_indexes(self.cursor)
        self.assertEqual(created, len(db_indexes.EXTRA_INDEXES))

        # Idempotent second call
        self.assertEqual(db_indexes.ensure_kodi_id_indexes(self.cursor), 0)

        # Query plan must use idx_Episode_KodiId instead of full table scan
        self.cursor.execute("EXPLAIN QUERY PLAN SELECT EmbyId, KodiFileId FROM Episode WHERE KodiId = 25")
        plan = " ".join(str(row) for row in self.cursor.fetchall())
        self.assertIn("idx_Episode_KodiId", plan)

        db_indexes.drop_kodi_id_indexes(self.cursor)
        self.cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_Episode_KodiId'")
        self.assertIsNone(self.cursor.fetchone())


class VideoDbBookmarkFixTest(unittest.TestCase):
    def test_resume_update_preserves_chapter_bookmarks(self):
        video_db_src = (ADDON_ROOT / "database" / "video_db.py").read_text(encoding="utf-8")
        self.assertIn(
            'UPDATE bookmark SET timeInSeconds = ?, totalTimeInSeconds = ? WHERE idFile = ? AND type = ?',
            video_db_src,
        )

        conn = sqlite3.connect(":memory:")
        cur = conn.cursor()
        cur.execute(
            "CREATE TABLE bookmark (idBookmark INTEGER PRIMARY KEY, idFile INTEGER, timeInSeconds REAL, totalTimeInSeconds REAL, thumbNailImage TEXT, player TEXT, type INTEGER)"
        )
        cur.execute("INSERT INTO bookmark VALUES (1, 10, 300.0, 3600.0, 'noimage', 'VideoPlayer', 0)")
        cur.execute("INSERT INTO bookmark VALUES (2, 10, 600.0, 3600.0, 'noimage', 'VideoPlayer', 0)")
        cur.execute("INSERT INTO bookmark VALUES (3, 10, 120.0, 3600.0, NULL, 'VideoPlayer', 1)")

        cur.execute(
            "UPDATE bookmark SET timeInSeconds = ?, totalTimeInSeconds = ? WHERE idFile = ? AND type = ?",
            (950.0, 3600.0, 10, "1"),
        )
        cur.execute("SELECT type, timeInSeconds FROM bookmark WHERE idFile = 10 ORDER BY idBookmark")
        rows = cur.fetchall()
        self.assertEqual(rows, [(0, 300.0), (0, 600.0), (1, 950.0)])
        conn.close()


class ArtworkTest(unittest.TestCase):
    def setUp(self):
        self._orig_enabled = config.ENABLED
        self._orig_redirect = config.PICTURE_REDIRECT_OPT
        config._OVERRIDE_LOADED = True
        config.ENABLED = True
        config.PICTURE_REDIRECT_OPT = True

    def tearDown(self):
        config.ENABLED = self._orig_enabled
        config.PICTURE_REDIRECT_OPT = self._orig_redirect

    def test_build_picture_redirect_url_primary_and_logo(self):
        url = artwork.build_picture_redirect_url(
            server_url="http://192.168.1.168:8096",
            access_token="dummy_token",
            emby_id="885750",
            image_type="Primary",
            image_index="0",
            image_tag="abc123",
            enable_cover_art=False,
        )
        parsed = urlsplit(url)
        qs = parse_qs(parsed.query)
        self.assertEqual(parsed.path, "/emby/Items/885750/Images/Primary/0")
        self.assertEqual(qs["tag"], ["abc123"])
        self.assertEqual(qs["maxWidth"], ["600"])
        self.assertEqual(qs["quality"], ["85"])
        self.assertEqual(qs["EnableImageEnhancers"], ["False"])

        logo_url = artwork.build_picture_redirect_url(
            server_url="http://192.168.1.168:8096",
            access_token="dummy_token",
            emby_id="885750",
            image_type="Logo",
            image_index="0",
            image_tag="None",
            enable_cover_art=True,
        )
        logo_qs = parse_qs(urlsplit(logo_url).query)
        self.assertNotIn("tag", logo_qs)
        self.assertEqual(logo_qs["maxWidth"], ["800"])
        self.assertNotIn("quality", logo_qs)
        self.assertEqual(logo_qs["EnableImageEnhancers"], ["True"])

    def test_build_picture_redirect_url_fallback_when_disabled(self):
        config.PICTURE_REDIRECT_OPT = False
        url = artwork.build_picture_redirect_url(
            server_url="http://192.168.1.168:8096",
            access_token="dummy_token",
            emby_id="885750",
            image_type="Primary",
            image_index="0",
            image_tag="abc123",
        )
        qs = parse_qs(urlsplit(url).query)
        self.assertNotIn("tag", qs)
        self.assertNotIn("maxWidth", qs)
        self.assertNotIn("quality", qs)

    def test_parse_image_metadata_formats(self):
        self.assertEqual(artwork.parse_image_metadata(_make_jpeg_with_dht_before_sof0(600, 900)), (600, 900, "jpg"))
        self.assertEqual(artwork.parse_image_metadata(_make_png(800, 310)), (800, 310, "png"))
        self.assertEqual(artwork.parse_image_metadata(_make_webp_vp8(640, 360)), (640, 360, "webp"))
        self.assertEqual(artwork.parse_image_metadata(_make_webp_vp8l(480, 720)), (480, 720, "webp"))
        self.assertEqual(artwork.parse_image_metadata(_make_webp_vp8x(1920, 1080)), (1920, 1080, "webp"))
        self.assertEqual(artwork.parse_image_metadata(b"short"), (0, 0, ""))

    def test_concurrent_artwork_cache(self):
        jpeg_bytes = _make_jpeg_with_dht_before_sof0(600, 900)
        png_bytes = _make_png(800, 250)
        request_count = {"n": 0}
        count_lock = threading.Lock()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                with count_lock:
                    request_count["n"] += 1
                body = png_bytes if "/Logo/" in self.path else jpeg_bytes
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):  # noqa: A002
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                added_batches = []
                utils_stub = SimpleNamespace(
                    DatabaseFiles={"texture-version": 13},
                    FolderUserdataThumbnails=tmpdir + os.sep,
                    TextureCacheCancel=False,
                    SystemShutdown=False,
                    sslverify=False,
                    enableCoverArt=False,
                    ArtworkLimitations=False,
                    ScreenResolution=(1920, 1080),
                    compressArt=False,
                    compressArtLevel=100,
                    addon_name="YoEmby",
                    icon="",
                    displayMessage=1000,
                    Dialog=SimpleNamespace(notification=lambda **kwargs: None),
                    EmbyServers={
                        "srv1": SimpleNamespace(
                            ServerData={"ServerUrl": f"http://127.0.0.1:{port}", "AccessToken": "tok"}
                        )
                    },
                    image_url_decode=lambda u, _=True: unquote(u[8:-1]) if u.startswith("image://") else u,
                    kodi_hash=lambda s: hashlib.md5(s.encode("utf-8")).hexdigest()[:8],
                    mkDir=lambda p: os.makedirs(p, exist_ok=True),
                    getFreeSpace=lambda _p: 9999999,
                    Translate=lambda code: str(code),
                    update_ProgressBar=lambda *args: None,
                )

                raw_urls = [
                    ("http://127.0.0.1:57342/picture/srv1/p-101-0-p-tag1",),
                    ("http://127.0.0.1:57342/picture/srv1/p-101-0-p-tag1",),  # duplicate
                    ("http://127.0.0.1:57342/picture/srv1/p-102-0-l-tag2",),
                ]

                cached = artwork.cache_all_entries_concurrent(
                    raw_urls,
                    "test_worker",
                    utils_stub,
                    lambda items: added_batches.extend(items),
                )
                self.assertEqual(cached, 2)
                self.assertEqual(request_count["n"], 2)
                self.assertEqual(len(added_batches), 2)
                formats = {item["EmbyID"]: (item["Width"], item["Height"], item["Extension"]) for item in added_batches}
                self.assertEqual(formats["101"], (600, 900, "jpg"))
                self.assertEqual(formats["102"], (800, 250, "png"))

                # Second run should skip all already-cached files with zero HTTP requests
                cached_again = artwork.cache_all_entries_concurrent(
                    raw_urls,
                    "test_worker",
                    utils_stub,
                    lambda items: added_batches.extend(items),
                )
                self.assertEqual(cached_again, 0)
                self.assertEqual(request_count["n"], 2)
        finally:
            server.shutdown()
            server.server_close()


class StrmFastPathTest(unittest.TestCase):
    def setUp(self):
        self._orig_enabled = config.ENABLED
        self._orig_fast = config.STRM_FAST_PATH
        self._orig_head = config.STRM_SKIP_REMOTE_HEAD
        self._orig_lan = config.STRM_LAN_DIRECT_REDIRECT
        config._OVERRIDE_LOADED = True
        config.ENABLED = True
        config.STRM_FAST_PATH = True
        config.STRM_SKIP_REMOTE_HEAD = True
        config.STRM_LAN_DIRECT_REDIRECT = True

    def tearDown(self):
        config.ENABLED = self._orig_enabled
        config.STRM_FAST_PATH = self._orig_fast
        config.STRM_SKIP_REMOTE_HEAD = self._orig_head
        config.STRM_LAN_DIRECT_REDIRECT = self._orig_lan

    def test_is_lan_http_url(self):
        self.assertTrue(strm.is_lan_http_url("http://192.168.1.168:8796/s/demo"))
        self.assertTrue(strm.is_lan_http_url("http://10.0.0.5:8080/video.mkv"))
        self.assertTrue(strm.is_lan_http_url("http://172.16.10.2/stream"))
        self.assertTrue(strm.is_lan_http_url("http://127.0.0.1:8796/stream"))
        self.assertTrue(strm.is_lan_http_url("http://nas.local:8796/stream"))
        self.assertFalse(strm.is_lan_http_url("https://cdn.example.com/movie.mkv"))
        self.assertFalse(strm.is_lan_http_url(r"\\192.168.1.168\sata\movie.mkv"))

    def test_skip_remote_head_and_direct_redirect(self):
        meta_http = {"isHttp": True}
        meta_local = {"isHttp": False}
        lan_src = {"Path": "http://192.168.1.168:8796/s/abc123", "IsRemote": True}
        pub_src = {"Path": "https://cdn.example.com/file.mkv", "IsRemote": True}

        self.assertTrue(strm.should_skip_remote_head(meta_http, lan_src, followhttp=False))
        self.assertTrue(strm.should_skip_remote_head(meta_http, pub_src, followhttp=False))
        self.assertFalse(strm.should_skip_remote_head(meta_local, lan_src, followhttp=False))

        # Direct 307 for LAN STRM gateway even when followhttp is False
        self.assertTrue(strm.should_direct_redirect_http(meta_http, lan_src, "videos/1/stream?static=true", False))
        # Public STRM still routes via Emby unless followhttp=True
        self.assertFalse(strm.should_direct_redirect_http(meta_http, pub_src, "videos/1/stream?static=true", False))
        self.assertTrue(strm.should_direct_redirect_http(meta_http, pub_src, "videos/1/stream?static=true", True))
        # Explicit HLS transcoding never bypasses Emby
        self.assertFalse(strm.should_direct_redirect_http(meta_http, lan_src, "videos/1/main.m3u8?VideoCodec=h264", False))

        # Disabled flag falls back to upstream
        config.STRM_FAST_PATH = False
        self.assertFalse(strm.should_skip_remote_head(meta_http, lan_src, followhttp=False))
        self.assertFalse(strm.should_direct_redirect_http(meta_http, lan_src, "videos/1/stream?static=true", False))


if __name__ == "__main__":
    unittest.main()
