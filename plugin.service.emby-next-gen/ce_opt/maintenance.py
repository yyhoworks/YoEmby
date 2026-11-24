"""YoEmby CoreELEC health diagnostics & user-confirmed maintenance actions.

All diagnostics are 100% read-only (`?mode=ro`). Destructive cleanup actions
(such as deleting `rollback/`) ALWAYS require explicit interactive user confirmation.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from . import config, db_opt, stream_heal, sync_fast


def _dir_size_and_count(path: str | Path) -> tuple[int, int]:
    if not path:
        return 0, 0
    p = Path(path)
    if not p.is_dir():
        return 0, 0
    total = 0
    count = 0
    for root, _dirs, files in os.walk(p):
        for fname in files:
            count += 1
            try:
                total += os.path.getsize(os.path.join(root, fname))
            except OSError:
                pass
    return total, count


def _file_size(path: str | Path) -> int:
    if not path:
        return 0
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _fmt_mb(num_bytes: int) -> str:
    if num_bytes >= 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"
    return f"{num_bytes / (1024 * 1024):.1f} MB"


def _connect_ro(path: str | Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def collect_health_report(
    emby_db_path: str | Path = "",
    video_db_path: str | Path = "",
    textures_db_path: str | Path = "",
    temp_dir: str | Path = "",
    rollback_dir: str | Path = "",
    thumbnails_dir: str | Path = "",
) -> dict[str, Any]:
    """Collect a structured, read-only health snapshot of YoEmby on CoreELEC."""
    report: dict[str, Any] = {
        "config": config.snapshot(),
        "runtime_stats": {
            **sync_fast.get_stats(),
            "strm_healed_session": stream_heal.get_healed_count(),
        },
        "storage": {},
        "emby_db": {},
        "video_db": {},
    }

    temp_sz, temp_cnt = _dir_size_and_count(temp_dir)
    rb_sz, rb_cnt = _dir_size_and_count(rollback_dir)
    thumb_sz, thumb_cnt = _dir_size_and_count(thumbnails_dir)
    report["storage"] = {
        "emby_db_bytes": _file_size(emby_db_path),
        "video_db_bytes": _file_size(video_db_path),
        "textures_db_bytes": _file_size(textures_db_path),
        "temp_bytes": temp_sz,
        "temp_files": temp_cnt,
        "rollback_bytes": rb_sz,
        "rollback_files": rb_cnt,
        "thumbnails_bytes": thumb_sz,
        "thumbnails_files": thumb_cnt,
    }

    if emby_db_path and os.path.isfile(emby_db_path):
        con = _connect_ro(emby_db_path)
        try:
            cur = con.cursor()
            ce_idxs = [
                r[0]
                for r in cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_ce_%'"
                ).fetchall()
            ]
            ms_total = cur.execute("SELECT COUNT(*) FROM MediaSources").fetchone()[0]
            ms_http = cur.execute("SELECT COUNT(*) FROM MediaSources WHERE Path LIKE 'http%'").fetchone()[0]
            ms_smb = cur.execute("SELECT COUNT(*) FROM MediaSources WHERE Path LIKE '\\%' OR Path LIKE 'smb://%'").fetchone()[0]
            vs_items = cur.execute("SELECT COUNT(DISTINCT EmbyId) FROM VideoStreams").fetchone()[0]
            ms_items = cur.execute("SELECT COUNT(DISTINCT EmbyId) FROM MediaSources").fetchone()[0]
            report["emby_db"] = {
                "ce_indexes_present": len(ce_idxs),
                "ce_indexes_expected": len(db_opt.EMBY_ADDITIVE_INDEXES),
                "mediasources_total": ms_total,
                "mediasources_http": ms_http,
                "mediasources_smb": ms_smb,
                "items_with_mediasources": ms_items,
                "items_missing_videostreams": max(0, ms_items - vs_items),
            }
        finally:
            con.close()

    if video_db_path and os.path.isfile(video_db_path):
        con = _connect_ro(video_db_path)
        try:
            cur = con.cursor()
            cols = {r[1] for r in cur.execute("PRAGMA table_info(streamdetails)").fetchall()}
            has_avdv = {"strHdrTypeAlt", "strDvProfile", "strAudioProfile"}.issubset(cols)
            mv_tot = cur.execute("SELECT COUNT(*) FROM movie").fetchone()[0]
            mv_sd = cur.execute(
                "SELECT COUNT(DISTINCT m.idFile) FROM movie m JOIN streamdetails s ON m.idFile=s.idFile"
            ).fetchone()[0]
            ep_tot = cur.execute("SELECT COUNT(*) FROM episode").fetchone()[0]
            ep_sd = cur.execute(
                "SELECT COUNT(DISTINCT e.idFile) FROM episode e JOIN streamdetails s ON e.idFile=s.idFile"
            ).fetchone()[0]
            bookmarks = cur.execute("SELECT COUNT(*) FROM bookmark").fetchone()[0]
            dv_prof_cnt = 0
            audio_prof_cnt = 0
            if has_avdv:
                dv_prof_cnt = cur.execute(
                    "SELECT COUNT(*) FROM streamdetails WHERE iStreamType=0 AND IFNULL(strDvProfile,'')!=''"
                ).fetchone()[0]
                audio_prof_cnt = cur.execute(
                    "SELECT COUNT(*) FROM streamdetails WHERE iStreamType=1 AND IFNULL(strAudioProfile,'')!=''"
                ).fetchone()[0]
            report["video_db"] = {
                "avdvplus_columns": has_avdv,
                "movies_total": mv_tot,
                "movies_missing_streams": max(0, mv_tot - mv_sd),
                "episodes_total": ep_tot,
                "episodes_missing_streams": max(0, ep_tot - ep_sd),
                "bookmarks_total": bookmarks,
                "dv_profile_populated": dv_prof_cnt,
                "audio_profile_populated": audio_prof_cnt,
            }
        finally:
            con.close()

    return report


def format_health_report(report: dict[str, Any]) -> str:
    """Format health snapshot as concise readable Chinese text for Kodi textviewer."""
    st = report.get("storage", {})
    edb = report.get("emby_db", {})
    vdb = report.get("video_db", {})
    rt = report.get("runtime_stats", {})
    cfg = report.get("config", {})

    policy_map = {"prefer_local": "优先本地存储", "prefer_resolution": "优先最高分辨率", "upstream": "插件默认"}
    policy_zh = policy_map.get(str(cfg.get("ce_multiversion_policy", "prefer_local")), "优先本地存储")

    lines = [
        "=== YoEmby CoreELEC 健康体检报告 ===",
        f"总开关 ce_enabled: {'开启' if cfg.get('ce_enabled') else '关闭'} | 多版本策略: {policy_zh}",
        "",
        "[1] 存储占用",
        f"  MyVideos DB : {_fmt_mb(st.get('video_db_bytes', 0))}",
        f"  Emby DB     : {_fmt_mb(st.get('emby_db_bytes', 0))}",
        f"  Textures DB : {_fmt_mb(st.get('textures_db_bytes', 0))}",
        f"  Thumbnails  : {_fmt_mb(st.get('thumbnails_bytes', 0))} ({st.get('thumbnails_files', 0)} 文件)",
        f"  addon temp/ : {_fmt_mb(st.get('temp_bytes', 0))} ({st.get('temp_files', 0)} 文件)",
        f"  rollback/   : {_fmt_mb(st.get('rollback_bytes', 0))} ({st.get('rollback_files', 0)} 文件)",
        "",
        "[2] 媒体库与流信息状态",
        f"  Emby 增量索引 : {edb.get('ce_indexes_present', 0)} / {edb.get('ce_indexes_expected', 0)}",
        f"  媒体源分布    : 总 {edb.get('mediasources_total', 0)} (SMB {edb.get('mediasources_smb', 0)} / HTTP STRM {edb.get('mediasources_http', 0)})",
        f"  Emby 缺流条目 : {edb.get('items_missing_videostreams', 0)}",
        f"  电影缺流      : {vdb.get('movies_missing_streams', 0)} / {vdb.get('movies_total', 0)}",
        f"  剧集缺流      : {vdb.get('episodes_missing_streams', 0)} / {vdb.get('episodes_total', 0)}",
        f"  avdvplus 徽标 : {'支持' if vdb.get('avdvplus_columns') else '未检测到'} (DV Profile: {vdb.get('dv_profile_populated', 0)}, 音频 Profile: {vdb.get('audio_profile_populated', 0)})",
        f"  书签表行数    : {vdb.get('bookmarks_total', 0)}",
        "",
        "[3] 本次会话优化统计",
        f"  增量指纹跳过重复重写 : {rt.get('fingerprint_skipped', 0)} 次 (实际写入 {rt.get('fingerprint_written', 0)} 次)",
        f"  WebSocket 事件合并   : 收到 {rt.get('ws_events_received', 0)} 次 -> 合并派发 {rt.get('ws_batches_flushed', 0)} 批",
        f"  Widget 刷新防抖合并  : 拦截 {rt.get('widget_refreshes_coalesced', 0)} 次 / 执行 {rt.get('widget_refreshes_executed', 0)} 次",
        f"  STRM 播后自愈补齐    : {rt.get('strm_healed_session', 0)} 条",
    ]
    return "\n".join(lines)


def batch_heal_from_kodi_db(emby_cur: Any, video_cur: Any) -> int:
    """Scan all Movie/Episode/Video items missing Emby VideoStreams and backfill
    any that already have Kodi FFmpeg streamdetails in MyVideos.
    """
    healed = 0
    for table, kodi_type in (("Movie", "movie"), ("Episode", "episode"), ("Video", "video")):
        missing = emby_cur.execute(
            f"SELECT t.EmbyId FROM {table} t "
            f"LEFT JOIN VideoStreams v ON t.EmbyId = v.EmbyId "
            f"WHERE t.KodiFileId IS NOT NULL AND v.EmbyId IS NULL"
        ).fetchall()
        for (emby_id,) in missing:
            if stream_heal.backfill_emby_streams_from_cursors(emby_cur, video_cur, emby_id, kodi_type):
                healed += 1
    return healed


def safe_clear_rollback(rollback_dir: str | Path) -> tuple[bool, int]:
    """Delete files inside addon `rollback/` directory after explicit user confirmation."""
    p = Path(rollback_dir)
    if not p.is_dir():
        return False, 0
    bytes_before, _ = _dir_size_and_count(p)
    shutil.rmtree(p, ignore_errors=True)
    return True, bytes_before


def build_menu_entries(report: dict[str, Any]) -> list[str]:
    """Build theme-neutral plain-text menu entries for native Kodi Dialog.select."""
    st = report.get("storage", {})
    edb = report.get("emby_db", {})
    total_b = (
        int(st.get("video_db_bytes", 0))
        + int(st.get("emby_db_bytes", 0))
        + int(st.get("textures_db_bytes", 0))
        + int(st.get("thumbnails_bytes", 0))
        + int(st.get("temp_bytes", 0))
        + int(st.get("rollback_bytes", 0))
    )
    missing = int(edb.get("items_missing_videostreams", 0))
    rb_b = int(st.get("rollback_bytes", 0))
    rb_cnt = int(st.get("rollback_files", 0))
    idx_cur = int(edb.get("ce_indexes_present", 0))
    idx_exp = int(edb.get("ce_indexes_expected", 0))

    issues = (1 if missing > 0 else 0) + (1 if rb_b > 0 else 0) + (1 if idx_exp > 0 and idx_cur < idx_exp else 0)
    summary_tag = f"{issues} 项可优化" if issues else "全部健康"
    heal_tag = f"当前 {missing} 条缺流" if missing > 0 else "流信息完整"
    rb_tag = f"{_fmt_mb(rb_b)} · {rb_cnt} 文件" if rb_cnt > 0 else "已清空"

    return [
        f"查看健康体检报告（{summary_tag} · {_fmt_mb(total_b)}）",
        f"批量补齐已播 STRM 缺流信息（{heal_tag}）",
        f"清理旧插件备份 rollback/（{rb_tag}）",
        f"核对 / 补建 Emby 增量覆盖索引（{idx_cur} / {idx_exp}）",
    ]


def open_maintenance_menu(utils_mod: Any, dbio_mod: Any) -> None:
    """Open skin-driven native Kodi dialogs (closing addonsettings first to prevent double-glass overlap)."""
    import xbmc  # type: ignore
    import xbmcgui  # type: ignore
    import xbmcvfs  # type: ignore

    server_id = utils_mod.EmbyServerIds[0] if utils_mod.EmbyServerIds else ""
    emby_db = utils_mod.DatabaseFiles.get(server_id, "") if server_id else ""
    video_db = utils_mod.DatabaseFiles.get("video", "")
    tex_db = utils_mod.DatabaseFiles.get("texture", "")
    temp_dir = xbmcvfs.translatePath(utils_mod.FolderEmbyTemp)
    rollback_dir = xbmcvfs.translatePath("special://profile/addon_data/plugin.service.emby-next-gen/rollback/")
    thumbs_dir = xbmcvfs.translatePath(utils_mod.FolderUserdataThumbnails)

    reopen_settings = bool(xbmc.getCondVisibility("Window.IsActive(addonsettings)"))
    if reopen_settings:
        xbmc.executebuiltin("Dialog.Close(addonsettings)")
        xbmc.sleep(150)

    dlg = xbmcgui.Dialog()
    try:
        while not utils_mod.SystemShutdown:
            report = collect_health_report(emby_db, video_db, tex_db, temp_dir, rollback_dir, thumbs_dir)
            choice = dlg.select("YoEmby 健康体检与维护", build_menu_entries(report))
            if choice < 0:
                break

            if choice == 0:
                dlg.textviewer("YoEmby 健康体检报告", format_health_report(report))
            elif choice == 1:
                if not server_id:
                    dlg.ok("YoEmby 维护", "未连接 Emby 服务器，请先在「连接」页登录后重试。")
                    continue
                prog = xbmcgui.DialogProgressBG()
                prog.create("YoEmby", "正在批量回填已播 STRM 缺流信息…")
                sqls: dict[str, Any] = {}
                vid_ro = None
                try:
                    prog.update(30)
                    vid_ro = dbio_mod.DBOpenRO("video", "ce_batch_heal")
                    dbio_mod.DBOpenRW(server_id, "ce_batch_heal", sqls)
                    prog.update(70)
                    healed = batch_heal_from_kodi_db(sqls["emby"].cursor, vid_ro.cursor)
                    prog.update(100)
                finally:
                    prog.close()
                    if vid_ro is not None:
                        dbio_mod.DBCloseRO("video", "ce_batch_heal")
                    if sqls.get("emby") is not None:
                        dbio_mod.DBCloseRW(server_id, "ce_batch_heal", sqls)
                dlg.ok("YoEmby 维护完成", f"本次共从 Kodi 数据库补齐 {healed} 条已播 STRM 流信息。")
            elif choice == 2:
                rb_sz = int(report.get("storage", {}).get("rollback_bytes", 0))
                rb_cnt = int(report.get("storage", {}).get("rollback_files", 0))
                if rb_cnt == 0:
                    dlg.ok("YoEmby 维护", "rollback/ 目录当前已为空，无需清理。")
                    continue
                if dlg.yesno(
                    "YoEmby 清理确认",
                    f"确定删除 rollback/ 目录下 {rb_cnt} 个旧插件备份文件（共 {_fmt_mb(rb_sz)}）吗？\n不会影响当前插件、配置或媒体库。",
                ):
                    _, freed = safe_clear_rollback(rollback_dir)
                    dlg.ok("YoEmby 清理完成", f"已清理 rollback/，释放 {_fmt_mb(freed)}。")
            elif choice == 3:
                if not server_id:
                    dlg.ok("YoEmby 维护", "未连接 Emby 服务器，请先在「连接」页登录后重试。")
                    continue
                sqls = {}
                try:
                    dbio_mod.DBOpenRW(server_id, "ce_index_check", sqls)
                    created = db_opt.ensure_emby_indexes(sqls["emby"].cursor, True)
                finally:
                    if sqls.get("emby") is not None:
                        dbio_mod.DBCloseRW(server_id, "ce_index_check", sqls)
                dlg.ok("YoEmby 索引核对", f"增量覆盖索引核对完成，本次新增 {created} 个索引。")
    finally:
        if reopen_settings and not utils_mod.SystemShutdown:
            xbmc.executebuiltin("Addon.OpenSettings(plugin.service.emby-next-gen)")
