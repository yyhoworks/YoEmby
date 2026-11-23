"""Incremental SQLite indexes for emby_*.db.

Adds read-accelerating indexes on KodiId and KodiFileId for Movie, Series,
Season, and Episode tables without modifying any table schema or columns.
"""

from ce_opt import config

EXTRA_INDEXES = (
    ("idx_Movie_KodiId", "Movie", "KodiId"),
    ("idx_Movie_KodiFileId", "Movie", "KodiFileId"),
    ("idx_Series_KodiId", "Series", "KodiId"),
    ("idx_Season_KodiId", "Season", "KodiId"),
    ("idx_Episode_KodiId", "Episode", "KodiId"),
    ("idx_Episode_KodiFileId", "Episode", "KodiFileId"),
)


def ensure_kodi_id_indexes(cursor):
    """Idempotently create missing KodiId/KodiFileId indexes on emby_*.db.

    Returns the number of indexes created. Safe to call on every startup;
    when all indexes already exist this performs a single sqlite_master lookup.
    """
    if not config.is_enabled("EXTRA_EMBY_INDEXES"):
        return 0

    names = tuple(item[0] for item in EXTRA_INDEXES)
    placeholders = ",".join("?" for _ in names)
    cursor.execute(
        f"SELECT name FROM sqlite_master WHERE type='index' AND name IN ({placeholders})",
        names,
    )
    existing = {row[0] for row in cursor.fetchall()}

    missing = [item for item in EXTRA_INDEXES if item[0] not in existing]
    if not missing:
        return 0

    for idx_name, table_name, col_name in missing:
        cursor.execute(
            f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table_name} ({col_name})"
        )

    cursor.execute("ANALYZE")
    conn = cursor.connection
    if conn.in_transaction:
        conn.commit()
        cursor.execute("BEGIN IMMEDIATE TRANSACTION")
    else:
        conn.commit()

    return len(missing)


def drop_kodi_id_indexes(cursor):
    """Drop extra KodiId/KodiFileId indexes before bulk re-import."""
    for idx_name, _, _ in EXTRA_INDEXES:
        cursor.execute(f"DROP INDEX IF EXISTS {idx_name}")
