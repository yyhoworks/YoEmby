"""Unit tests for Batch 5: opaque maintenance UI, TV overlays & distilled settings."""

from __future__ import annotations

import re
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ADDON_ROOT = Path(__file__).resolve().parent.parent / "plugin.service.emby-next-gen"
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

from ce_opt import config, maintenance_ui


def _parse_po_ids(po_path: Path) -> set[str]:
    text = po_path.read_text(encoding="utf-8")
    return set(re.findall(r'msgctxt "#(\d+)"', text))


class _FakeAddon:
    def __init__(self, values: dict[str, str]):
        self._values = values

    def getSetting(self, key: str) -> str:
        return self._values.get(key, "")


class TestMaintenanceUiViewModel(unittest.TestCase):
    def test_fmt_size_auto_units(self) -> None:
        self.assertEqual(maintenance_ui.fmt_size(0), "0.0 MB")
        self.assertEqual(maintenance_ui.fmt_size(33 * 1024 * 1024), "33.0 MB")
        self.assertEqual(maintenance_ui.fmt_size(int(1.26 * 1024 * 1024 * 1024)), "1.26 GB")

    def test_view_model_issues_and_healthy_states(self) -> None:
        report_issues = {
            "storage": {
                "video_db_bytes": 124 * 1024 * 1024,
                "emby_db_bytes": 26 * 1024 * 1024,
                "textures_db_bytes": 8 * 1024 * 1024,
                "thumbnails_bytes": 1355 * 1024 * 1024,
                "thumbnails_files": 13279,
                "temp_bytes": 74 * 1024 * 1024,
                "temp_files": 1636,
                "rollback_bytes": 33 * 1024 * 1024,
                "rollback_files": 262,
            },
            "emby_db": {
                "ce_indexes_present": 8,
                "ce_indexes_expected": 8,
                "mediasources_total": 8852,
                "mediasources_smb": 2398,
                "mediasources_http": 6454,
                "items_missing_videostreams": 417,
            },
            "video_db": {
                "avdvplus_columns": True,
                "dv_profile_populated": 24,
                "audio_profile_populated": 120,
                "movies_missing_streams": 18,
                "episodes_missing_streams": 399,
                "bookmarks_total": 1000,
            },
            "runtime_stats": {
                "ws_events_received": 12,
                "ws_batches_flushed": 3,
                "fingerprint_skipped": 9,
                "widget_refreshes_coalesced": 4,
                "widget_refreshes_executed": 1,
                "strm_healed_session": 2,
            },
            "config": {"ce_enabled": True, "ce_multiversion_policy": "prefer_local"},
        }
        vm = maintenance_ui.build_panel_view_model(report_issues)
        self.assertEqual(vm["issues_count"], 2)
        self.assertIn("2 项可优化", vm["status_badge"])
        self.assertIn("GB", vm["row1"][2])
        self.assertIn("417 条缺流", vm["row2"][2])
        self.assertIn("优先本地存储", vm["row3"][1])
        self.assertEqual(vm["btn_heal"], "补齐缺流 (417)")
        self.assertEqual(vm["btn_clean"], "清理旧备份 (33.0 MB)")
        self.assertIn("DV Profile 24 条", vm["details_text"])

        # Healthy state
        report_ok = {
            "storage": {"thumbnails_bytes": 10 * 1024 * 1024},
            "emby_db": {"ce_indexes_present": 8, "ce_indexes_expected": 8, "items_missing_videostreams": 0},
            "video_db": {"avdvplus_columns": True},
            "runtime_stats": {},
            "config": {"ce_enabled": True, "ce_multiversion_policy": "upstream"},
        }
        vm_ok = maintenance_ui.build_panel_view_model(report_ok)
        self.assertEqual(vm_ok["issues_count"], 0)
        self.assertIn("全部健康", vm_ok["status_badge"])
        self.assertEqual(vm_ok["btn_heal"], "流信息完整")
        self.assertEqual(vm_ok["btn_clean"], "旧备份已清空")


