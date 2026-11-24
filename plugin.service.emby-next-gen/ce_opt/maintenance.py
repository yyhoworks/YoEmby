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

from . import config, db_opt, stream_heal, sync_fast, yoemby_health_dashboard


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

    missing_kodi_file_ids: set[int] = set()

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
            ms_items = cur.execute("SELECT COUNT(DISTINCT EmbyId) FROM MediaSources").fetchone()[0]
            ms_missing = cur.execute(
                "SELECT COUNT(DISTINCT m.EmbyId) FROM MediaSources m "
                "LEFT JOIN VideoStreams v ON m.EmbyId = v.EmbyId "
                "WHERE v.EmbyId IS NULL"
            ).fetchone()[0]
            for tbl in ("Movie", "Episode", "Video"):
                try:
                    rows = cur.execute(
                        f"SELECT t.KodiFileId FROM {tbl} t "
                        f"LEFT JOIN VideoStreams v ON t.EmbyId = v.EmbyId "
                        f"WHERE t.KodiFileId IS NOT NULL AND v.EmbyId IS NULL"
                    ).fetchall()
                    for (kfid,) in rows:
                        if kfid:
                            missing_kodi_file_ids.add(int(kfid))
                except sqlite3.Error:
                    pass
            report["emby_db"] = {
                "ce_indexes_present": len(ce_idxs),
                "ce_indexes_expected": len(db_opt.EMBY_ADDITIVE_INDEXES),
                "mediasources_total": ms_total,
                "mediasources_http": ms_http,
                "mediasources_smb": ms_smb,
                "items_with_mediasources": ms_items,
                "items_missing_videostreams": ms_missing,
                "items_healable_local": 0,
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
            healable_local = 0
            if missing_kodi_file_ids:
                kfid_list = list(missing_kodi_file_ids)
                for i in range(0, len(kfid_list), 500):
                    chunk = kfid_list[i : i + 500]
                    ph = ",".join("?" for _ in chunk)
                    healable_local += cur.execute(
                        f"SELECT COUNT(DISTINCT idFile) FROM streamdetails WHERE iStreamType=0 AND idFile IN ({ph})",
                        chunk,
                    ).fetchone()[0]
            if report["emby_db"]:
                report["emby_db"]["items_healable_local"] = healable_local
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
        f"  Emby 缺流条目 : {edb.get('items_missing_videostreams', 0)} (本机可立即回填 {edb.get('items_healable_local', 0)} 条)",
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


def build_dashboard_data(report: dict[str, Any]) -> dict[str, Any]:
    """Build structured 3-page x 2x2 card data for YoEmbyHealthDashboard."""
    st = report.get("storage", {})
    edb = report.get("emby_db", {})
    vdb = report.get("video_db", {})
    rt = report.get("runtime_stats", {})
    cfg = report.get("config", {})

    policy_map = {"prefer_local": "优先本地存储", "prefer_resolution": "优先最高分辨率", "upstream": "插件默认"}
    policy_zh = policy_map.get(str(cfg.get("ce_multiversion_policy", "prefer_local")), "优先本地存储")
    ce_enabled = bool(cfg.get("ce_enabled", True))

    vid_b = int(st.get("video_db_bytes", 0))
    emby_b = int(st.get("emby_db_bytes", 0))
    tex_b = int(st.get("textures_db_bytes", 0))
    db_total_b = vid_b + emby_b + tex_b
    thumbs_b = int(st.get("thumbnails_bytes", 0))
    thumbs_files = int(st.get("thumbnails_files", 0))
    temp_b = int(st.get("temp_bytes", 0))
    temp_files = int(st.get("temp_files", 0))
    rb_b = int(st.get("rollback_bytes", 0))
    rb_files = int(st.get("rollback_files", 0))
    total_b = db_total_b + thumbs_b + temp_b + rb_b
    denom = float(total_b) if total_b > 0 else 1.0

    idx_cur = int(edb.get("ce_indexes_present", 0))
    idx_exp = int(edb.get("ce_indexes_expected", 0))
    idx_ok = idx_exp > 0 and idx_cur >= idx_exp
    idx_label = f"{idx_cur} / {idx_exp}" if idx_exp > 0 else "未检测"
    idx_pct = round(idx_cur * 100.0 / idx_exp, 1) if idx_exp > 0 else 0.0

    ms_total = int(edb.get("mediasources_total", 0))
    ms_http = int(edb.get("mediasources_http", 0))
    ms_smb = int(edb.get("mediasources_smb", 0))
    strm_pct = round(ms_http * 100.0 / ms_total, 1) if ms_total > 0 else 0.0

    missing = int(edb.get("items_missing_videostreams", 0))
    healable = int(edb.get("items_healable_local", 0))
    missing_pct = (
        min(100.0, round(missing * 100.0 / max(1, ms_http or ms_total), 1))
        if missing > 0
        else 0.0
    )

    mv_tot = int(vdb.get("movies_total", 0))
    mv_miss = int(vdb.get("movies_missing_streams", 0))
    ep_tot = int(vdb.get("episodes_total", 0))
    ep_miss = int(vdb.get("episodes_missing_streams", 0))
    avdv = bool(vdb.get("avdvplus_columns", False))
    dv_cnt = int(vdb.get("dv_profile_populated", 0))
    audio_cnt = int(vdb.get("audio_profile_populated", 0))

    has_rollback = rb_files > 0 or rb_b > 0
    optimizable = (1 if healable > 0 else 0) + (1 if has_rollback else 0) + (1 if idx_exp > 0 and idx_cur < idx_exp else 0)

    idx_summary = f"增量索引 {idx_label} 健康" if idx_ok else (f"增量索引 {idx_label}" if idx_exp > 0 else "索引未检测")
    opt_summary = f"{optimizable} 项可优化" if optimizable > 0 else "全部健康"
    summary = f"总存储 {_fmt_mb(total_b)} · {idx_summary} · {opt_summary}"

    thumbs_pct = thumbs_b * 100.0 / denom
    db_pct = db_total_b * 100.0 / denom
    temp_pct = temp_b * 100.0 / denom
    rb_pct = rb_b * 100.0 / denom

    storage_cards = [
        {
            "title": "Thumbnails 缩略图缓存",
            "value": _fmt_mb(thumbs_b),
            "detail": f"{thumbs_files:,} 个文件 · 占总存储 {thumbs_pct:.1f}%",
            "badge": "正常缓存",
            "tone": "info",
            "percent": max(10.0, thumbs_pct) if thumbs_b > 0 else 0,
        },
        {
            "title": "Kodi & Emby 数据库",
            "value": _fmt_mb(db_total_b),
            "detail": f"MyVideos {_fmt_mb(vid_b)} · Emby {_fmt_mb(emby_b)} · Textures {_fmt_mb(tex_b)}",
            "badge": "结构健康",
            "tone": "ok",
            "percent": max(10.0, db_pct) if db_total_b > 0 else 0,
        },
        {
            "title": "addon temp/ 临时缓存",
            "value": _fmt_mb(temp_b),
            "detail": f"{temp_files:,} 个临时文件 · 运行期缓存",
            "badge": "正常",
            "tone": "info",
            "percent": max(10.0, temp_pct) if temp_b > 0 else 0,
        },
        {
            "title": "rollback/ 旧插件备份",
            "value": _fmt_mb(rb_b),
            "detail": f"{rb_files:,} 个历史文件 · 可安全清理" if has_rollback else "目录已清空 · 零冗余占用",
            "badge": "可优化" if has_rollback else "已清空",
            "tone": "warn" if has_rollback else "ok",
            "percent": max(10.0, rb_pct) if rb_b > 0 else 0,
            "action_id": "clean_rollback" if has_rollback else "",
            "action_label": "按确定：清理旧插件备份 ›" if has_rollback else "",
        },
    ]

    if healable > 0:
        missing_detail = f"本机可回填 {healable:,} 条 · 其余播后自动自愈"
        missing_badge = f"可回填 {healable}"
        missing_tone = "warn"
        missing_card_pct = max(20.0, missing_pct)
        missing_action_id = "fix_missing_streams"
        missing_action_label = "按确定：回填已播 STRM 流信息 ›"
    elif missing > 0:
        missing_detail = (
            f"电影 {mv_miss}/{mv_tot} · 剧集 {ep_miss}/{ep_tot} · 均未播过，播后自愈"
            if (mv_tot > 0 or ep_tot > 0)
            else "均未在本机播过（可回填 0 条）· 播后自动自愈"
        )
        missing_badge = "待播后自愈"
        missing_tone = "info"
        missing_card_pct = max(10.0, missing_pct)
        missing_action_id = ""
        missing_action_label = ""
    else:
        missing_detail = "全部条目流信息完整"
        missing_badge = "完整"
        missing_tone = "ok"
        missing_card_pct = 100
        missing_action_id = ""
        missing_action_label = ""
    opt_detail = (
        f"策略：{policy_zh} · avdvplus {'就绪' if avdv else '未检测'} (DV {dv_cnt} / 音频 {audio_cnt})"
        if vdb
        else f"多版本选源策略：{policy_zh}"
    )

    library_cards = [
        {
            "title": "Emby 增量覆盖索引",
            "value": idx_label,
            "detail": "所有媒体库索引覆盖正常" if idx_ok else "建议核对并补建增量索引",
            "badge": "完全健康" if idx_ok else "待核对",
            "tone": "ok" if idx_ok else "warn",
            "percent": idx_pct,
            "action_id": "rebuild_index",
            "action_label": "按确定：核对 / 补建索引 ›",
        },
        {
            "title": f"媒体源分布（总 {ms_total:,}）",
            "value": f"{strm_pct:.1f}% STRM" if ms_total > 0 else "0 条",
            "detail": f"HTTP STRM {ms_http:,} 条 · 本地/SMB {ms_smb:,} 条",
            "badge": policy_zh,
            "tone": "info",
            "percent": strm_pct,
        },
        {
            "title": "Emby 缺流条目",
            "value": f"{missing:,} 条",
            "detail": missing_detail,
            "badge": missing_badge,
            "tone": missing_tone,
            "percent": missing_card_pct,
            "action_id": missing_action_id,
            "action_label": missing_action_label,
        },
        {
            "title": "CoreELEC 优化与徽标",
            "value": "开启" if ce_enabled else "已关闭",
            "detail": opt_detail,
            "badge": "运行中" if ce_enabled else "未开启",
            "tone": "ok" if ce_enabled else "warn",
            "percent": 100 if ce_enabled else 10,
        },
    ]

    healed_sess = int(rt.get("strm_healed_session", 0))
    fp_skip = int(rt.get("fingerprint_skipped", 0))
    w_coal = int(rt.get("widget_refreshes_coalesced", 0))

    if healable > 0:
        heal_card_value = f"{healable:,} 条可回填"
        heal_card_detail = f"总缺流 {missing:,} 条 · 仅回填本机已播条目"
        heal_card_badge = "推荐执行"
        heal_card_tone = "warn"
        heal_card_pct = 70
        heal_card_action_label = "按确定：立即回填已播条目 ›"
    elif missing > 0:
        heal_card_value = "暂无可回填"
        heal_card_detail = f"未播缺流 {missing:,} 条 · 点播后自动自愈（已自愈 {healed_sess}）"
        heal_card_badge = "播后自愈"
        heal_card_tone = "info"
        heal_card_pct = 100
        heal_card_action_label = "按确定：重新扫描本机已播记录 ›"
    else:
        heal_card_value = "无需补齐"
        heal_card_detail = f"全部条目流信息完整（本次已自愈 {healed_sess} 条）"
        heal_card_badge = "已完成"
        heal_card_tone = "ok"
        heal_card_pct = 100
        heal_card_action_label = "按确定：再次核对本机记录 ›"

    action_cards = [
        {
            "title": "维护 1 · 批量补齐 STRM 缺流",
            "value": heal_card_value,
            "detail": heal_card_detail,
            "badge": heal_card_badge,
            "tone": heal_card_tone,
            "percent": heal_card_pct,
            "action_id": "fix_missing_streams",
            "action_label": heal_card_action_label,
        },
        {
            "title": "维护 2 · 清理 rollback/ 备份",
            "value": f"释放 {_fmt_mb(rb_b)}" if has_rollback else "无需清理",
            "detail": f"安全移除 {rb_files:,} 个旧插件历史文件" if has_rollback else "rollback/ 目录当前已为空",
            "badge": "安全清理" if has_rollback else "已清空",
            "tone": "warn" if has_rollback else "ok",
            "percent": 30 if has_rollback else 100,
            "action_id": "clean_rollback",
            "action_label": "按确定：立即清理备份 ›",
        },
        {
            "title": "维护 3 · 核对 / 补建增量索引",
            "value": idx_label,
            "detail": "检查并修复 Emby 增量同步覆盖索引",
            "badge": "健康" if idx_ok else "需核对",
            "tone": "ok" if idx_ok else "warn",
            "percent": idx_pct if idx_exp > 0 else 100,
            "action_id": "rebuild_index",
            "action_label": "按确定：立即核对索引 ›",
        },
        {
            "title": "维护 4 · 查看完整原始体检文本",
            "value": "原始报告",
            "detail": f"含会话统计（跳过重写 {fp_skip} 次 · 合并刷新 {w_coal} 次）",
            "badge": "诊断详情",
            "tone": "info",
            "percent": 100,
            "action_id": "raw_report",
            "action_label": "按确定：打开文本阅读器 ›",
        },
    ]

    return {
        "title": "YoEmby 健康体检仪表盘",
        "summary": summary,
        "pages": [
            {"title": "1. 存储分布", "cards": storage_cards},
            {"title": "2. 媒体库与流信息", "cards": library_cards},
            {"title": "3. 维护与一键修复", "cards": action_cards},
        ],
    }


def open_maintenance_menu(utils_mod: Any, dbio_mod: Any) -> None:
    """Open YoEmby 3-page Health Checkup Dashboard (auto-styled by YoPlayer glass override)."""
    import xbmc  # type: ignore
    import xbmcgui  # type: ignore
    import xbmcvfs  # type: ignore

    if getattr(utils_mod, "SystemShutdown", False):
        return

    server_id = utils_mod.EmbyServerIds[0] if utils_mod.EmbyServerIds else ""
    emby_db = utils_mod.DatabaseFiles.get(server_id, "") if server_id else ""
    video_db = utils_mod.DatabaseFiles.get("video", "")
    tex_db = utils_mod.DatabaseFiles.get("texture", "")
    temp_dir = xbmcvfs.translatePath(utils_mod.FolderEmbyTemp)
    rollback_dir = xbmcvfs.translatePath("special://profile/addon_data/plugin.service.emby-next-gen/rollback/")
    thumbs_dir = xbmcvfs.translatePath(utils_mod.FolderUserdataThumbnails)

    addon_path = ""
    if hasattr(utils_mod, "CustomDialogParameters") and utils_mod.CustomDialogParameters:
        addon_path = str(utils_mod.CustomDialogParameters[0])
    elif hasattr(utils_mod, "Addon"):
        addon_path = str(utils_mod.Addon.getAddonInfo("path"))
    else:
        import xbmcaddon  # type: ignore

        addon_path = str(xbmcaddon.Addon("plugin.service.emby-next-gen").getAddonInfo("path"))

    dlg = xbmcgui.Dialog()

    def _collect_bundle() -> tuple[dict[str, Any], str]:
        snap = collect_health_report(emby_db, video_db, tex_db, temp_dir, rollback_dir, thumbs_dir)
        return build_dashboard_data(snap), format_health_report(snap)

    def _run_fix_missing_streams() -> None:
        if not server_id:
            dlg.ok("YoEmby 维护", "未连接 Emby 服务器，请先在「连接」页登录后重试。")
            return
        prog = xbmcgui.DialogProgressBG()
        prog.create("YoEmby", "正在批量回填已播 STRM 缺流信息…")
        sqls: dict[str, Any] = {}
        vid_ro = None
        healed = 0
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
        if healed > 0:
            dlg.ok("YoEmby 维护完成", f"本次共从 Kodi 数据库补齐 {healed} 条已播 STRM 流信息。")
        else:
            dlg.ok(
                "YoEmby 维护提示",
                "当前没有可从本机回填的已播 STRM 条目（0 条）。\n"
                "其余缺流影片均未在本机播放过，点播一次后会自动自愈补齐，\n"
                "或在 Emby 服务端刷新对应媒体库元数据后同步。",
            )

    def _run_clean_rollback() -> None:
        rb_sz, rb_cnt = _dir_size_and_count(rollback_dir)
        if rb_cnt == 0 and rb_sz == 0:
            dlg.ok("YoEmby 维护", "rollback/ 目录当前已为空，无需清理。")
            return
        if dlg.yesno(
            "YoEmby 清理确认",
            f"确定删除 rollback/ 目录下 {rb_cnt} 个旧插件备份文件（共 {_fmt_mb(rb_sz)}）吗？\n不会影响当前插件、配置或媒体库。",
        ):
            _, freed = safe_clear_rollback(rollback_dir)
            dlg.ok("YoEmby 清理完成", f"已清理 rollback/，释放 {_fmt_mb(freed)}。")

    def _run_rebuild_index() -> None:
        if not server_id:
            dlg.ok("YoEmby 维护", "未连接 Emby 服务器，请先在「连接」页登录后重试。")
            return
        sqls: dict[str, Any] = {}
        created = 0
        try:
            dbio_mod.DBOpenRW(server_id, "ce_index_check", sqls)
            created = db_opt.ensure_emby_indexes(sqls["emby"].cursor, True)
        finally:
            if sqls.get("emby") is not None:
                dbio_mod.DBCloseRW(server_id, "ce_index_check", sqls)
        dlg.ok("YoEmby 索引核对", f"增量覆盖索引核对完成，本次新增 {created} 个索引。")

    reopen_settings = bool(xbmc.getCondVisibility("Window.IsActive(addonsettings)"))
    if reopen_settings:
        xbmc.executebuiltin("Dialog.Close(addonsettings)")
        xbmc.sleep(150)

    try:
        report_data, raw_text = _collect_bundle()
        yoemby_health_dashboard.open_health_dashboard(
            addon_path=addon_path,
            report_data=report_data,
            raw_text=raw_text,
            actions={
                "fix_missing_streams": _run_fix_missing_streams,
                "clean_rollback": _run_clean_rollback,
                "rebuild_index": _run_rebuild_index,
                "refresh": _collect_bundle,
            },
        )
    finally:
        if reopen_settings and not getattr(utils_mod, "SystemShutdown", False):
            xbmc.executebuiltin("Addon.OpenSettings(plugin.service.emby-next-gen)")
