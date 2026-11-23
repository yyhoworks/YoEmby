#!/usr/bin/env python3
"""Mechanical guardrail checks for YoEmby.

Enforces:
1. Locked addon ID ('plugin.service.emby-next-gen'), version ('12.4.24'), and ASCII display name ('YoEmby').
2. YoPlayer read-only SQLite schema contract in emby_db.py.
3. No leaked user data / credentials / build artifacts inside plugin.service.emby-next-gen/.
4. Python syntax compilation across plugin, scripts, and tests.
5. Upstream diff bloat audit against tag 'upstream-12.4.24' (excluding ce_opt/).
6. Local unittest suite under tests/ (when present).
"""

from __future__ import annotations

import compileall
import os
import re
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ADDON_DIR = REPO_ROOT / "plugin.service.emby-next-gen"
ADDON_XML = ADDON_DIR / "addon.xml"
EMBY_DB_PY = ADDON_DIR / "database" / "emby_db.py"
TESTS_DIR = REPO_ROOT / "tests"

EXPECTED_ADDON_ID = "plugin.service.emby-next-gen"
EXPECTED_ADDON_VERSION = "12.4.24"
EXPECTED_ADDON_NAME = "YoEmby"
UPSTREAM_BASELINE_TAG = "upstream-12.4.24"
UPSTREAM_FILE_ADD_WARN_LIMIT = 80

# YoPlayer contract: required tables and column names in emby_db.py CREATE TABLE statements.
REQUIRED_EMBY_SCHEMA: dict[str, tuple[str, ...]] = {
    "Movie": ("EmbyId", "KodiId", "KodiFileId", "KodiPathId"),
    "Video": ("EmbyId", "KodiId", "KodiFileId", "KodiPathId"),
    "Series": ("EmbyId", "KodiId", "KodiPathId"),
    "Season": ("EmbyId", "KodiId", "KodiParentId"),
    "Episode": ("EmbyId", "KodiId", "KodiFileId", "KodiPathId"),
    "MediaSources": ("EmbyId", "MediaSourceId", "Path"),
    "AudioStreams": ("EmbyId", "StreamIndex", "DisplayTitle", "Codec"),
    "Subtitles": ("EmbyId", "StreamIndex", "DisplayTitle", "Codec", "Language", "External"),
    "LibrarySynced": ("EmbyLibraryId", "EmbyLibraryName", "EmbyType"),
    "EmbyLibraryMapping": ("EmbyLibraryId", "EmbyId"),
}

FORBIDDEN_ADDON_PATTERNS = (
    re.compile(r"^servers_.*\.json$", re.IGNORECASE),
    re.compile(r".*\.db(-wal|-shm)?$", re.IGNORECASE),
    re.compile(r".*\.zip$", re.IGNORECASE),
)


def check_addon_xml(errors: list[str]) -> None:
    if not ADDON_XML.is_file():
        errors.append(f"Missing {ADDON_XML}")
        return
    tree = ET.parse(ADDON_XML)
    root = tree.getroot()
    addon_id = root.attrib.get("id", "")
    version = root.attrib.get("version", "")
    name = root.attrib.get("name", "")

    if addon_id != EXPECTED_ADDON_ID:
        errors.append(f"addon.xml id mismatch: got '{addon_id}', must stay '{EXPECTED_ADDON_ID}' (YoPlayer contract)")
    if version != EXPECTED_ADDON_VERSION:
        errors.append(
            f"addon.xml version mismatch: got '{version}', must stay '{EXPECTED_ADDON_VERSION}' "
            "(YoPlayer VERIFIED_VERSIONS whitelist)"
        )
    if name != EXPECTED_ADDON_NAME or not name.isascii():
        errors.append(f"addon.xml name mismatch: got '{name}', expected ASCII '{EXPECTED_ADDON_NAME}'")
    print(f"[OK] addon.xml: id={addon_id}, name={name}, version={version}")


