import os
import sqlite3
import threading


class LinkStore:
    """SQLite-backed persistent storage for link data.

    Each thread gets its own connection via threading.local().
    """

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS links (
        link_id        TEXT PRIMARY KEY,
        message        TEXT NOT NULL,
        image_path     TEXT NOT NULL,
        image_filename TEXT NOT NULL,
        created_at     REAL NOT NULL,
        burn_after_reading INTEGER NOT NULL DEFAULT 0,
        delivered      INTEGER NOT NULL DEFAULT 0,
        mode           TEXT NOT NULL DEFAULT 'distributed',
        dist_key       INTEGER
    );
    """

    def __init__(self, db_path):
        self._db_path = db_path
        self._local = threading.local()
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        # Initialize schema on the calling thread's connection
        self._conn().execute(self.SCHEMA)
        self._conn().commit()
        self._migrate()

    def _migrate(self):
        """Add columns that may not exist in older databases."""
        conn = self._conn()
        cursor = conn.execute("PRAGMA table_info(links)")
        columns = {row[1] for row in cursor.fetchall()}
        if "mode" not in columns:
            conn.execute("ALTER TABLE links ADD COLUMN mode TEXT NOT NULL DEFAULT 'distributed'")
            conn.commit()
        if "dist_key" not in columns:
            conn.execute("ALTER TABLE links ADD COLUMN dist_key INTEGER")
            conn.commit()
        if "fec" not in columns:
            conn.execute("ALTER TABLE links ADD COLUMN fec INTEGER NOT NULL DEFAULT 0")
            conn.commit()

    def _conn(self):
        """Return a per-thread SQLite connection."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    def create(self, link_id, message, image_path, image_filename, created_at,
               burn_after_reading=False, mode="distributed", dist_key=None, fec=False):
        self._conn().execute(
            "INSERT INTO links "
            "(link_id, message, image_path, image_filename, created_at, burn_after_reading, mode, dist_key, fec) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (link_id, message, image_path, image_filename, created_at,
             int(burn_after_reading), mode, dist_key, int(fec)),
        )
        self._conn().commit()

    def get(self, link_id):
        row = self._conn().execute(
            "SELECT * FROM links WHERE link_id = ?", (link_id,)
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def mark_delivered(self, link_id):
        """Mark a link as delivered. If burn_after_reading, delete the row instead."""
        conn = self._conn()
        row = conn.execute(
            "SELECT burn_after_reading FROM links WHERE link_id = ?", (link_id,)
        ).fetchone()
        if row is None:
            return
        if row["burn_after_reading"]:
            conn.execute("DELETE FROM links WHERE link_id = ?", (link_id,))
        else:
            conn.execute(
                "UPDATE links SET delivered = 1 WHERE link_id = ?", (link_id,)
            )
        conn.commit()

    def delete(self, link_id):
        self._conn().execute("DELETE FROM links WHERE link_id = ?", (link_id,))
        self._conn().commit()

    def close(self):
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None
