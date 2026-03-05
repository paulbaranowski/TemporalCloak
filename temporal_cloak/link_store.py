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
        delivered      INTEGER NOT NULL DEFAULT 0
    );
    """

    def __init__(self, db_path):
        self._db_path = db_path
        self._local = threading.local()
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        # Initialize schema on the calling thread's connection
        self._conn().execute(self.SCHEMA)
        self._conn().commit()

    def _conn(self):
        """Return a per-thread SQLite connection."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    def create(self, link_id, message, image_path, image_filename, created_at,
               burn_after_reading=False):
        self._conn().execute(
            "INSERT INTO links "
            "(link_id, message, image_path, image_filename, created_at, burn_after_reading) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (link_id, message, image_path, image_filename, created_at,
             int(burn_after_reading)),
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
