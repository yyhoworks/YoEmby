"""Unified opaque 10-foot TV Health & Maintenance WindowXMLDialog for YoEmby.

Eliminates YoPlayer translucent DialogTextViewer overlap by rendering inside a
dedicated high-contrast dark obsidian dialog (`script-emby-ce-maintenance.xml`)
that combines summary diagnostics, inline technical details, and 1-click actions.
"""

from __future__ import annotations

from typing import Any

from . import db_opt, maintenance


def fmt_size(num_bytes: int) -> str:
    """Format byte size cleanly as MB or GB for 10-foot TV legibility."""
    if num_bytes >= 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"
    return f"{num_bytes / (1024 * 1024):.1f} MB"


def build_panel_view_model(report: dict[str, Any]) -> dict[str, Any]:
    """Build pure UI strings & state flags from a health report (fully unit-testable)."""
    st = report.get("storage", {})
    edb = report.get("emby_db", {})
    vdb = report.get("video_db", {})
    rt = report.get("runtime_stats", {})
    cfg = report.get("config", {})

    thumb_b = int(st.get("thumbnails_bytes", 0))
    temp_b = int(st.get("temp_bytes", 0))
    rb_b = int(st.get("rollback_bytes", 0))
    rb_cnt = int(st.get("rollback_files", 0))
    db_b = int(st.get("video_db_bytes", 0)) + int(st.get("emby_db_bytes", 0)) + int(st.get("textures_db_bytes", 0))
    total_b = thumb_b + temp_b + rb_b + db_b

    missing = int(edb.get("items_missing_videostreams", 0))
    mv_miss = int(vdb.get("movies_missing_streams", 0))
    ep_miss = int(vdb.get("episodes_missing_streams", 0))
    idx_cur = int(edb.get("ce_indexes_present", 0))
    idx_exp = int(edb.get("ce_indexes_expected", 0))
    ms_tot = int(edb.get("mediasources_total", 0))
    ms_smb = int(edb.get("mediasources_smb", 0))
    ms_http = int(edb.get("mediasources_http", 0))

    issues = (1 if missing > 0 else 0) + (1 if rb_b > 0 else 0) + (1 if idx_exp > 0 and idx_cur < idx_exp else 0)
    status_badge = f"[COLOR FFFBBF24]{issues} 项可优化[/COLOR]" if issues else "[COLOR FF34D399]全部健康[/COLOR]"

    rb_note = f"旧版备份 {fmt_size(rb_b)}（可释放）" if rb_b > 0 else "旧版备份已清理"
    row1_desc = f"缩略图 {fmt_size(thumb_b)} · 节点图标 {fmt_size(temp_b)} · {rb_note}"
    row1_val = fmt_size(total_b)
    row1_sub = f"[COLOR FFFBBF24]含 {fmt_size(rb_b)} 旧备份[/COLOR]" if rb_b > 0 else "[COLOR FF34D399]空间整洁[/COLOR]"

    row2_desc = f"共 {ms_tot} 片源（SMB {ms_smb} · STRM {ms_http}）· 覆盖索引 {idx_cur}/{idx_exp}"
    row2_val = f"[COLOR FFFBBF24]{missing} 条缺流[/COLOR]" if missing > 0 else "[COLOR FF34D399]流信息完整[/COLOR]"
    row2_sub = f"电影 {mv_miss} · 剧集 {ep_miss}" if missing > 0 else "已全部同步至 emby.db"

    policy_map = {"prefer_local": "优先本地存储", "prefer_resolution": "优先最高分辨率", "upstream": "插件默认"}
    policy_zh = policy_map.get(str(cfg.get("ce_multiversion_policy", "prefer_local")), "优先本地存储")
    avdv = "avdvplus 徽标就绪" if vdb.get("avdvplus_columns") else "标准 Kodi 流表"
    row3_desc = f"{avdv} · 多版本策略：{policy_zh}"
    row3_val = "[COLOR FF34D399]加速已开启[/COLOR]" if cfg.get("ce_enabled", True) else "[COLOR FFFDA4AF]总开关已关[/COLOR]"
    row3_sub = f"本次拦截 {rt.get('fingerprint_skipped', 0)} 次重复重写 · 自愈 {rt.get('strm_healed_session', 0)} 条"

    details_lines = [
        f"MyVideos DB : {fmt_size(int(st.get('video_db_bytes', 0)))}    |    Emby DB : {fmt_size(int(st.get('emby_db_bytes', 0)))}",
        f"Textures DB : {fmt_size(int(st.get('textures_db_bytes', 0)))}    |    书签表行数 : {vdb.get('bookmarks_total', 0)}",
        f"Thumbnails : {fmt_size(thumb_b)} ({st.get('thumbnails_files', 0)} 文件)    |    temp/ : {fmt_size(temp_b)} ({st.get('temp_files', 0)} 文件)",
        f"rollback/ : {fmt_size(rb_b)} ({rb_cnt} 文件)    |    增量覆盖索引 : {idx_cur} / {idx_exp}",
        f"avdvplus 徽标写入 : DV Profile {vdb.get('dv_profile_populated', 0)} 条 · 音频 Profile {vdb.get('audio_profile_populated', 0)} 条",
        f"同步防抖与指纹 : 收到 WS {rt.get('ws_events_received', 0)} 次 → 合并 {rt.get('ws_batches_flushed', 0)} 批 · 指纹跳过 {rt.get('fingerprint_skipped', 0)} 次",
        f"首页刷新防抖 : 拦截 {rt.get('widget_refreshes_coalesced', 0)} 次 / 执行 {rt.get('widget_refreshes_executed', 0)} 次 · 播后自愈 {rt.get('strm_healed_session', 0)} 条",
        "",
        "说明：所有检测均采用 SQLite 只读模式 (?mode=ro)，不锁库、不影响播放。按返回键可回到摘要页。",
    ]

    return {
        "title": "YoEmby 健康体检与维护",
        "status_badge": status_badge,
        "issues_count": issues,
        "row1": ("存储与缓存占用", row1_desc, row1_val, row1_sub),
        "row2": ("媒体库流信息与索引", row2_desc, row2_val, row2_sub),
        "row3": ("音画徽标与后台加速", row3_desc, row3_val, row3_sub),
        "details_text": "\n".join(details_lines),
        "btn_heal": f"补齐缺流 ({missing})" if missing > 0 else "流信息完整",
        "btn_clean": f"清理旧备份 ({fmt_size(rb_b)})" if rb_b > 0 else "旧备份已清空",
        "btn_index": f"核对索引 ({idx_cur}/{idx_exp})",
        "btn_details_summary": "技术明细",
        "btn_details_back": "返回摘要",
        "missing_count": missing,
        "rollback_bytes": rb_b,
        "rollback_files": rb_cnt,
    }


