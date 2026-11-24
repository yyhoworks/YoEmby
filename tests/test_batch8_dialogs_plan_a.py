"""Unit tests for Plan A neutral obsidian dialog polish & legacy XML bug fixes."""

from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ADDON_ROOT = Path(__file__).resolve().parent.parent / "plugin.service.emby-next-gen"
SKIN_DIR = ADDON_ROOT / "resources" / "skins" / "default" / "1080i"


def _control_ids(root: ET.Element) -> set[str]:
    return {el.attrib["id"] for el in root.iter("control") if "id" in el.attrib}


class TestPlanANeutralDialogs(unittest.TestCase):
    def test_all_skin_xmls_parse_cleanly_without_legacy_green_or_typos(self) -> None:
        xml_files = sorted(SKIN_DIR.glob("*.xml"))
        self.assertGreaterEqual(len(xml_files), 10)
        for path in xml_files:
            ET.parse(path)  # Must be strictly well-formed XML
            text = path.read_text(encoding="utf-8")
            lower = text.lower()
            self.assertNotIn("easin=", lower, f"{path.name} still has 'easin=' typo")
            self.assertNotIn("52b54b", lower, f"{path.name} still has legacy Emby green #52b54b")
            self.assertNotIn("388e3c", lower, f"{path.name} still has legacy Emby green #388e3c")
            self.assertNotIn("</align>&gt;", text, f"{path.name} still has stray &gt; entity")

    def test_connect_server_ids_and_safe_horizontal_nav(self) -> None:
        root = ET.parse(SKIN_DIR / "script-emby-connect-server.xml").getroot()
        ids = _control_ids(root)
        for cid in ("100", "101", "102", "150", "155", "201", "202", "203", "204", "205", "206"):
            self.assertIn(cid, ids)
        lst = next(el for el in root.iter("control") if el.attrib.get("id") == "155")
        self.assertEqual(lst.findtext("onleft"), "noop")
        self.assertEqual(lst.findtext("onright"), "noop")

    def test_connect_login_and_manual_preserve_edit_geometry_and_contrast(self) -> None:
        expectations = [
            ("script-emby-connect-login.xml", "470", "660"),
            ("script-emby-connect-login-manual.xml", "470", "470"),
            ("script-emby-connect-server-manual.xml", "470", "470"),
        ]
        for fname, exp_w, exp_h in expectations:
            root = ET.parse(SKIN_DIR / fname).getroot()
            ids = _control_ids(root)
            for cid in ("100", "101", "102", "200", "201", "202", "203"):
                self.assertIn(cid, ids, f"{fname} missing control id {cid}")
            has_geom = any(
                el.findtext("width") == exp_w and el.findtext("height") == exp_h
                for el in root.iter("control")
                if el.attrib.get("type") == "group"
            )
            self.assertTrue(has_geom, f"{fname} must keep {exp_w}x{exp_h} container for Python ControlEdit coordinates")

        login_text = (SKIN_DIR / "script-emby-connect-login.xml").read_text(encoding="utf-8")
        self.assertNotIn("ff464646", login_text.lower())
        self.assertIn("FF9AA4B2", login_text)

    def test_connect_users_white_focus_and_ids(self) -> None:
        root = ET.parse(SKIN_DIR / "script-emby-connect-users.xml").getroot()
        ids = _control_ids(root)
        for cid in ("100", "155", "200", "201"):
            self.assertIn(cid, ids)
        text = (SKIN_DIR / "script-emby-connect-users.xml").read_text(encoding="utf-8")
        self.assertIn('colordiffuse="FFFFFFFF">items/focus_square.png', text)

    def test_resume_dialog_widened_high_contrast_and_safe_nav(self) -> None:
        root = ET.parse(SKIN_DIR / "script-emby-resume.xml").getroot()
        self.assertEqual(root.attrib.get("id"), "3301")
        ids = _control_ids(root)
        for cid in ("100", "3010", "3011"):
            self.assertIn(cid, ids)
        glist = next(el for el in root.iter("control") if el.attrib.get("id") == "100")
        self.assertEqual(glist.findtext("onleft"), "noop")
        self.assertEqual(glist.findtext("onright"), "noop")
        btn = next(el for el in root.iter("control") if el.attrib.get("id") == "3010")
        self.assertEqual(btn.findtext("focusedcolor"), "FF12161F")
        self.assertEqual(btn.find("texturefocus").attrib.get("colordiffuse"), "FFF1F3F5")
        has_wide_group = any(
            el.findtext("width") == "480"
            for el in root.iter("control")
            if el.attrib.get("type") == "group"
        )
        self.assertTrue(has_wide_group)

    def test_python_edit_dialogs_use_neutral_text_color(self) -> None:
        for rel in ("dialogs/loginconnect.py", "dialogs/loginmanual.py", "dialogs/servermanual.py"):
            content = (ADDON_ROOT / rel).read_text(encoding="utf-8")
            self.assertNotIn("FF52b54b", content, f"{rel} still uses legacy green input text")
            self.assertIn('textColor="FFF5F5F7"', content)


if __name__ == "__main__":
    unittest.main()
