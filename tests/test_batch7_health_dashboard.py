"""Unit tests for YoEmby Health Checkup Dashboard (Plan 3) integration & contract."""

from __future__ import annotations

import sys
import types
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

ADDON_ROOT = Path(__file__).resolve().parent.parent / "plugin.service.emby-next-gen"
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

from ce_opt import maintenance, yoemby_health_dashboard as dash


class _FakeListItem:
    def __init__(self, label: str = "", label2: str = ""):
        self.label = label
        self.label2 = label2
        self.props: dict[str, str] = {}

    def getLabel(self) -> str:
        return self.label

    def setProperty(self, key: str, value: str) -> None:
        self.props[key] = value

    def getProperty(self, key: str) -> str:
        return self.props.get(key, "")


class _FakeControl:
    def __init__(self) -> None:
        self.label = ""
        self.items: list[_FakeListItem] = []
        self.selected_index = 0

    def setLabel(self, text: str) -> None:
        self.label = text

    def reset(self) -> None:
        self.items.clear()
        self.selected_index = 0

    def addItem(self, item: _FakeListItem) -> None:
        self.items.append(item)

    def getSelectedItem(self):
        if 0 <= self.selected_index < len(self.items):
            return self.items[self.selected_index]
        return None


class _FakeDialog:
    textviewer_calls: list[tuple[str, str]] = []
    ok_calls: list[tuple[str, str]] = []
    notification_calls: list[tuple[str, str]] = []
    yesno_result: bool = True

    def textviewer(self, heading: str, body: str) -> None:
        self.__class__.textviewer_calls.append((heading, body))

    def ok(self, heading: str, message: str) -> None:
        self.__class__.ok_calls.append((heading, message))

    def notification(self, heading: str, message: str, icon: str = "", time: int = 0, sound: bool = True) -> None:
        self.__class__.notification_calls.append((heading, message))

    def yesno(self, heading: str, message: str) -> bool:
        return self.__class__.yesno_result


class _FakeProgressBG:
    def create(self, heading: str, message: str = "") -> None:
        pass

    def update(self, percent: int, heading: str = "", message: str = "") -> None:
        pass

    def close(self) -> None:
        pass


class _FakeAction:
    def __init__(self, action_id: int) -> None:
        self._id = action_id

    def getId(self) -> int:
        return self._id


class _HarnessDashboard(dash.YoEmbyHealthDashboard):
    """Testable subclass providing in-memory WindowXMLDialog methods."""

    def __init__(self, *args, **kwargs) -> None:
        self.controls: dict[int, _FakeControl] = {
            cid: _FakeControl()
            for cid in (
                dash.CTRL_TITLE,
                dash.CTRL_SUMMARY,
                dash.CTRL_FOOTER_HINT,
                dash.CTRL_CLOSE,
                *dash.CTRL_TAB_IDS,
                dash.CTRL_CARD_PANEL,
                dash.CTRL_REFRESH,
                dash.CTRL_RAW_REPORT,
            )
        }
        self.window_props: dict[str, str] = {}
        self.focused_id: int | None = None
        self.closed = False
        super().__init__(*args, **kwargs)

    def getControl(self, ctrl_id: int) -> _FakeControl:
        return self.controls[ctrl_id]

    def setProperty(self, key: str, value: str) -> None:
        self.window_props[key] = value

    def setFocusId(self, ctrl_id: int) -> None:
        self.focused_id = ctrl_id

    def close(self) -> None:
        self.closed = True