def open_panel(utils_mod: Any, dbio_mod: Any) -> None:
    """Open the opaque unified MaintenanceDialog (falls back cleanly if XML cannot load)."""
    import xbmc  # type: ignore
    import xbmcgui  # type: ignore
    import xbmcvfs  # type: ignore

    addon_path = utils_mod.Addon.getAddonInfo("path")
    server_id = utils_mod.EmbyServerIds[0] if utils_mod.EmbyServerIds else ""
    paths = {
        "server_id": server_id,
        "emby_db": utils_mod.DatabaseFiles.get(server_id, "") if server_id else "",
        "video_db": utils_mod.DatabaseFiles.get("video", ""),
        "tex_db": utils_mod.DatabaseFiles.get("texture", ""),
        "temp_dir": xbmcvfs.translatePath(utils_mod.FolderEmbyTemp),
        "rollback_dir": xbmcvfs.translatePath("special://profile/addon_data/plugin.service.emby-next-gen/rollback/"),
        "thumbs_dir": xbmcvfs.translatePath(utils_mod.FolderUserdataThumbnails),
    }

    class MaintenanceDialog(xbmcgui.WindowXMLDialog):
        def __init__(self, *args: Any, **kwargs: Any):
            super().__init__(*args, **kwargs)
            self._show_details = False
            self._vm: dict[str, Any] = {}
            self._hint = "方向键选择下方操作，按返回键退出"

        def onInit(self) -> None:
            self._refresh()
            try:
                self.setFocusId(101)
            except Exception:
                pass

        def _set_label(self, cid: int, text: str) -> None:
            try:
                self.getControl(cid).setLabel(text)
            except Exception:
                pass

        def _set_text(self, cid: int, text: str) -> None:
            try:
                self.getControl(cid).setText(text)
            except Exception:
                pass

        def _set_visible(self, cid: int, visible: bool) -> None:
            try:
                self.getControl(cid).setVisible(visible)
            except Exception:
                pass

        def _refresh(self, hint: str | None = None) -> None:
            if hint is not None:
                self._hint = hint
            rep = maintenance.collect_health_report(
                paths["emby_db"],
                paths["video_db"],
                paths["tex_db"],
                paths["temp_dir"],
                paths["rollback_dir"],
                paths["thumbs_dir"],
            )
            vm = build_panel_view_model(rep)
            self._vm = vm

            self._set_label(200, vm["title"])
            self._set_label(201, vm["status_badge"])
            self._set_label(202, self._hint)

            for base_id, key in ((310, "row1"), (320, "row2"), (330, "row3")):
                t, d, v, s = vm[key]
                self._set_label(base_id, t)
                self._set_label(base_id + 1, d)
                self._set_label(base_id + 2, v)
                self._set_label(base_id + 3, s)

            self._set_text(400, vm["details_text"])
            self._set_visible(300, not self._show_details)
            self._set_visible(400, self._show_details)

            self._set_label(101, vm["btn_heal"])
            self._set_label(102, vm["btn_clean"])
            self._set_label(103, vm["btn_index"])
            self._set_label(104, vm["btn_details_back"] if self._show_details else vm["btn_details_summary"])

        def onAction(self, action: Any) -> None:
            aid = action.getId()
            if aid in (10, 92):  # PREVIOUS_MENU / NAV_BACK
                if self._show_details:
                    self._show_details = False
                    self._refresh("已返回健康摘要，再按返回键退出")
                else:
                    self.close()

        def onClick(self, controlId: int) -> None:
            if controlId == 104:
                self._show_details = not self._show_details
                self._refresh("只读技术明细（按返回键回到摘要）" if self._show_details else "方向键选择下方操作，按返回键退出")
                return

            if controlId == 101:  # Batch heal STRM streams
                if not paths["server_id"]:
                    self._refresh("[COLOR FFFDA4AF]未连接 Emby 服务器，请先在「连接」页登录[/COLOR]")
                    return
                prog = xbmcgui.DialogProgressBG()
                prog.create("YoEmby", "正在从 Kodi 数据库批量回填缺流 STRM…")
                sqls: dict[str, Any] = {}
                vid_ro = None
                try:
                    prog.update(30)
                    vid_ro = dbio_mod.DBOpenRO("video", "ce_batch_heal")
                    dbio_mod.DBOpenRW(paths["server_id"], "ce_batch_heal", sqls)
                    prog.update(70)
                    healed = maintenance.batch_heal_from_kodi_db(sqls["emby"].cursor, vid_ro.cursor)
                    prog.update(100)
                except Exception as exc:
                    self._refresh(f"[COLOR FFFDA4AF]回填失败：{exc}[/COLOR]")
                    return
                finally:
                    prog.close()
                    if vid_ro is not None:
                        dbio_mod.DBCloseRO("video", "ce_batch_heal")
                    if sqls.get("emby") is not None:
                        dbio_mod.DBCloseRW(paths["server_id"], "ce_batch_heal", sqls)
                self._refresh(f"[COLOR FF34D399]批量回填完成：本次补齐 {healed} 条已播 STRM 流信息[/COLOR]")
                return

            if controlId == 102:  # Clean rollback/
                rb_b = self._vm.get("rollback_bytes", 0)
                rb_cnt = self._vm.get("rollback_files", 0)
                if rb_cnt == 0:
                    self._refresh("rollback 目录已为空，无需清理")
                    return
                ok = xbmcgui.Dialog().yesno(
                    "YoEmby 清理确认",
                    f"确定删除 rollback/ 下 {rb_cnt} 个旧插件备份文件（共 {fmt_size(rb_b)}）吗？\n不会影响当前插件、设置或媒体库。",
                )
                if ok:
                    _, freed = maintenance.safe_clear_rollback(paths["rollback_dir"])
                    self._refresh(f"[COLOR FF34D399]已清理 rollback/，释放 {fmt_size(freed)}[/COLOR]")
                return

            if controlId == 103:  # Verify / add indexes
                if not paths["server_id"]:
                    self._refresh("[COLOR FFFDA4AF]未连接 Emby 服务器，请先在「连接」页登录[/COLOR]")
                    return
                sqls = {}
                try:
                    dbio_mod.DBOpenRW(paths["server_id"], "ce_index_check", sqls)
                    created = db_opt.ensure_emby_indexes(sqls["emby"].cursor, True)
                except Exception as exc:
                    self._refresh(f"[COLOR FFFDA4AF]索引检查失败：{exc}[/COLOR]")
                    return
                finally:
                    if sqls.get("emby") is not None:
                        dbio_mod.DBCloseRW(paths["server_id"], "ce_index_check", sqls)
                self._refresh(f"[COLOR FF34D399]索引检查完成：本次新增 {created} 个覆盖索引[/COLOR]")

    try:
        dlg = MaintenanceDialog("script-emby-ce-maintenance.xml", addon_path, "default", "1080i")
        dlg.doModal()
        del dlg
    except Exception as exc:
        xbmc.log(f"EMBY.ce_opt.maintenance_ui: XML dialog fallback ({exc})", 2)
        xbmc.executebuiltin("Dialog.Close(addonsettings)")
        rep = maintenance.collect_health_report(
            paths["emby_db"], paths["video_db"], paths["tex_db"],
            paths["temp_dir"], paths["rollback_dir"], paths["thumbs_dir"],
        )
        xbmcgui.Dialog().textviewer("YoEmby 健康体检报告", maintenance.format_health_report(rep))
