"""Artwork URL sizing/tagging, image metadata parsing, and concurrent pre-caching."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import http.client
import os
import ssl
import struct
import threading
import time
from urllib.parse import unquote, urlencode, urlsplit

from ce_opt import config

EMBY_ARTWORK_IDS = {
    "p": "Primary",
    "a": "Art",
    "b": "Banner",
    "d": "Disc",
    "l": "Logo",
    "t": "Thumb",
    "B": "Backdrop",
    "c": "Chapter",
}

# Image types where transparency (PNG) is common; avoid forcing JPEG quality param
_ALPHA_IMAGE_TYPES = frozenset(("Logo", "Art", "Disc"))

# JPEG Start-Of-Frame markers that actually contain width/height
# (Excludes 0xC4 DHT, 0xC8 JPG ext, 0xCC DAC)
_JPEG_SOF_MARKERS = frozenset(
    (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF)
)


def _build_crc32_mpeg2_table():
    table = []
    for byte in range(256):
        crc = byte << 24
        for _ in range(8):
            if crc & 0x80000000:
                crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF
            else:
                crc = (crc << 1) & 0xFFFFFFFF
        table.append(crc)
    return tuple(table)


_CRC32_MPEG2_TABLE = _build_crc32_mpeg2_table()


def fast_kodi_hash(path):
    """256-entry lookup-table CRC-32/MPEG-2 matching Kodi & upstream ``utils.kodi_hash``."""
    crc = 0xFFFFFFFF
    table = _CRC32_MPEG2_TABLE
    for byte in path.lower().encode("utf-8"):
        crc = ((crc << 8) & 0xFFFFFFFF) ^ table[((crc >> 24) ^ byte) & 0xFF]
    return f"{crc:08x}"


def _limitation_percent_from_utils(utils_mod, image_type):
    attr_map = {
        "Primary": "ArtworkLimitationPrimary",
        "Art": "ArtworkLimitationArt",
        "Banner": "ArtworkLimitationBanner",
        "Disc": "ArtworkLimitationDisc",
        "Logo": "ArtworkLimitationLogo",
        "Thumb": "ArtworkLimitationThumb",
        "Backdrop": "ArtworkLimitationBackdrop",
        "Chapter": "ArtworkLimitationChapter",
    }
    attr = attr_map.get(image_type)
    if not attr or utils_mod is None:
        return None
    try:
        return int(getattr(utils_mod, attr, 100))
    except Exception:
        return None


def build_picture_query_params(
    image_type,
    image_tag="",
    enable_cover_art=False,
    artwork_limitations=False,
    screen_resolution=(1920, 1080),
    limitation_percent=None,
    compress_art=False,
    compress_art_level=100,
):
    """Build Emby image query parameters with Tag, optimal sizing, and quality."""
    params = {
        "EnableImageEnhancers": "True" if enable_cover_art else "False",
    }

    if not config.is_enabled("PICTURE_REDIRECT_OPT"):
        return params

    if image_tag and str(image_tag).lower() != "none":
        params["tag"] = str(image_tag)

    if artwork_limitations and limitation_percent:
        width = max(1, int(screen_resolution[0] * int(limitation_percent) / 100))
        height = max(1, int(screen_resolution[1] * int(limitation_percent) / 100))
        params["maxWidth"] = width
        params["maxHeight"] = height
    elif config.is_enabled("PICTURE_RESIZE_ENABLED"):
        max_widths = config.get_value("PICTURE_MAX_WIDTHS", {})
        max_width = max_widths.get(image_type)
        if max_width and int(max_width) > 0:
            params["maxWidth"] = int(max_width)

    if compress_art:
        params["quality"] = int(compress_art_level)
    elif config.is_enabled("PICTURE_RESIZE_ENABLED") and image_type not in _ALPHA_IMAGE_TYPES:
        quality = int(config.get_value("PICTURE_QUALITY", 85))
        if 1 <= quality <= 100:
            params["quality"] = quality

    return params


def build_picture_redirect_url(
    server_url,
    access_token,
    emby_id,
    image_type,
    image_index,
    image_tag="",
    enable_cover_art=False,
    artwork_limitations=False,
    screen_resolution=(1920, 1080),
    limitation_percent=None,
    compress_art=False,
    compress_art_level=100,
):
    """Construct the full Emby image URL for 307 redirect or direct fetch."""
    base = f"{server_url.rstrip('/')}/emby/Items/{emby_id}/Images/{image_type}/{image_index}"
    params = {"api_key": access_token}
    params.update(
        build_picture_query_params(
            image_type=image_type,
            image_tag=image_tag,
            enable_cover_art=enable_cover_art,
            artwork_limitations=artwork_limitations,
            screen_resolution=screen_resolution,
            limitation_percent=limitation_percent,
            compress_art=compress_art,
            compress_art_level=compress_art_level,
        )
    )
    return f"{base}?{urlencode(params)}"


def build_picture_redirect_from_metadata(meta_data, server_data, utils_mod):
    """Convenience adapter called from hooks/webservice.py."""
    image_type = meta_data["ImageType"]
    return build_picture_redirect_url(
        server_url=server_data["ServerUrl"],
        access_token=server_data["AccessToken"],
        emby_id=meta_data["EmbyId"],
        image_type=image_type,
        image_index=meta_data["ImageIndex"],
        image_tag=meta_data.get("ImageTag", ""),
        enable_cover_art=bool(getattr(utils_mod, "enableCoverArt", False)),
        artwork_limitations=bool(getattr(utils_mod, "ArtworkLimitations", False)),
        screen_resolution=getattr(utils_mod, "ScreenResolution", (1920, 1080)),
        limitation_percent=_limitation_percent_from_utils(utils_mod, image_type),
        compress_art=bool(getattr(utils_mod, "compressArt", False)),
        compress_art_level=getattr(utils_mod, "compressArtLevel", 100),
    )


def parse_image_metadata(binary_data):
    """Extract (width, height, format) from JPEG, PNG, WebP, or GIF bytes.

    Fixes upstream's JPEG marker bug where ``marker >> 4 == 12`` misidentified
    DHT (0xC4), JPG ext (0xC8), and DAC (0xCC) segments as Start-Of-Frame.
    """
    if not binary_data:
        return 0, 0, ""

    size = len(binary_data)
    if size < 10:
        return 0, 0, ""

    # PNG
    if size >= 24 and binary_data[:8] == b"\x89PNG\r\n\x1a\n":
        width, height = struct.unpack(">II", binary_data[16:24])
        return width, height, "png"

    # JPEG
    if binary_data[0] == 0xFF and binary_data[1] == 0xD8:
        pos = 2
        while pos < size:
            # Skip any fill 0xFF bytes
            while pos < size and binary_data[pos] != 0xFF:
                pos += 1
            while pos < size and binary_data[pos] == 0xFF:
                pos += 1
            if pos >= size:
                break

            marker = binary_data[pos]
            pos += 1

            # Standalone markers without length payload
            if marker == 0xD9 or marker == 0xDA:  # EOI or SOS
                break
            if marker == 0x01 or (0xD0 <= marker <= 0xD8):
                continue

            if pos + 2 > size:
                break

            seg_len = (binary_data[pos] << 8) | binary_data[pos + 1]
            if seg_len < 2 or pos + seg_len > size:
                break

            if marker in _JPEG_SOF_MARKERS:
                if pos + 7 <= size:
                    height, width = struct.unpack(">HH", binary_data[pos + 3 : pos + 7])
                    return width, height, "jpg"
                break

            pos += seg_len

        return 0, 0, "jpg"

    # WebP (RIFF....WEBP)
    if size >= 30 and binary_data[:4] == b"RIFF" and binary_data[8:12] == b"WEBP":
        chunk = binary_data[12:16]
        if chunk == b"VP8 ":
            if binary_data[23:26] == b"\x9d\x01\x2a":
                raw_w, raw_h = struct.unpack("<HH", binary_data[26:30])
                return raw_w & 0x3FFF, raw_h & 0x3FFF, "webp"
        elif chunk == b"VP8L":
            if binary_data[20] == 0x2F:
                bits = struct.unpack("<I", binary_data[21:25])[0]
                width = (bits & 0x3FFF) + 1
                height = ((bits >> 14) & 0x3FFF) + 1
                return width, height, "webp"
        elif chunk == b"VP8X":
            width = 1 + (binary_data[24] | (binary_data[25] << 8) | (binary_data[26] << 16))
            height = 1 + (binary_data[27] | (binary_data[28] << 8) | (binary_data[29] << 16))
            return width, height, "webp"
        return 0, 0, "webp"

    # GIF
    if binary_data[:6] in (b"GIF87a", b"GIF89a"):
        width, height = struct.unpack("<HH", binary_data[6:10])
        return width, height, "gif"

    return 0, 0, ""


class _ThreadLocalHttpPool:
    """Persistent per-thread HTTP/HTTPS keep-alive connection pool."""

    def __init__(self, timeout=15, ssl_verify=False):
        self._timeout = timeout
        self._ssl_verify = ssl_verify
        self._local = threading.local()
        self._lock = threading.Lock()
        self._all_conns = []

    def _create_conn(self, scheme, host, port):
        if scheme == "https":
            ctx = ssl.create_default_context() if self._ssl_verify else ssl._create_unverified_context()
            conn = http.client.HTTPSConnection(host, port, timeout=self._timeout, context=ctx)
        else:
            conn = http.client.HTTPConnection(host, port, timeout=self._timeout)
        with self._lock:
            self._all_conns.append(conn)
        return conn

    def _get_conn(self, key):
        conns = getattr(self._local, "conns", None)
        if conns is None:
            conns = {}
            self._local.conns = conns
        conn = conns.get(key)
        if conn is None:
            conn = self._create_conn(*key)
            conns[key] = conn
        return conn

    def _reset_conn(self, key):
        conns = getattr(self._local, "conns", None)
        if conns and key in conns:
            try:
                conns[key].close()
            except Exception:
                pass
            del conns[key]

    def get_bytes(self, url):
        parsed = urlsplit(url)
        scheme = parsed.scheme.lower()
        host = parsed.hostname
        port = parsed.port or (443 if scheme == "https" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        key = (scheme, host, port)

        for attempt in range(2):
            conn = self._get_conn(key)
            try:
                conn.request("GET", path, headers={"Connection": "keep-alive"})
                resp = conn.getresponse()
                body = resp.read()
                if resp.status == 200:
                    return body
                if resp.status in (301, 302, 303, 307, 308):
                    location = resp.getheader("Location")
                    if location and attempt == 0:
                        return self.get_bytes(location)
                return b""
            except Exception:
                self._reset_conn(key)
                if attempt == 1:
                    return b""
        return b""

    def close_all(self):
        with self._lock:
            for conn in self._all_conns:
                try:
                    conn.close()
                except Exception:
                    pass
            self._all_conns.clear()


def _parse_artwork_entry(raw_url, texture_version, image_url_decode_fn):
    """Parse a Kodi artwork URL into normalized cache task fields, or None."""
    if not raw_url:
        return None

    has_image_prefix = raw_url.startswith("image://")
    if has_image_prefix:
        if texture_version <= 13:
            cache_path = raw_url
        else:
            cache_path = f"{raw_url.rsplit('/', 1)[0]}/".lower()
        http_path = image_url_decode_fn(raw_url, True)
    else:
        cache_path = raw_url
        http_path = raw_url

    folder = http_path.split("/")
    data = http_path.replace("|redirect-limit=1000&failonerror=false", "")
    data = data[data.rfind("/") + 1 :].split("-")

    if len(data) < 5 or len(folder) < 5:
        return None

    image_type = EMBY_ARTWORK_IDS.get(data[3])
    if not image_type:
        return None

    overlay_text = unquote("-".join(data[5:])) if len(data) > 5 else ""
    return {
        "raw_url": raw_url,
        "cache_path": cache_path,
        "has_image_prefix": has_image_prefix,
        "server_id": folder[4],
        "emby_id": data[1],
        "image_index": data[2],
        "image_type": image_type,
        "image_tag": data[4],
        "overlay_text": overlay_text,
    }


def cache_all_entries_concurrent(urls, worker_name, utils_mod, add_textures_fn, xbmcvfs_mod=None, xbmc_mod=None):
    """Concurrently pre-cache artwork into Kodi Thumbnails/ and Textures13.db."""
    total_input = len(urls)
    if total_input == 0:
        return 0

    texture_version = utils_mod.DatabaseFiles.get("texture-version", 13)
    thumb_root_vfs = utils_mod.FolderUserdataThumbnails
    local_thumb_root = ""
    if xbmcvfs_mod is not None:
        try:
            translated = xbmcvfs_mod.translatePath(thumb_root_vfs)
            if translated and os.path.isdir(translated):
                local_thumb_root = translated
        except Exception:
            local_thumb_root = ""
    elif os.path.isdir(thumb_root_vfs):
        local_thumb_root = thumb_root_vfs

    # Deduplicate and filter already-cached entries first
    tasks = []
    seen_cache_paths = set()
    created_dirs = set()
    skip_noimage = config.is_enabled("ARTWORK_CACHE_SKIP_NOIMAGE")
    progress_interval = float(config.get_value("ARTWORK_CACHE_PROGRESS_INTERVAL", 0.25))
    last_scan_progress = 0.0

    for idx_in, url_row in enumerate(urls):
        if getattr(utils_mod, "TextureCacheCancel", False) or getattr(utils_mod, "SystemShutdown", False):
            return 0
        raw_url = url_row[0] if isinstance(url_row, (list, tuple)) else url_row
        entry = _parse_artwork_entry(raw_url, texture_version, utils_mod.image_url_decode)
        if not entry:
            continue

        if skip_noimage and entry["image_tag"].lower() == "noimage":
            continue

        cache_path = entry["cache_path"]
        if cache_path in seen_cache_paths:
            continue
        seen_cache_paths.add(cache_path)

        server_id = entry["server_id"]
        if server_id not in utils_mod.EmbyServers:
            continue

        img_hash = utils_mod.kodi_hash(cache_path)
        subdir = img_hash[0]

        if local_thumb_root:
            base_local = os.path.join(local_thumb_root, subdir, img_hash)
            if (
                os.path.exists(f"{base_local}.jpg")
                or os.path.exists(f"{base_local}.png")
                or os.path.exists(f"{base_local}.webp")
            ):
                continue
        elif xbmcvfs_mod is not None:
            base_vfs = f"{thumb_root_vfs}{subdir}/{img_hash}"
            if (
                xbmcvfs_mod.exists(f"{base_vfs}.jpg")
                or xbmcvfs_mod.exists(f"{base_vfs}.png")
                or xbmcvfs_mod.exists(f"{base_vfs}.webp")
            ):
                continue

        entry["hash"] = img_hash
        entry["subdir"] = subdir
        tasks.append(entry)

        if idx_in % 256 == 0:
            now = time.monotonic()
            if now - last_scan_progress >= progress_interval:
                last_scan_progress = now
                utils_mod.update_ProgressBar(
                    worker_name,
                    0,
                    utils_mod.Translate(33199),
                    f"{utils_mod.Translate(33045)}: {len(tasks)} / {total_input}",
                )

    if not tasks:
        return 0

    # Pre-create required hex subdirectories once
    for subdir in {task["subdir"] for task in tasks}:
        if subdir in created_dirs:
            continue
        if local_thumb_root:
            os.makedirs(os.path.join(local_thumb_root, subdir), exist_ok=True)
        else:
            utils_mod.mkDir(f"{thumb_root_vfs}{subdir}")
        created_dirs.add(subdir)

    max_workers = max(1, int(config.get_value("ARTWORK_CACHE_WORKERS", 6)))
    timeout = max(3, int(config.get_value("ARTWORK_CACHE_TIMEOUT", 15)))
    pool = _ThreadLocalHttpPool(timeout=timeout, ssl_verify=bool(getattr(utils_mod, "sslverify", False)))
    # Serialize CPU-heavy Pillow overlay rendering so Kodi's UI thread never starves on GIL
    overlay_lock = threading.Semaphore(1)

    def _fetch_and_write(task):
        if getattr(utils_mod, "TextureCacheCancel", False) or getattr(utils_mod, "SystemShutdown", False):
            return None

        if task["overlay_text"]:
            with overlay_lock:
                if getattr(utils_mod, "TextureCacheCancel", False) or getattr(utils_mod, "SystemShutdown", False):
                    return None
                image_binary, _, _ = utils_mod.image_overlay(
                    task["image_tag"],
                    task["server_id"],
                    task["emby_id"],
                    task["image_type"],
                    task["image_index"],
                    task["overlay_text"],
                )
            time.sleep(0.005)
        else:
            server_data = utils_mod.EmbyServers[task["server_id"]].ServerData
            url = build_picture_redirect_url(
                server_url=server_data["ServerUrl"],
                access_token=server_data["AccessToken"],
                emby_id=task["emby_id"],
                image_type=task["image_type"],
                image_index=task["image_index"],
                image_tag=task["image_tag"],
                enable_cover_art=bool(getattr(utils_mod, "enableCoverArt", False)),
                artwork_limitations=bool(getattr(utils_mod, "ArtworkLimitations", False)),
                screen_resolution=getattr(utils_mod, "ScreenResolution", (1920, 1080)),
                limitation_percent=_limitation_percent_from_utils(utils_mod, task["image_type"]),
                compress_art=bool(getattr(utils_mod, "compressArt", False)),
                compress_art_level=getattr(utils_mod, "compressArtLevel", 100),
            )
            image_binary = pool.get_bytes(url)

        if not image_binary:
            return None

        width, height, image_format = parse_image_metadata(image_binary)
        if width == 0 or not image_format:
            return None

        cached_url = f"{task['subdir']}/{task['hash']}.{image_format}"
        vfs_path = f"{thumb_root_vfs}{cached_url}"

        if local_thumb_root:
            local_path = os.path.join(local_thumb_root, task["subdir"], f"{task['hash']}.{image_format}")
            with open(local_path, "wb") as handle:
                handle.write(image_binary)
        else:
            utils_mod.writeFile(vfs_path, image_binary)

        size = len(image_binary)
        return {
            "Url": task["cache_path"],
            "Width": width,
            "Height": height,
            "Size": size,
            "Extension": image_format,
            "ImageHash": "" if task["has_image_prefix"] else f"d0s{size}",
            "Path": vfs_path,
            "cachedUrl": cached_url,
            "EmbyID": task["emby_id"],
        }

    batch = []
    cached_count = 0
    done_count = 0
    total_tasks = len(tasks)
    last_progress = 0.0
    chunk_size = 500

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for offset in range(0, total_tasks, chunk_size):
                if getattr(utils_mod, "TextureCacheCancel", False) or getattr(utils_mod, "SystemShutdown", False):
                    break

                if utils_mod.getFreeSpace(thumb_root_vfs) < 2097152:
                    utils_mod.Dialog.notification(
                        heading=utils_mod.addon_name,
                        message=utils_mod.Translate(33429),
                        icon=utils_mod.icon,
                        time=utils_mod.displayMessage,
                        sound=True,
                    )
                    if xbmc_mod is not None:
                        xbmc_mod.log("EMBY.helper.artworkcache: Artwork cache: running out of space", 2)
                    break

                chunk = tasks[offset : offset + chunk_size]
                futures = [executor.submit(_fetch_and_write, task) for task in chunk]

                for fut in as_completed(futures):
                    if getattr(utils_mod, "TextureCacheCancel", False) or getattr(utils_mod, "SystemShutdown", False):
                        for pending in futures:
                            pending.cancel()
                        break

                    done_count += 1
                    item = None
                    try:
                        item = fut.result()
                    except Exception:
                        item = None

                    if item:
                        batch.append(item)
                        cached_count += 1

                    now = time.monotonic()
                    if now - last_progress >= progress_interval or done_count == total_tasks:
                        last_progress = now
                        emby_id = item["EmbyID"] if item else ""
                        utils_mod.update_ProgressBar(
                            worker_name,
                            done_count / total_tasks * 100,
                            utils_mod.Translate(33199),
                            f"{utils_mod.Translate(33045)}: {emby_id} / {done_count}",
                        )

                if batch:
                    add_textures_fn(batch)
                    batch.clear()
    finally:
        pool.close_all()
        if batch:
            add_textures_fn(batch)

    return cached_count
