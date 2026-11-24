"""Unit tests for Batch 2: ce_opt.sync_fast and ce_opt.db_opt."""

from __future__ import annotations

import sqlite3
import sys
import time
import unittest
from pathlib import Path

ADDON_ROOT = Path(__file__).resolve().parent.parent / "plugin.service.emby-next-gen"
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

from ce_opt import config, db_opt, sync_fast


class FakeEmbySQL:
    def __init__(self, existing: set[tuple[str, str]]):
        self.existing = existing

    def get_item_by_id(self, item_id, item_type):
        return (item_id,) if (str(item_id), str(item_type)) in self.existing else None


class TestSyncFingerprint(unittest.TestCase):
    def setUp(self) -> None:
        config.reset_defaults()
        sync_fast.reset_state()

    def tearDown(self) -> None:
        config.reset_defaults()
        sync_fast.reset_state()

    def _sample_episode(self, name: str = "Ep1", played: bool = False) -> dict:
        return {
            "Id": "927075",
            "Type": "Episode",
            "LibraryId": "293420",
            "Name": name,
            "IndexNumber": 1,
            "ParentIndexNumber": 1,
            "SeriesId": "926999",
            "SeasonId": "927000",
            "MediaSources": [
                {
                    "Id": "ms1",
                    "Path": "http://cdn/ep1.mkv",
                    "MediaStreams": [{"Type": "Video", "Index": 0, "Codec": "hevc", "Width": 3840}],
                    "Chapters": [{"StartPositionTicks": 3000000000, "Name": "Intro Start"}],
                }
            ],
            "UserData": {"Played": played, "PlayCount": 1 if played else 0, "PlaybackPositionTicks": 0, "IsFavorite": False},
        }

    def test_duplicate_incremental_update_is_skipped_even_after_mutation(self) -> None:
        sqls = {"emby": FakeEmbySQL({("927075", "Episode")})}

        # First arrival: not cached yet -> must write
        ep1 = self._sample_episode()
        skip, digest = sync_fast.check_or_prepare_fingerprint("srv1", ep1, True, sqls)
        self.assertFalse(skip)
        self.assertIsNotNone(digest)

        # Simulate upstream mutating item in-place during ClassObject.change()
        ep1["MediaSources"][0]["Chapters"][0]["StartPositionTicks"] = 300
        ep1["KodiFullPath"] = "http://127.0.0.1:57342/..."
        sync_fast.commit_fingerprint("srv1", ep1["Id"], digest)

        # Second identical arrival from Emby LibraryChanged -> MUST skip!
        ep2 = self._sample_episode()
        skip2, _ = sync_fast.check_or_prepare_fingerprint("srv1", ep2, True, sqls)
        self.assertTrue(skip2)
        self.assertEqual(sync_fast.get_stats()["fingerprint_skipped"], 1)

        # Playstate change invalidates skip (never drops UserData updates)
        ep3 = self._sample_episode(played=True)
        skip3, _ = sync_fast.check_or_prepare_fingerprint("srv1", ep3, True, sqls)
        self.assertFalse(skip3)

        # Metadata change invalidates skip
        ep4 = self._sample_episode(name="Ep1 Renamed")
        skip4, _ = sync_fast.check_or_prepare_fingerprint("srv1", ep4, True, sqls)
        self.assertFalse(skip4)

        # Full sync (IncrementalSync=False) NEVER skips
        ep5 = self._sample_episode()
        skip5, _ = sync_fast.check_or_prepare_fingerprint("srv1", ep5, False, sqls)
        self.assertFalse(skip5)

    def test_missing_local_row_forces_write(self) -> None:
        sqls_present = {"emby": FakeEmbySQL({("927075", "Episode")})}
        ep = self._sample_episode()
        _, digest = sync_fast.check_or_prepare_fingerprint("srv1", ep, True, sqls_present)
        sync_fast.commit_fingerprint("srv1", ep["Id"], digest)

        # Row removed from emby.db externally -> must NOT skip
        sqls_missing = {"emby": FakeEmbySQL(set())}
        skip, _ = sync_fast.check_or_prepare_fingerprint("srv1", self._sample_episode(), True, sqls_missing)
        self.assertFalse(skip)

    def test_invalidation_and_switch_off(self) -> None:
        sqls = {"emby": FakeEmbySQL({("927075", "Episode")})}
        ep = self._sample_episode()
        _, digest = sync_fast.check_or_prepare_fingerprint("srv1", ep, True, sqls)
        sync_fast.commit_fingerprint("srv1", ep["Id"], digest)

        # Turning flag off restores upstream behavior
        config.set_override(ce_sync_fingerprint=False)
        skip, _ = sync_fast.check_or_prepare_fingerprint("srv1", self._sample_episode(), True, sqls)
        self.assertFalse(skip)

        config.set_override(ce_sync_fingerprint=True)
        sync_fast.invalidate_item_fingerprint("srv1", "927075")
        skip2, _ = sync_fast.check_or_prepare_fingerprint("srv1", self._sample_episode(), True, sqls)
        self.assertFalse(skip2)


