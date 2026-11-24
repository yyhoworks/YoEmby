"""Unit tests for Batch 5: skin-driven maintenance menu, neutral TV overlays & distilled settings."""

from __future__ import annotations

import re
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ADDON_ROOT = Path(__file__).resolve().parent.parent / "plugin.service.emby-next-gen"
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

from ce_opt import config, maintenance


def _parse_po_ids(po_path: Path) -> set[str]:
    text = po_path.read_text(encoding="utf-8")
    return set(re.findall(r'msgctxt "#(\d+)"', text))


class _FakeAddon:
    def __init__(self, values: dict[str, str]):
        self._values = values

    def getSetting(self, key: str) -> str:
        return self._values.get(key, "")


class TestSkinDrivenMaintenanceMenu(unittest.TestCase):
    def test_fmt_size_auto_gb_and_mb(self) -> None:
        self.assertEqual(maintenance._fmt_mb(0), "0.0 MB")
        self.assertEqual(maintenance._fmt_mb(33 * 1024 * 1024), "33.0 MB")
        self.assertEqual(maintenance._fmt_mb(int(1.26 * 1024 * 1024 * 1024)), "1.26 GB")

    def test_menu_entries_plain_text_and_theme_neutral(self) -> None:
        report_issues = {
            "storage": {
                "video_db_bytes": 124 * 1024 * 1024,
                "emby_db_bytes": 26 * 1024 * 1024,
                "textures_db_bytes": 8 * 1024 * 1024,
                "thumbnails_bytes": 1355 * 1024 * 1024,
                "temp_bytes": 74 * 1024 * 1024,
                "rollback_bytes": 33 * 1024 * 1024,
                "rollback_files": 262,
            },
            "emby_db": {
                "ce_indexes_present": 8,
                "ce_indexes_expected": 8,
                "items_missing_videostreams": 417,
            },
            "video_db": {},
            "runtime_stats": {},
            "config": {"ce_enabled": True, "ce_multiversion_policy": "prefer_local"},
        }
        entries = maintenance.build_menu_entries(report_issues)
        self.assertEqual(len(entries), 4)
        for line in entries:
            self.assertNotIn("[COLOR", line)
        self.assertIn("2 项可优化", entries[0])
        self.assertIn("GB", entries[0])
        self.assertIn("417 条缺流", entries[1])
        self.assertIn("33.0 MB", entries[2])
        self.assertIn("8 / 8", entries[3])

        # Healthy state & localized policy in textviewer report
        report_ok = {
            "storage": {"thumbnails_bytes": 10 * 1024 * 1024},
            "emby_db": {"ce_indexes_present": 8, "ce_indexes_expected": 8, "items_missing_videostreams": 0},
            "video_db": {},
            "runtime_stats": {},
            "config": {"ce_enabled": True, "ce_multiversion_policy": "prefer_local"},
        }
        entries_ok = maintenance.build_menu_entries(report_ok)
        self.assertIn("全部健康", entries_ok[0])
        self.assertIn("流信息完整", entries_ok[1])
        self.assertIn("已清空", entries_ok[2])
        txt = maintenance.format_health_report(report_ok)
        self.assertIn("优先本地存储", txt)
        self.assertNotIn("[COLOR", txt)


class TestNeutralTvOverlaysAndDistilledSettings(unittest.TestCase):
    def tearDown(self) -> None:
        config.reset_defaults()

    def test_skin_xml_files_well_formed_and_neutral_without_custom_maint_dialog(self) -> None:
        skin_dir = ADDON_ROOT / "resources" / "skins" / "default" / "1080i"

        # Skin-driven: no custom plugin maintenance XML fighting skin theme
        self.assertFalse((skin_dir / "script-emby-ce-maintenance.xml").exists())

        # Neutral bottom-right skip dialogs (clear of subtitle band, no garish amber block)
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
            self.assertEqual(btn.findtext("focusedcolor"), "FFFFFFFF")
            self.assertNotEqual(btn.find("texturefocus").attrib.get("colordiffuse"), "FFF59E0B")

        # Context menu: neutral translucent focus & safe horizontal nav (no accidental close)
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

        for s in basic:
            lbl = s.attrib.get("label", "")
            hlp = s.attrib.get("help", "")
            self.assertTrue(lbl and hlp, f"{s.attrib['id']} missing label/help")
            self.assertIn(lbl, en_ids)
            self.assertIn(lbl, zh_ids)
            self.assertIn(hlp, en_ids)
            self.assertIn(hlp, zh_ids)

        mv = next(s for s in settings if s.attrib["id"] == "ce_multiversion_policy")
        ctrl = mv.find("control")
        self.assertIsNotNone(ctrl)
        self.assertEqual(ctrl.attrib.get("type"), "spinner")
        opt_labels = [o.attrib.get("label", "") for o in mv.iter("option")]
        self.assertEqual(len(opt_labels), 3)
        for ol in opt_labels:
            self.assertIn(ol, en_ids)
            self.assertIn(ol, zh_ids)

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
