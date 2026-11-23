"""Feature flags and CoreELEC tuning defaults for YoEmby.

All optimizations can be disabled globally via ``ENABLED = False`` or
individually via ``special://profile/addon_data/plugin.service.emby-next-gen/ce_opt.json``
to seamlessly fall back to upstream 12.4.24 behavior.
"""

import json
import os

# Master switch for all CE optimizations
ENABLED = True

# Database tuning & extra indexes
DB_RW_CACHE_KB = 32768
EXTRA_EMBY_INDEXES = True

# Webservice worker pool floor
WEBSERVICE_MIN_WORKERS = 10

# Artwork 307 redirect optimization (tag + sensible sizing/quality)
PICTURE_REDIRECT_OPT = True
PICTURE_RESIZE_ENABLED = True
PICTURE_QUALITY = 85
PICTURE_MAX_WIDTHS = {
    "Primary": 600,
    "Thumb": 640,
    "Logo": 800,
    "Art": 800,
    "Banner": 1000,
    "Disc": 600,
    "Backdrop": 1920,
    "Chapter": 480,
}

# Concurrent artwork pre-caching
ARTWORK_CACHE_CONCURRENT = True
ARTWORK_CACHE_WORKERS = 6
ARTWORK_CACHE_TIMEOUT = 15
ARTWORK_CACHE_PROGRESS_INTERVAL = 0.25

# HTTP STRM fast path (YoLink / LAN 302 gateways)
STRM_FAST_PATH = True
STRM_SKIP_REMOTE_HEAD = True
STRM_LAN_DIRECT_REDIRECT = True

_OVERRIDE_LOADED = False


def _default_override_path():
    try:
        import xbmcvfs  # pylint: disable=import-outside-toplevel
        return xbmcvfs.translatePath(
            "special://profile/addon_data/plugin.service.emby-next-gen/ce_opt.json"
        )
    except Exception:
        return ""


def load_overrides(config_path=None):
    """Load optional JSON overrides into module-level settings.

    Unknown keys or mismatched types are ignored so a malformed config file
    can never crash the addon.
    """
    global _OVERRIDE_LOADED  # pylint: disable=global-statement
    path = config_path if config_path is not None else _default_override_path()
    _OVERRIDE_LOADED = True

    if not path or not os.path.isfile(path):
        return False

    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return False

    if not isinstance(data, dict):
        return False

    module_globals = globals()
    applied = False
    for key, value in data.items():
        if not key.isupper() or key not in module_globals:
            continue
        current = module_globals[key]
        if isinstance(current, bool):
            if isinstance(value, bool):
                module_globals[key] = value
                applied = True
        elif isinstance(current, int):
            if isinstance(value, int) and not isinstance(value, bool):
                module_globals[key] = value
                applied = True
        elif isinstance(current, float):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                module_globals[key] = float(value)
                applied = True
        elif isinstance(current, dict):
            if isinstance(value, dict):
                merged = current.copy()
                merged.update(value)
                module_globals[key] = merged
                applied = True

    return applied


def is_enabled(flag_name):
    """Return True iff master switch and the named boolean flag are enabled."""
    if not _OVERRIDE_LOADED:
        load_overrides()
    return bool(ENABLED and globals().get(flag_name, False))


def get_value(name, default=None):
    """Return a config value, respecting master switch override loading."""
    if not _OVERRIDE_LOADED:
        load_overrides()
    return globals().get(name, default)