class TestCoalescerAndDebouncer(unittest.TestCase):
    def tearDown(self) -> None:
        config.reset_defaults()
        sync_fast.reset_state()

    def test_library_changed_coalesces_burst_and_remove_wins(self) -> None:
        config.set_override(ce_sync_debounce=True, ce_sync_debounce_sec=0.1)
        emitted: list[tuple] = []
        coalescer = sync_fast.LibraryChangedCoalescer(emitted.append)

        # Burst of 3 season updates with overlapping IDs, plus a remove of id 2
        coalescer.submit([], [("1", "unknown", "unknown"), ("2", "unknown", "unknown")])
        coalescer.submit([], [("1", "unknown", "unknown"), ("2", "unknown", "unknown"), ("3", "unknown", "unknown")])
        coalescer.submit(["2"], [("1", "unknown", "unknown"), ("3", "unknown", "unknown"), ("4", "unknown", "unknown")])
        time.sleep(0.25)

        self.assertEqual(len(emitted), 1)
        batch = dict(emitted[0])
        self.assertEqual(batch["remove"], ["2"])
        self.assertEqual([x[0] for x in batch["update"]], ["1", "3", "4"])

    def test_library_changed_passthrough_when_disabled(self) -> None:
        config.set_override(ce_sync_debounce=False)
        emitted: list[tuple] = []
        coalescer = sync_fast.LibraryChangedCoalescer(emitted.append)
        coalescer.submit([], [("10", "unknown", "unknown")])
        coalescer.submit([], [("11", "unknown", "unknown")])
        self.assertEqual(len(emitted), 2)

    def test_widget_debouncer_coalesces_rapid_triggers(self) -> None:
        config.set_override(ce_widget_debounce=True, ce_widget_debounce_sec=0.15)
        debouncer = sync_fast.WidgetRefreshDebouncer()
        calls: list[bool] = []

        self.assertTrue(debouncer.trigger(True, calls.append))  # immediate first run
        self.assertFalse(debouncer.trigger(True, calls.append))  # coalesced
        self.assertFalse(debouncer.trigger(True, calls.append))  # coalesced
        self.assertEqual(len(calls), 1)

        time.sleep(0.25)
        self.assertEqual(len(calls), 2)  # exactly 1 trailing refresh
        debouncer.cancel_all()


class TestDbOpt(unittest.TestCase):
    def tearDown(self) -> None:
        config.reset_defaults()

    def test_additive_indexes_and_pragmas_on_sqlite(self) -> None:
        conn = sqlite3.connect(":memory:")
        cur = conn.cursor()
        cur.execute("CREATE TABLE Movie (EmbyId INTEGER PRIMARY KEY, EmbyPresentationKey TEXT)")
        cur.execute("CREATE TABLE Episode (EmbyId INTEGER PRIMARY KEY, KodiParentId INTEGER, EmbyPresentationKey TEXT)")
        cur.execute("CREATE TABLE Series (EmbyId INTEGER PRIMARY KEY, EmbyPresentationKey TEXT)")
        cur.execute("CREATE TABLE Season (EmbyId INTEGER PRIMARY KEY, KodiParentId INTEGER, EmbyPresentationKey TEXT)")
        cur.execute("CREATE TABLE Video (EmbyId INTEGER PRIMARY KEY, KodiId INTEGER)")
        cur.execute("CREATE TABLE UpdateItems (EmbyId INTEGER, EmbyLibraryId TEXT)")

        created = db_opt.ensure_emby_indexes(cur, commit_transaction=False)
        self.assertEqual(created, len(db_opt.EMBY_ADDITIVE_INDEXES))

        # Second call is idempotent no-op
        self.assertEqual(db_opt.ensure_emby_indexes(cur, commit_transaction=False), 0)

        # Verify query plan uses our new PresentationKey index
        plan = cur.execute("EXPLAIN QUERY PLAN SELECT EmbyId FROM Episode WHERE EmbyPresentationKey = 'abc'").fetchall()
        plan_str = " ".join(str(r) for r in plan)
        self.assertIn("idx_ce_Episode_PresentationKey", plan_str)

        # Drop works cleanly
        db_opt.drop_emby_indexes(cur)
        remaining = cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_ce_%'").fetchall()
        self.assertEqual(remaining, [])

        # PRAGMAs apply cleanly
        db_opt.apply_connection_pragmas(conn, readonly=False)
        cache_sz = cur.execute("PRAGMA cache_size").fetchone()[0]
        self.assertEqual(cache_sz, -int(config.get("ce_db_cache_kb")))
        conn.close()


if __name__ == "__main__":
    unittest.main()
