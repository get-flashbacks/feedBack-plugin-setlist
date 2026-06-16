"""Setlist Builder plugin — create and manage ordered song playlists."""

import json
import sqlite3
import threading
from pathlib import Path

_db_path = None
_conn = None
_lock = threading.Lock()


def _get_conn():
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(_db_path, check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS setlists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS setlist_songs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                setlist_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                title TEXT,
                artist TEXT,
                position INTEGER NOT NULL,
                arrangement TEXT,
                FOREIGN KEY (setlist_id) REFERENCES setlists(id) ON DELETE CASCADE
            )
        """)
        _conn.commit()
    return _conn


def setup(app, context):
    global _db_path
    config_dir = context["config_dir"]
    _db_path = str(config_dir / "setlists.db")
    meta_db = context["meta_db"]

    @app.get("/api/plugins/setlist/list")
    def list_setlists():
        conn = _get_conn()
        rows = conn.execute(
            "SELECT s.id, s.name, s.created_at, s.updated_at, "
            "(SELECT COUNT(*) FROM setlist_songs WHERE setlist_id = s.id) as song_count "
            "FROM setlists s ORDER BY s.updated_at DESC"
        ).fetchall()
        return [
            {"id": r[0], "name": r[1], "created_at": r[2], "updated_at": r[3],
             "song_count": r[4]}
            for r in rows
        ]

    @app.post("/api/plugins/setlist/create")
    def create_setlist(data: dict):
        name = data.get("name", "").strip()
        if not name:
            return {"error": "Name required"}
        conn = _get_conn()
        with _lock:
            cur = conn.execute("INSERT INTO setlists (name) VALUES (?)", (name,))
            conn.commit()
            return {"id": cur.lastrowid, "name": name}

    @app.delete("/api/plugins/setlist/{setlist_id}")
    def delete_setlist(setlist_id: int):
        conn = _get_conn()
        with _lock:
            conn.execute("DELETE FROM setlist_songs WHERE setlist_id = ?", (setlist_id,))
            conn.execute("DELETE FROM setlists WHERE id = ?", (setlist_id,))
            conn.commit()
        return {"ok": True}

    @app.post("/api/plugins/setlist/{setlist_id}/rename")
    def rename_setlist(setlist_id: int, data: dict):
        name = data.get("name", "").strip()
        if not name:
            return {"error": "Name required"}
        conn = _get_conn()
        with _lock:
            conn.execute("UPDATE setlists SET name = ?, updated_at = datetime('now') WHERE id = ?",
                         (name, setlist_id))
            conn.commit()
        return {"ok": True}

    @app.get("/api/plugins/setlist/{setlist_id}")
    def get_setlist(setlist_id: int):
        conn = _get_conn()
        setlist = conn.execute(
            "SELECT id, name, created_at FROM setlists WHERE id = ?", (setlist_id,)
        ).fetchone()
        if not setlist:
            return {"error": "Not found"}

        songs = conn.execute(
            "SELECT id, filename, title, artist, position, arrangement "
            "FROM setlist_songs WHERE setlist_id = ? ORDER BY position",
            (setlist_id,)
        ).fetchall()

        return {
            "id": setlist[0], "name": setlist[1], "created_at": setlist[2],
            "songs": [
                {"id": r[0], "filename": r[1], "title": r[2], "artist": r[3],
                 "position": r[4], "arrangement": r[5]}
                for r in songs
            ],
        }

    @app.post("/api/plugins/setlist/{setlist_id}/add")
    def add_to_setlist(setlist_id: int, data: dict):
        filename = data.get("filename", "")
        if not filename:
            return {"error": "No filename"}
        conn = _get_conn()
        with _lock:
            # Get next position
            row = conn.execute(
                "SELECT COALESCE(MAX(position), 0) FROM setlist_songs WHERE setlist_id = ?",
                (setlist_id,)
            ).fetchone()
            pos = row[0] + 1
            conn.execute(
                "INSERT INTO setlist_songs (setlist_id, filename, title, artist, position, arrangement) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (setlist_id, filename, data.get("title", ""), data.get("artist", ""),
                 pos, data.get("arrangement", ""))
            )
            conn.execute("UPDATE setlists SET updated_at = datetime('now') WHERE id = ?", (setlist_id,))
            conn.commit()
        return {"ok": True, "position": pos}

    @app.delete("/api/plugins/setlist/{setlist_id}/song/{song_id}")
    def remove_from_setlist(setlist_id: int, song_id: int):
        conn = _get_conn()
        with _lock:
            conn.execute("DELETE FROM setlist_songs WHERE id = ? AND setlist_id = ?",
                         (song_id, setlist_id))
            # Re-number positions
            songs = conn.execute(
                "SELECT id FROM setlist_songs WHERE setlist_id = ? ORDER BY position",
                (setlist_id,)
            ).fetchall()
            for i, (sid,) in enumerate(songs):
                conn.execute("UPDATE setlist_songs SET position = ? WHERE id = ?", (i + 1, sid))
            conn.execute("UPDATE setlists SET updated_at = datetime('now') WHERE id = ?", (setlist_id,))
            conn.commit()
        return {"ok": True}

    @app.post("/api/plugins/setlist/{setlist_id}/reorder")
    def reorder_setlist(setlist_id: int, data: dict):
        """Reorder songs. data = {"song_ids": [3, 1, 2]}"""
        song_ids = data.get("song_ids", [])
        if not song_ids:
            return {"error": "No song IDs"}
        conn = _get_conn()
        with _lock:
            for i, sid in enumerate(song_ids):
                conn.execute(
                    "UPDATE setlist_songs SET position = ? WHERE id = ? AND setlist_id = ?",
                    (i + 1, sid, setlist_id)
                )
            conn.execute("UPDATE setlists SET updated_at = datetime('now') WHERE id = ?", (setlist_id,))
            conn.commit()
        return {"ok": True}