class TestTvSkinOverlaysAndDistilledSettings(unittest.TestCase):
    def tearDown(self) -> None:
        config.reset_defaults()

    def test_all_skin_xml_files_well_formed_and_high_contrast(self) -> None:
        skin_dir = ADDON_ROOT / "resources" / "skins" / "default" / "1080i"

        # 1. Unified opaque maintenance dialog
        maint = ET.parse(skin_dir / "script-emby-ce-maintenance.xml").getroot()
        imgs = [el for el in maint.iter("control") if el.attrib.get("type") == "image"]
        diffuses = [img.find("texture").attrib.get("colordiffuse", "") for img in imgs if img.find("texture") is not None]
        self.assertIn("EB070A0F", diffuses)  # fullscreen opaque scrim
        self.assertIn("FF141923", diffuses)  # solid obsidian card
        btns = [el.attrib.get("id") for el in maint.iter("control") if el.attrib.get("type") == "button"]
        self.assertEqual(btns, ["101", "102", "103", "104"])

        # 2. Infuse-style bottom-right skip dialogs (clear of subtitle band)
        for name in (
            "script-emby-skipintrodialog.xml",
            "script-emby-skipcreditsdialog.xml",
            "script-emby-skipintrodialogembuary.xml",
        ):
            root = ET.parse(skin_dir / name).getroot()
            grp = next(el for el in root.iter("control") if el.attrib.get("type") == "group")
            self.assertGreaterEqual(int(grp.findtext("left", "0")), 1500)
            self.assertGreaterEqual(int(grp.findtext("top", "0")), 820)
            btn = next(el for el in root.iter("control") if el.attrib.get("type") == "button" and el.attrib.get("id") == "1")
            self.assertEqual(btn.findtext("focusedcolor"), "FF0B0E14")

        # 3. Context menu: high-contrast focus & safe horizontal nav (no accidental close)
        ctx = ET.parse(skin_dir / "script-emby-context.xml").getroot()
        lst = next(el for el in ctx.iter("control") if el.attrib.get("id") == "155")
        self.assertEqual(lst.findtext("onleft"), "noop")
        self.assertEqual(lst.findtext("onright"), "noop")
        self.assertIsNone(lst.find("onup"))
        self.assertIsNone(lst.find("ondown"))

    def test_distilled_ce_opt_settings_and_localization(self) -> None:
        root = ET.parse(ADDON_ROOT / "resources" / "settings.xml").getroot()
        ce_cat = next(c for c in root.iter("category") if c.attrib.get("id") == "ce_opt")
        settings = list(ce_cat.iter("setting"))

        basic = [s for s in settings if s.findtext("level") == "0"]
        self.assertEqual(
            [s.attrib["id"] for s in basic],
            ["ce_maintenance_menu", "ce_enabled", "ce_multiversion_policy", "ce_skip_chapter_bookmarks"],
        )

        en_ids = _parse_po_ids(ADDON_ROOT / "resources" / "language" / "resource.language.en_gb" / "strings.po")
        zh_ids = _parse_po_ids(ADDON_ROOT / "resources" / "language" / "resource.language.zh_cn" / "strings.po")

        # Every Basic item has localized label & help in both en_gb and zh_cn
        for s in basic:
            lbl = s.attrib.get("label", "")
            hlp = s.attrib.get("help", "")
            self.assertTrue(lbl and hlp, f"{s.attrib['id']} missing label/help")
            self.assertIn(lbl, en_ids)
            self.assertIn(lbl, zh_ids)
            self.assertIn(hlp, en_ids)
            self.assertIn(hlp, zh_ids)

        # Localized spinner for multiversion policy
        mv = next(s for s in settings if s.attrib["id"] == "ce_multiversion_policy")
        ctrl = mv.find("control")
        self.assertIsNotNone(ctrl)
        self.assertEqual(ctrl.attrib.get("type"), "spinner")
        opt_labels = [o.attrib.get("label", "") for o in mv.iter("option")]
        self.assertEqual(len(opt_labels), 3)
        for ol in opt_labels:
            self.assertIn(ol, en_ids)
            self.assertIn(ol, zh_ids)

        # All dependent settings disable cleanly when ce_enabled is false
        for s in settings:
            sid = s.attrib["id"]
            if sid in ("ce_maintenance_menu", "ce_enabled"):
                continue
            deps = [d.attrib.get("type") for d in s.iter("dependency")]
            self.assertIn("enable", deps, f"{sid} missing enable dependency on ce_enabled")

    def test_config_reload_distilled_bundle_inheritance(self) -> None:
        state = config.reload(_FakeAddon({"ce_sync_debounce": "false", "ce_db_indexes": "false", "ce_artwork_307_opt": "false"}))
        self.assertFalse(state["ce_sync_debounce"])
        self.assertFalse(state["ce_sync_fingerprint"])
        self.assertFalse(state["ce_widget_debounce"])
        self.assertFalse(state["ce_pause_sync_during_playback"])
        self.assertFalse(state["ce_db_indexes"])
        self.assertFalse(state["ce_db_pragmas"])
        self.assertFalse(state["ce_artwork_307_opt"])
        self.assertFalse(state["ce_strm_path_fix"])


if __name__ == "__main__":
    unittest.main()
