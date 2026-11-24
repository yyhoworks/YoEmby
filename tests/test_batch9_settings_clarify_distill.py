"""Unit tests for Batch 9: settings.xml Clarify + Distill (100% help coverage, disambiguation & reversible Lite Mode hiding)."""

from __future__ import annotations

import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ADDON_ROOT = Path(__file__).resolve().parent.parent / "plugin.service.emby-next-gen"
SETTINGS_XML = ADDON_ROOT / "resources" / "settings.xml"
PO_EN = ADDON_ROOT / "resources" / "language" / "resource.language.en_gb" / "strings.po"
PO_ZH = ADDON_ROOT / "resources" / "language" / "resource.language.zh_cn" / "strings.po"


def _parse_po_catalog(po_path: Path) -> dict[str, tuple[str, str]]:
    """Parse both single-line and multiline gettext entries into {id: (msgid, msgstr)}."""
    text = po_path.read_text(encoding="utf-8")
    catalog: dict[str, tuple[str, str]] = {}
    blocks = re.split(r"\n\s*\n", text)
    for block in blocks:
        m_id = re.search(r'msgctxt\s+"#(\d+)"', block)
        if not m_id:
            continue
        sid = m_id.group(1)
        m_split = re.search(r'\bmsgid\s+(.*?)\nmsgstr\s+(.*)', block, re.S)
        if not m_split:
            continue
        msgid = "".join(re.findall(r'"((?:\\.|[^"\\])*)"', m_split.group(1)))
        msgstr = "".join(re.findall(r'"((?:\\.|[^"\\])*)"', m_split.group(2)))
        catalog[sid] = (msgid, msgstr)
    return catalog


def _has_lite_mode_hide_dep(setting: ET.Element) -> bool:
    for dep in setting.iter("dependency"):
        if dep.attrib.get("type") != "visible":
            continue
        for cond in dep.iter("condition"):
            if (
                cond.attrib.get("setting") == "ce_lite_mode"
                and cond.attrib.get("operator") == "is"
                and (cond.text or "").strip() == "false"
            ):
                return True
    return False


class TestSettingsClarifyAndDistill(unittest.TestCase):
    def setUp(self) -> None:
        self.root = ET.parse(SETTINGS_XML).getroot()
        self.en = _parse_po_catalog(PO_EN)
        self.zh = _parse_po_catalog(PO_ZH)

    def test_all_visible_settings_have_valid_en_and_zh_label_and_help(self) -> None:
        checked = 0
        for cat in self.root.iter("category"):
            if cat.findtext("visible") == "false":
                continue
            for grp in cat.iter("group"):
                if grp.findtext("visible") == "false":
                    continue
                for s in grp.findall("setting"):
                    if s.findtext("visible") == "false":
                        continue
                    sid = s.attrib["id"]
                    lbl = s.attrib.get("label", "")
                    hlp = s.attrib.get("help", "")
                    self.assertTrue(lbl, f"Visible setting '{sid}' missing label ID")
                    self.assertTrue(hlp, f"Visible setting '{sid}' missing help ID")
                    self.assertIn(lbl, self.en, f"Setting '{sid}' label #{lbl} missing in en_gb")
                    self.assertIn(lbl, self.zh, f"Setting '{sid}' label #{lbl} missing in zh_cn")
                    self.assertTrue(self.zh[lbl][1] or self.zh[lbl][0], f"Setting '{sid}' label #{lbl} empty in zh_cn")
                    self.assertIn(hlp, self.en, f"Setting '{sid}' help #{hlp} missing in en_gb")
                    self.assertIn(hlp, self.zh, f"Setting '{sid}' help #{hlp} missing in zh_cn")
                    self.assertTrue(self.en[hlp][0], f"Setting '{sid}' help #{hlp} empty in en_gb")
                    self.assertTrue(self.zh[hlp][1], f"Setting '{sid}' help #{hlp} empty in zh_cn")
                    checked += 1
        self.assertGreaterEqual(checked, 85)

    def test_interface_notification_durations_disambiguated_and_l0_debug_demoted(self) -> None:
        iface = next(c for c in self.root.iter("category") if c.attrib.get("id") == "Interface")
        settings = {s.attrib["id"]: s for s in iface.iter("setting")}

        dm_lbl = self.zh[settings["displayMessage"].attrib["label"]][1]
        nc_lbl = self.zh[settings["newContentTime"].attrib["label"]][1]
        self.assertNotEqual(dm_lbl, nc_lbl)
        self.assertIn("常规通知", dm_lbl)
        self.assertIn("新内容", nc_lbl)

        # Skin debug items moved out of L0 Basic into L3 Expert
        for sid in ("animateicon", "refreshskin", "skinreload"):
            self.assertEqual(settings[sid].findtext("level"), "3", f"{sid} should be L3 Expert")

        # Interface has zero L0 clutter left
        visible_l0 = [
            s.attrib["id"]
            for grp in iface.iter("group")
            if grp.findtext("visible") != "false"
            for s in grp.findall("setting")
            if s.findtext("visible") != "false" and s.findtext("level", "0") == "0"
        ]
        self.assertEqual(visible_l0, [])

    def test_lite_mode_reversible_visibility_dependencies(self) -> None:
        all_settings = {s.attrib["id"]: s for s in self.root.iter("setting")}
        expected_lite_hidden = (
            "enableContextDelete",
            "enableContextRemoteOptions",
            "enableContextDownloadOptions",
            "enableContextRecordingOptions",
            "enableContextSimilarOptions",
            "enableContextSettingsOptions",
            "enableContextPlayRandom",
            "skipintroembuarydesign",
            "offerDelete",
            "deleteTV",
            "deleteMovies",
        )
        for sid in expected_lite_hidden:
            self.assertIn(sid, all_settings)
            self.assertTrue(
                _has_lite_mode_hide_dep(all_settings[sid]),
                f"{sid} missing reversible ce_lite_mode=false visibility dependency",
            )

        # Kept context switches stay visible in Lite Mode
        for kept in (
            "enableContextFavouriteOptions",
            "enableContextSpecialsOptions",
            "enableContextRefreshOptions",
            "enableContextGotoOptions",
        ):
            self.assertFalse(_has_lite_mode_hide_dep(all_settings[kept]))

    def test_ce_opt_split_into_core_and_expert_groups_and_vacuum_help_fixed(self) -> None:
        ce_cat = next(c for c in self.root.iter("category") if c.attrib.get("id") == "ce_opt")
        groups = ce_cat.findall("group")
        self.assertEqual(len(groups), 2)
        self.assertEqual(len(groups[0].findall("setting")), 4)
        self.assertEqual(len(groups[1].findall("setting")), 7)

        all_settings = {s.attrib["id"]: s for s in self.root.iter("setting")}
        self.assertEqual(all_settings["databasevacuummanual"].attrib.get("help"), "33953")
        self.assertEqual(all_settings["AutoSelectHighestResolution"].attrib.get("help"), "33947")


if __name__ == "__main__":
    unittest.main()