class TestHealthDashboardContract(unittest.TestCase):
    def test_fallback_xml_matches_skin_and_plugin_contract(self) -> None:
        xml_path = ADDON_ROOT / "resources" / "skins" / "default" / "1080i" / "script-yoemby-health.xml"
        self.assertTrue(xml_path.is_file(), "Missing fallback XML script-yoemby-health.xml")

        root = ET.parse(xml_path).getroot()
        self.assertEqual(root.tag, "window")
        self.assertEqual(root.attrib.get("type"), "dialog")
        self.assertEqual(root.findtext("defaultcontrol"), "2000")

        ctrl_types: dict[str, str] = {}
        for ctrl in root.iter("control"):
            cid = ctrl.attrib.get("id")
            if cid:
                ctrl_types[cid] = ctrl.attrib.get("type", "")

        expected_controls = {
            "1001": "label",
            "1002": "label",
            "1003": "label",
            "1009": "button",
            "1101": "button",
            "1102": "button",
            "1103": "button",
            "2000": "panel",
            "3001": "button",
            "3002": "button",
        }
        for cid, ctype in expected_controls.items():
            self.assertEqual(ctrl_types.get(cid), ctype, f"Control {cid} type mismatch")

        xml_text = xml_path.read_text(encoding="utf-8")
        for token in (
            "$INFO[ListItem.Label]",
            "$INFO[ListItem.Label2]",
            "$INFO[ListItem.Property(value)]",
            "$INFO[ListItem.Property(badge)]",
            "$INFO[ListItem.Property(action_label)]",
            "Window.Property(YoEmby.Page)",
            "ListItem.Property(tone)",
            "ListItem.Property(meter_step)",
        ):
            self.assertIn(token, xml_text)
        self.assertNotIn("← → 切换分页", xml_text)

    def test_quantize_percent_and_legacy_parser_supports_mb_and_gb(self) -> None:
        self.assertEqual(dash._quantize_percent(None), "")
        self.assertEqual(dash._quantize_percent(0), "")
        self.assertEqual(dash._quantize_percent(4), "10")
        self.assertEqual(dash._quantize_percent(87), "90")
        self.assertEqual(dash._quantize_percent(120), "100")

        sample_report = "\n".join(
            [
                "=== YoEmby CoreELEC 健康体检报告 ===",
                "总开关 ce_enabled: 开启 | 多版本策略: 优先本地存储",
                "  MyVideos DB : 124.0 MB",
                "  Emby DB     : 26.2 MB",
                "  Textures DB : 8.1 MB",
                "  Thumbnails  : 1.26 GB (13279 文件)",
                "  addon temp/ : 74.0 MB (210 文件)",
                "  rollback/   : 33.0 MB (262 文件)",
                "  Emby 增量索引 : 8 / 8",
                "  媒体源分布    : 总 8852 (SMB 1200 / HTTP STRM 7652)",
                "  Emby 缺流条目 : 417",
            ]
        )
        parsed = dash.parse_legacy_report_text(sample_report)
        self.assertEqual(len(parsed["pages"]), 3)
        self.assertEqual(len(parsed["pages"][0]["cards"]), 4)
        self.assertIn("GB", parsed["summary"])
        self.assertIn("8 / 8 健康", parsed["summary"])
        self.assertIn("2 项可优化", parsed["summary"])
        # 1.26 GB = 1290.24 MB (properly parsed rather than 0.0 MB)
        self.assertIn("1290.2 MB", parsed["pages"][0]["cards"][0]["value"])

    def test_build_dashboard_data_structured_pages_and_tones(self) -> None:
        report_issues = {
            "storage": {
                "video_db_bytes": 124 * 1024 * 1024,
                "emby_db_bytes": 26 * 1024 * 1024,
                "textures_db_bytes": 8 * 1024 * 1024,
                "thumbnails_bytes": 1355 * 1024 * 1024,
                "thumbnails_files": 13279,
                "temp_bytes": 74 * 1024 * 1024,
                "temp_files": 210,
                "rollback_bytes": 33 * 1024 * 1024,
                "rollback_files": 262,
            },
            "emby_db": {
                "ce_indexes_present": 8,
                "ce_indexes_expected": 8,
                "mediasources_total": 8852,
                "mediasources_http": 7652,
                "mediasources_smb": 1200,
                "items_missing_videostreams": 417,
                "items_healable_local": 12,
            },
            "video_db": {
                "avdvplus_columns": True,
                "movies_total": 1000,
                "movies_missing_streams": 12,
                "episodes_total": 5000,
                "episodes_missing_streams": 40,
                "dv_profile_populated": 914,
                "audio_profile_populated": 850,
            },
            "runtime_stats": {
                "fingerprint_skipped": 42,
                "widget_refreshes_coalesced": 9,
                "strm_healed_session": 3,
            },
            "config": {"ce_enabled": True, "ce_multiversion_policy": "prefer_local"},
        }
        data = maintenance.build_dashboard_data(report_issues)
        self.assertEqual(data["title"], "YoEmby 健康体检仪表盘")
        self.assertIn("2 项可优化", data["summary"])
        self.assertIn("8 / 8 健康", data["summary"])
        self.assertEqual(len(data["pages"]), 3)
        for page in data["pages"]:
            self.assertEqual(len(page["cards"]), 4)

        # Page 1 card 4: rollback cleanup
        rb_card = data["pages"][0]["cards"][3]
        self.assertEqual(rb_card["action_id"], "clean_rollback")
        self.assertEqual(rb_card["tone"], "warn")

        # Page 2 card 1 & 3: index & locally healable missing streams
        self.assertEqual(data["pages"][1]["cards"][0]["action_id"], "rebuild_index")
        self.assertEqual(data["pages"][1]["cards"][0]["tone"], "ok")
        self.assertEqual(data["pages"][1]["cards"][2]["action_id"], "fix_missing_streams")
        self.assertEqual(data["pages"][1]["cards"][2]["tone"], "warn")
        self.assertEqual(data["pages"][2]["cards"][0]["value"], "12 条可回填")
        self.assertEqual(data["pages"][2]["cards"][0]["badge"], "推荐执行")

        # When missing streams exist only as unplayed cloud STRMs (healable=0), do not falsely flag warn/optimizable
        report_unplayed = {
            **report_issues,
            "emby_db": {**report_issues["emby_db"], "items_healable_local": 0},
        }
        data_unplayed = maintenance.build_dashboard_data(report_unplayed)
        self.assertIn("1 项可优化", data_unplayed["summary"])
        self.assertEqual(data_unplayed["pages"][1]["cards"][2]["tone"], "info")
        self.assertEqual(data_unplayed["pages"][1]["cards"][2]["badge"], "待播后自愈")
        self.assertEqual(data_unplayed["pages"][1]["cards"][2]["action_id"], "")
        self.assertEqual(data_unplayed["pages"][2]["cards"][0]["value"], "暂无可回填")
        self.assertEqual(data_unplayed["pages"][2]["cards"][0]["tone"], "info")

        # Page 3 maintenance actions
        self.assertEqual(
            [c["action_id"] for c in data["pages"][2]["cards"]],
            ["fix_missing_streams", "clean_rollback", "rebuild_index", "raw_report"],
        )

    def test_dashboard_controller_navigation_properties_and_actions(self) -> None:
        fake_xbmcgui = types.SimpleNamespace(ListItem=_FakeListItem, Dialog=_FakeDialog, NOTIFICATION_INFO="info")
        _FakeDialog.textviewer_calls.clear()
        _FakeDialog.notification_calls.clear()

        report_v1 = {
            "storage": {"rollback_bytes": 33 * 1024 * 1024, "rollback_files": 262},
            "emby_db": {"ce_indexes_present": 8, "ce_indexes_expected": 8, "items_missing_videostreams": 5},
            "video_db": {},
            "runtime_stats": {},
            "config": {"ce_enabled": True, "ce_multiversion_policy": "prefer_local"},
        }
        report_v2 = {
            "storage": {"rollback_bytes": 0, "rollback_files": 0},
            "emby_db": {"ce_indexes_present": 8, "ce_indexes_expected": 8, "items_missing_videostreams": 0},
            "video_db": {},
            "runtime_stats": {},
            "config": {"ce_enabled": True, "ce_multiversion_policy": "prefer_local"},
        }

        called: list[str] = []

        def on_clean() -> None:
            called.append("clean_rollback")

        def on_refresh() -> tuple[dict, str]:
            called.append("refresh")
            return maintenance.build_dashboard_data(report_v2), maintenance.format_health_report(report_v2)

        with mock.patch.object(dash, "xbmcgui", fake_xbmcgui):
            dlg = _HarnessDashboard(
                report_data=maintenance.build_dashboard_data(report_v1),
                raw_text=maintenance.format_health_report(report_v1),
                actions={"clean_rollback": on_clean, "refresh": on_refresh},
            )
            dlg.onInit()

            self.assertEqual(dlg.focused_id, dash.CTRL_CARD_PANEL)
            self.assertEqual(dlg.window_props["YoEmby.Page"], "0")
            self.assertEqual(dlg.controls[dash.CTRL_TITLE].label, "YoEmby 健康体检仪表盘")
            self.assertIn("顶部标签 / 翻页键切页", dlg.controls[dash.CTRL_FOOTER_HINT].label)
            self.assertNotIn("← → 切换分页", dlg.controls[dash.CTRL_FOOTER_HINT].label)
            self.assertEqual(len(dlg.controls[dash.CTRL_CARD_PANEL].items), 4)

            # Clicking a read-only card (index 0: Thumbnails) notifies instead of failing silently
            dlg.controls[dash.CTRL_CARD_PANEL].selected_index = 0
            dlg.onClick(dash.CTRL_CARD_PANEL)
            self.assertEqual(called, [])
            self.assertEqual(len(_FakeDialog.notification_calls), 1)
            self.assertIn("只读指标", _FakeDialog.notification_calls[0][1])

            # Switch tab via focus & PageDown
            dlg.onFocus(1102)
            self.assertEqual(dlg.window_props["YoEmby.Page"], "1")
            dlg.onAction(_FakeAction(dash.ACTION_PAGE_DOWN))
            self.assertEqual(dlg.window_props["YoEmby.Page"], "2")

            # Click Maintenance 2 card (clean_rollback) -> triggers clean + refresh
            dlg.controls[dash.CTRL_CARD_PANEL].selected_index = 1
            dlg.onClick(dash.CTRL_CARD_PANEL)
            self.assertEqual(called, ["clean_rollback", "refresh"])
            self.assertIn("全部健康", dlg.controls[dash.CTRL_SUMMARY].label)

            # Open raw report via 3002 -> must show refreshed raw text (0.0 MB rollback)
            dlg.onClick(dash.CTRL_RAW_REPORT)
            self.assertEqual(len(_FakeDialog.textviewer_calls), 1)
            self.assertIn("0.0 MB (0 文件)", _FakeDialog.textviewer_calls[0][1])

            # Back / Close
            dlg.onAction(_FakeAction(dash.ACTION_NAV_BACK))
            self.assertTrue(dlg.closed)

    def test_open_maintenance_menu_wires_all_dashboard_callbacks(self) -> None:
        fake_xbmc = types.SimpleNamespace(
            getCondVisibility=lambda cond: cond == "Window.IsActive(addonsettings)",
            executebuiltin=mock.Mock(),
            sleep=mock.Mock(),
        )
        fake_xbmcgui = types.SimpleNamespace(
            Dialog=_FakeDialog,
            DialogProgressBG=_FakeProgressBG,
        )
        fake_xbmcvfs = types.SimpleNamespace(translatePath=lambda p: "")

        utils_mod = types.SimpleNamespace(
            SystemShutdown=False,
            EmbyServerIds=[],
            DatabaseFiles={},
            FolderEmbyTemp="",
            FolderUserdataThumbnails="",
            CustomDialogParameters=("/mock/addon/path", "default", "1080i"),
        )
        dbio_mod = types.SimpleNamespace()

        captured: dict = {}

        def fake_open_dashboard(addon_path, report_data=None, raw_text="", actions=None):
            captured["addon_path"] = addon_path
            captured["report_data"] = report_data
            captured["raw_text"] = raw_text
            captured["actions"] = actions
            # Exercise refresh callback
            refreshed = actions["refresh"]()
            captured["refreshed"] = refreshed

        with mock.patch.dict(
            sys.modules,
            {"xbmc": fake_xbmc, "xbmcgui": fake_xbmcgui, "xbmcvfs": fake_xbmcvfs},
        ), mock.patch.object(dash, "open_health_dashboard", side_effect=fake_open_dashboard):
            maintenance.open_maintenance_menu(utils_mod, dbio_mod)

        self.assertEqual(captured["addon_path"], "/mock/addon/path")
        self.assertEqual(len(captured["report_data"]["pages"]), 3)
        self.assertIn("YoEmby CoreELEC 健康体检报告", captured["raw_text"])
        self.assertEqual(
            set(captured["actions"].keys()),
            {"fix_missing_streams", "clean_rollback", "rebuild_index", "refresh"},
        )
        self.assertIsInstance(captured["refreshed"], tuple)
        self.assertEqual(len(captured["refreshed"]), 2)
        # Verify addonsettings closed before opening and reopened after closing
        fake_xbmc.executebuiltin.assert_any_call("Dialog.Close(addonsettings)")
        fake_xbmc.executebuiltin.assert_any_call("Addon.OpenSettings(plugin.service.emby-next-gen)")


if __name__ == "__main__":
    unittest.main()
