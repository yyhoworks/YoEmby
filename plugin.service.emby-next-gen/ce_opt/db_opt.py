"""Pure-additive SQLite indexes and CoreELEC PRAGMA tuning for YoEmby.

Strictly respects AGENTS.md YoPlayer DB schema contract:
- NEVER alters, renames, or deletes any existing table or column.
- ONLY creates additive `CREATE INDEX IF NOT EXISTS idx_ce_*` indexes.
"""

from __future__ import annotations

from typing import Any

from . import config

# Sentinel index used to skip redundant DDL checks once applied.
SENTINEL_INDEX = "idx_ce_Episode_PresentationKey"

# Additive indexes targeting verified unindexed WHERE clauses in emby_db.py & YoPlayer queries.
EMBY_ADDITIVE_INDEXES: tuple[tuple[str, str], ...] = (
    ("idx_ce_Movie_PresentationKey", "CREATE INDEX IF NOT EXISTS idx_ce_Movie_PresentationKey ON Movie (EmbyPresentationKey)"),
    ("idx_ce_Episode_PresentationKey", "CREATE INDEX IF NOT EXISTS idx_ce_Episode_PresentationKey ON Episode (EmbyPresentationKey)"),
    ("idx_ce_Series_PresentationKey", "CREATE INDEX IF NOT EXISTS idx_ce_Series_PresentationKey ON Series (EmbyPresentationKey)"),
    ("idx_ce_Season_PresentationKey", "CREATE INDEX IF NOT EXISTS idx_ce_Season_PresentationKey ON Season (EmbyPresentationKey)"),
    ("idx_ce_Episode_KodiParentId", "CREATE INDEX IF NOT EXISTS idx_ce_Episode_KodiParentId ON Episode (KodiParentId)"),
    ("idx_ce_Season_KodiParentId", "CREATE INDEX IF NOT EXISTS idx_ce_Season_KodiParentId ON Season (KodiParentId)"),
    ("idx_ce_Video_KodiId", "CREATE INDEX IF NOT EXISTS idx_ce_Video_KodiId ON Video (KodiId)"),
    ("idx_ce_UpdateItems_LibraryId", "CREATE INDEX IF NOT EXISTS idx_ce_UpdateItems_LibraryId ON UpdateItems (EmbyLibraryId)"),
)


def apply_connection_pragmas(conn: Any, readonly: bool = False) -> None:
    """Apply safe CoreELEC SQLite PRAGMAs on open connections."""
    if not config.is_enabled("ce_db_pragmas"):
        return
    cache_kb = int(config.get("ce_db_cache_kb", 16384))
    try:
        conn.execute(f"PRAGMA cache_size=-{cache_kb}")
        if readonly:
            conn.execute("PRAGMA query_only=ON")
    except Exception:
        pass


def ensure_emby_indexes(cursor: Any, commit_transaction: bool = True) -> int:
    """Create additive `idx_ce_*` indexes on emby_*.db if missing.

    Returns the number of indexes created (0 if already present or disabled).
    """
    if not config.is_enabled("ce_db_indexes"):
        return 0

    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
        (SENTINEL_INDEX,),
    )
    if cursor.fetchone():
        return 0

    created = 0
    for _name, ddl in EMBY_ADDITIVE_INDEXES:
        cursor.execute(ddl)
        created += 1

    cursor.execute("ANALYZE")
    if commit_transaction:
        try:
            cursor.connection.commit()
            cursor.execute("BEGIN IMMEDIATE TRANSACTION")
        except Exception:
            pass
    return created


def drop_emby_indexes(cursor: Any) -> None:
    """Drop `idx_ce_*` indexes during bulk sync (paired with emby_db.delete_Index)."""
    for name, _ddl in EMBY_ADDITIVE_INDEXES:
        try:
            cursor.execute(f"DROP INDEX IF EXISTS {name}")
        except Exception:
            pass