def check_emby_schema_contract(errors: list[str]) -> None:
    if not EMBY_DB_PY.is_file():
        errors.append(f"Missing {EMBY_DB_PY}")
        return
    text = EMBY_DB_PY.read_text(encoding="utf-8")
    for table, cols in REQUIRED_EMBY_SCHEMA.items():
        m = re.search(rf"CREATE TABLE IF NOT EXISTS {table}\s*\(([^)]+)\)", text)
        if not m:
            errors.append(f"emby_db.py missing CREATE TABLE for required YoPlayer table '{table}'")
            continue
        body = m.group(1)
        for col in cols:
            if not re.search(rf"\b{re.escape(col)}\b", body):
                errors.append(f"emby_db.py table '{table}' missing required column '{col}'")
    if not errors:
        print(f"[OK] emby_db.py schema contract verified ({len(REQUIRED_EMBY_SCHEMA)} tables)")


def check_forbidden_files(errors: list[str]) -> None:
    bad: list[str] = []
    for root, dirs, files in os.walk(ADDON_DIR):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fname in files:
            rel = Path(root, fname).relative_to(ADDON_DIR)
            if fname.lower() == "settings.xml" and rel.parts != ("resources", "settings.xml"):
                bad.append(str(rel))
                continue
            if any(pat.match(fname) for pat in FORBIDDEN_ADDON_PATTERNS):
                bad.append(str(rel))
    if bad:
        errors.append(f"Forbidden runtime/secret/archive files inside addon dir: {', '.join(bad)}")
    else:
        print("[OK] No forbidden runtime/secret files in addon directory")


def check_python_syntax(errors: list[str]) -> None:
    targets = [ADDON_DIR, REPO_ROOT / "scripts"]
    if TESTS_DIR.is_dir():
        targets.append(TESTS_DIR)
    for target in targets:
        ok = compileall.compile_dir(str(target), quiet=1, force=False)
        if not ok:
            errors.append(f"Python syntax check failed in {target}")
    if not errors:
        print("[OK] Python syntax check passed")


def audit_upstream_diff(warnings: list[str]) -> None:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", UPSTREAM_BASELINE_TAG],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            warnings.append(f"Git tag '{UPSTREAM_BASELINE_TAG}' not found; skipping upstream diff audit")
            return

        diff = subprocess.run(
            ["git", "diff", UPSTREAM_BASELINE_TAG, "--numstat", "--", "plugin.service.emby-next-gen/"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        warnings.append(f"Skipping git diff audit: {exc}")
        return

    upstream_files = 0
    upstream_added = 0
    ce_opt_added = 0
    for line in diff.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 3 or parts[0] == "-":
            continue
        added, _deleted, path = int(parts[0]), int(parts[1]), parts[2]
        if "/ce_opt/" in path:
            ce_opt_added += added
        else:
            upstream_files += 1
            upstream_added += added
            if added > UPSTREAM_FILE_ADD_WARN_LIMIT:
                warnings.append(
                    f"Upstream file '{path}' has +{added} lines vs {UPSTREAM_BASELINE_TAG} "
                    f"(>{UPSTREAM_FILE_ADD_WARN_LIMIT}); consider moving logic into ce_opt/"
                )
    print(
        f"[INFO] Diff vs {UPSTREAM_BASELINE_TAG}: "
        f"{upstream_files} upstream file(s) (+{upstream_added} lines), ce_opt/ (+{ce_opt_added} lines)"
    )


def run_unit_tests(errors: list[str]) -> None:
    if not TESTS_DIR.is_dir():
        print("[INFO] No tests/ directory yet (skipping unittest)")
        return
    suite = unittest.defaultTestLoader.discover(str(TESTS_DIR), pattern="test_*.py")
    count = suite.countTestCases()
    if count == 0:
        print("[INFO] No test_*.py files found in tests/ yet")
        return
    runner = unittest.TextTestRunner(verbosity=1)
    result = runner.run(suite)
    if not result.wasSuccessful():
        errors.append(f"Unit tests failed ({len(result.failures)} failures, {len(result.errors)} errors)")
    else:
        print(f"[OK] Unit tests passed ({count} tests)")


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    check_addon_xml(errors)
    check_emby_schema_contract(errors)
    check_forbidden_files(errors)
    check_python_syntax(errors)
    audit_upstream_diff(warnings)
    run_unit_tests(errors)

    for warn in warnings:
        print(f"[WARN] {warn}")
    if errors:
        print("\n=== GUARDRAIL CHECK FAILED ===")
        for err in errors:
            print(f"[FAIL] {err}")
        return 1

    print("\n=== ALL GUARDRAILS PASSED ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
