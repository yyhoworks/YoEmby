"""Library scanning and incremental sync accelerators for CoreELEC."""

import time

from ce_opt import config

_PROGRESS_STATE = {}


def should_enqueue_theme(utils_mod):
    """Return False when theme audio/video are both disabled in addon settings."""
    if not config.is_enabled("SYNC_SKIP_DISABLED_THEMES"):
        return True
    return bool(
        getattr(utils_mod, "theme_enable_audio", False)
        or getattr(utils_mod, "theme_enable_video", False)
    )


def should_update_progress(task_id, value, header, now=None):
    """Throttle frequent DialogProgressBG.update() calls to reduce GUI/GIL overhead.

    Always allows 0%, 100%, or header transitions through immediately.
    """
    if not config.is_enabled("SYNC_THROTTLE_PROGRESS"):
        return True

    ts = time.monotonic() if now is None else float(now)
    interval = float(config.get_value("SYNC_PROGRESS_INTERVAL", 0.25))
    int_val = int(value)
    prev = _PROGRESS_STATE.get(task_id)

    if (
        prev is None
        or int_val <= 0
        or int_val >= 100
        or prev[1] != header
        or (ts - prev[0]) >= interval
    ):
        _PROGRESS_STATE[task_id] = (ts, header)
        return True

    return False


def clear_progress_state(task_id):
    """Clean up throttle tracking when a progress bar closes."""
    _PROGRESS_STATE.pop(task_id, None)


def clear_all_progress_state():
    """Clean up all throttle tracking when all progress bars close."""
    _PROGRESS_STATE.clear()


def batch_set_links(
    kodi_item_id,
    sqls,
    kodi_type,
    meta_items,
    emby_table,
    link_table,
    id_col,
    include_role_order=False,
    xbmc_mod=None,
):
    """Replace N+1 EmbyDB SELECT + single-row VideoDB INSERT with batched SQL.

    Preserves exact upstream link table semantics, ordering, and missing-item logs.
    """
    if not meta_items:
        return 0

    emby_cursor = sqls["emby"].cursor
    video_cursor = sqls["video"].cursor

    # Collect unique EmbyIds preserving order
    unique_ids = []
    seen_ids = set()
    for item in meta_items:
        raw_id = item.get("Id")
        if raw_id is None:
            continue
        key = str(raw_id)
        if key not in seen_ids:
            seen_ids.add(key)
            unique_ids.append(raw_id)

    if not unique_ids:
        return 0

    emby_to_kodi = {}
    chunk_size = 500
    for offset in range(0, len(unique_ids), chunk_size):
        chunk = unique_ids[offset : offset + chunk_size]
        placeholders = ",".join("?" for _ in chunk)
        emby_cursor.execute(
            f"SELECT EmbyId, KodiId FROM {emby_table} WHERE EmbyId IN ({placeholders})",
            chunk,
        )
        for emby_id, kodi_id in emby_cursor.fetchall():
            emby_to_kodi[str(emby_id)] = kodi_id

    rows = []
    for order, item in enumerate(meta_items):
        raw_id = item.get("Id")
        kodi_id = emby_to_kodi.get(str(raw_id)) if raw_id is not None else None
        if kodi_id is None:
            if xbmc_mod is not None:
                xbmc_mod.log(f"EMBY.core.common: batch_set_links ({emby_table}) missing: {item}", 3)
            continue

        if include_role_order:
            rows.append((kodi_id, kodi_item_id, kodi_type, item.get("Role", ""), order))
        else:
            rows.append((kodi_id, kodi_item_id, kodi_type))

    if not rows:
        return 0

    if include_role_order:
        video_cursor.executemany(
            f"INSERT OR REPLACE INTO {link_table}({id_col}, media_id, media_type, role, cast_order) VALUES (?, ?, ?, ?, ?)",
            rows,
        )
    else:
        video_cursor.executemany(
            f"INSERT OR REPLACE INTO {link_table}({id_col}, media_id, media_type) VALUES (?, ?, ?)",
            rows,
        )

    return len(rows)


def dedup_person_artwork(kodi_artwork):
    """Trim redundant poster/landscape copies of an actor's Primary thumb.

    Kodi and YoPlayer read actor thumbnails from ``thumb`` (and ``actor.art_urls``).
    Dropping duplicate ``poster`` and ``landscape`` entries that point to the exact
    same URL as ``thumb`` avoids ~77k bloated rows in MyVideos131.db's ``art`` table.
    """
    if not config.is_enabled("SYNC_DEDUP_PERSON_ART") or not isinstance(kodi_artwork, dict):
        return kodi_artwork

    thumb_url = kodi_artwork.get("thumb")
    if not thumb_url:
        return kodi_artwork

    cleaned = kodi_artwork.copy()
    if cleaned.get("poster") == thumb_url:
        cleaned["poster"] = None
    if cleaned.get("landscape") == thumb_url:
        cleaned["landscape"] = None
    return cleaned


def should_skip_noimage_chapter(marker_label, has_image_tag):
    """Return True to skip generic 5-min auto chapters that have no thumbnail image.

    NEVER skips IntroStart / IntroEnd / CreditsStart / Title Sequence markers
    (which set ``marker_label``) and NEVER skips real chapters with ``ImageTag``.
    """
    if not config.is_enabled("SYNC_SKIP_NOIMAGE_CHAPTERS"):
        return False
    return (not marker_label) and (not has_image_tag)


def get_person_paging(configured_paging):
    """Cap Person API page size to avoid single-shot multi-MB JSON memory spikes."""
    try:
        paging = int(configured_paging)
    except Exception:
        paging = 5000

    if not config.is_enabled("SYNC_PERSON_PAGING_OPT"):
        return paging

    cap = max(500, int(config.get_value("SYNC_PERSON_PAGING_CAP", 5000)))
    return min(paging, cap) if paging > 0 else cap


def is_companion_queue_empty(result):
    """Return True when Emby Kodi Companion explicitly reports zero changes."""
    if not config.is_enabled("SYNC_TRUST_COMPANION_EMPTY"):
        return False
    if not isinstance(result, dict):
        return False
    required_keys = ("ItemsAdded", "ItemsRemoved", "ItemsUpdated", "UserDataChanged")
    if not all(key in result and isinstance(result[key], list) for key in required_keys):
        return False
    return all(len(result[key]) == 0 for key in required_keys)


def should_query_start_sync_type(companion_empty, emby_type):
    """When Companion reports empty, only query types Companion doesn't track."""
    if not companion_empty:
        return True
    allowed = config.get_value("SYNC_COMPANION_EMPTY_TYPES", ("Person", "BoxSet"))
    return emby_type in allowed
