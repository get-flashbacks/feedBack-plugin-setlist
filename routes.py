"""Setlist Builder plugin — create and manage ordered song playlists."""

import sqlite3
import threading
from contextlib import contextmanager

from fastapi.responses import JSONResponse

_db_path = None
_conn = None
_lock = threading.Lock()

# `datetime('now')` truncates to whole seconds, so two mutations within the
# same second produced an identical `updated_at` and left the list's
# "most recently updated first" ordering up to whatever sqlite returned. Use
# millisecond precision. The stored format stays lexicographically sortable
# against older second-precision rows: "HH:MM:SS" sorts before "HH:MM:SS.mmm"
# because the prefix is shared.
_NOW = "strftime('%Y-%m-%d %H:%M:%f', 'now')"


def _clean_name(data: dict) -> str:
    """Extract and trim the "name" field from a request body.

    `data.get("name", "")` alone assumes the field is a string whenever
    it's present — a client sending `{"name": null}` or `{"name": 123}`
    (FastAPI's bare `dict` param accepts any JSON object shape) made the
    unconditional `.strip()` raise `AttributeError` and 500 the request
    instead of the intended "Name required" 400.
    """
    name = data.get("name", "")
    return name.strip() if isinstance(name, str) else ""


def _clean_field(data: dict, key: str) -> str:
    """Read a free-text field, coercing non-strings to "".

    The same shape assumption `_clean_name` guards against applied to every
    denormalized song field: a client posting `{"filename": ["a"]}` reached
    sqlite3 and raised `InterfaceError: Error binding parameter 1`, surfacing
    as an opaque 500. Rejecting non-strings up front turns those into the
    documented 400.
    """
    value = data.get(key, "")
    return value if isinstance(value, str) else ""


def _reset_conn():
    """Close and drop the cached connection. Used by `setup` and by tests."""
    global _conn
    with _lock:
        if _conn is not None:
            try:
                _conn.close()
            except sqlite3.Error:
                pass
            _conn = None


def _get_conn():
    # Fast path outside the lock: once _conn is set, every caller just reads
    # it. FastAPI runs these sync `def` routes in a threadpool, so without
    # locking the slow path, two concurrent first requests can each pass the
    # `_conn is None` check, open their own sqlite3.connect(), and race to
    # assign _conn — the loser's connection (and any writes made through it
    # before the race resolves) is silently discarded.
    global _conn
    if _conn is not None:
        return _conn
    with _lock:
        if _conn is None:
            conn = sqlite3.connect(_db_path, check_same_thread=False)
            # `PRAGMA foreign_keys` defaults to OFF in SQLite and is
            # per-connection, so the `ON DELETE CASCADE` declared on
            # setlist_songs was never enforced. delete_setlist masks this by
            # deleting children explicitly, but songs added against a
            # nonexistent setlist were kept forever as orphans. Turning
            # enforcement on makes the schema honest; the explicit child
            # delete stays because it also covers databases created before
            # this pragma existed.
            conn.execute("PRAGMA foreign_keys=ON")
            # Wait instead of raising "database is locked" when another
            # process (host app, maintenance script) holds a write txn.
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS setlists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    created_at TEXT DEFAULT ({_NOW}),
                    updated_at TEXT DEFAULT ({_NOW})
                )
            """)
            conn.execute("""
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
            # Every query here (list's per-row COUNT subquery, get_setlist's
            # WHERE setlist_id ORDER BY position, add's MAX(position) lookup,
            # remove/reorder's per-song updates) filters on setlist_id.
            # Without an index each of those does a full table scan of
            # setlist_songs.
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_setlist_songs_setlist_id "
                "ON setlist_songs(setlist_id)"
            )
            conn.commit()
            _conn = conn
    return _conn


def _error(message: str, status: int):
    return JSONResponse({"error": message}, status)


def _setlist_exists(conn, setlist_id: int) -> bool:
    return conn.execute(
        "SELECT 1 FROM setlists WHERE id = ?", (setlist_id,)
    ).fetchone() is not None


@contextmanager
def _write(conn):
    """Serialize a write transaction, rolling back if any statement fails.

    Every mutating route shares one connection, so an exception mid-sequence
    would otherwise leave a partially-applied transaction open for the next
    request to reuse.
    """
    with _lock:
        try:
            yield
        except Exception:
            conn.rollback()
            raise
        else:
            conn.commit()


def _touch(conn, setlist_id: int):
    conn.execute(
        f"UPDATE setlists SET updated_at = {_NOW} WHERE id = ?", (setlist_id,)
    )


def setup(app, context):
    global _db_path
    config_dir = context["config_dir"]
    _db_path = str(config_dir / "setlists.db")

    # setup() can run more than once (tests, or a host that remounts
    # plugins). Without this, a second call kept serving the *previous* db
    # path through the cached module-global connection.
    _reset_conn()

    @app.get("/api/plugins/setlist/list")
    def list_setlists():
        conn = _get_conn()
        rows = conn.execute(
            "SELECT s.id, s.name, s.created_at, s.updated_at, "
            "(SELECT COUNT(*) FROM setlist_songs WHERE setlist_id = s.id) as song_count "
            "FROM setlists s ORDER BY s.updated_at DESC, s.id DESC"
        ).fetchall()
        return [
            {"id": r[0], "name": r[1], "created_at": r[2], "updated_at": r[3],
             "song_count": r[4]}
            for r in rows
        ]

    @app.post("/api/plugins/setlist/create")
    def create_setlist(data: dict):
        name = _clean_name(data)
        if not name:
            return _error("Name required", 400)
        conn = _get_conn()
        with _write(conn):
            cur = conn.execute("INSERT INTO setlists (name) VALUES (?)", (name,))
            return {"id": cur.lastrowid, "name": name}

    @app.delete("/api/plugins/setlist/{setlist_id}")
    def delete_setlist(setlist_id: int):
        conn = _get_conn()
        with _write(conn):
            # Explicit child delete: correct on databases created before
            # PRAGMA foreign_keys=ON, and a no-op once the cascade is live.
            conn.execute("DELETE FROM setlist_songs WHERE setlist_id = ?", (setlist_id,))
            deleted = conn.execute(
                "DELETE FROM setlists WHERE id = ?", (setlist_id,)
            ).rowcount
        if not deleted:
            return _error("Not found", 404)
        return {"ok": True}

    @app.post("/api/plugins/setlist/{setlist_id}/rename")
    def rename_setlist(setlist_id: int, data: dict):
        name = _clean_name(data)
        if not name:
            return _error("Name required", 400)
        conn = _get_conn()
        with _write(conn):
            if not _setlist_exists(conn, setlist_id):
                return _error("Not found", 404)
            conn.execute("UPDATE setlists SET name = ? WHERE id = ?", (name, setlist_id))
            _touch(conn, setlist_id)
        return {"ok": True}

    @app.get("/api/plugins/setlist/{setlist_id}")
    def get_setlist(setlist_id: int):
        conn = _get_conn()
        setlist = conn.execute(
            "SELECT id, name, created_at FROM setlists WHERE id = ?", (setlist_id,)
        ).fetchone()
        if not setlist:
            return _error("Not found", 404)

        songs = conn.execute(
            "SELECT id, filename, title, artist, position, arrangement "
            "FROM setlist_songs WHERE setlist_id = ? ORDER BY position, id",
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
        filename = _clean_field(data, "filename").strip()
        if not filename:
            return _error("No filename", 400)
        conn = _get_conn()
        with _write(conn):
            if not _setlist_exists(conn, setlist_id):
                # Without this check the insert succeeded and left a
                # permanently orphaned row pointing at a setlist that does
                # not exist, while still reporting ok:true.
                return _error("Not found", 404)
            row = conn.execute(
                "SELECT COALESCE(MAX(position), 0) FROM setlist_songs WHERE setlist_id = ?",
                (setlist_id,)
            ).fetchone()
            pos = row[0] + 1
            conn.execute(
                "INSERT INTO setlist_songs (setlist_id, filename, title, artist, position, arrangement) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (setlist_id, filename, _clean_field(data, "title"),
                 _clean_field(data, "artist"), pos,
                 _clean_field(data, "arrangement"))
            )
            _touch(conn, setlist_id)
        return {"ok": True, "position": pos}

    @app.delete("/api/plugins/setlist/{setlist_id}/song/{song_id}")
    def remove_from_setlist(setlist_id: int, song_id: int):
        conn = _get_conn()
        with _write(conn):
            deleted = conn.execute(
                "DELETE FROM setlist_songs WHERE id = ? AND setlist_id = ?",
                (song_id, setlist_id)
            ).rowcount
            if not deleted:
                # Reordering and re-touching on a no-op delete was wasted work
                # that also bumped the wrong setlist's updated_at.
                return _error("Not found", 404)
            # Re-number densely: removing from the middle otherwise left a gap.
            songs = conn.execute(
                "SELECT id FROM setlist_songs WHERE setlist_id = ? ORDER BY position, id",
                (setlist_id,)
            ).fetchall()
            conn.executemany(
                "UPDATE setlist_songs SET position = ? WHERE id = ?",
                [(i + 1, sid) for i, (sid,) in enumerate(songs)]
            )
            _touch(conn, setlist_id)
        return {"ok": True}

    @app.post("/api/plugins/setlist/{setlist_id}/reorder")
    def reorder_setlist(setlist_id: int, data: dict):
        """Reorder songs. data = {"song_ids": [3, 1, 2]}

        `song_ids` must be a list of unique integers belonging to this
        setlist. Listed songs come first in the given order; any omitted song
        keeps its relative order and is appended. Numbering stays dense (1..N)
        either way — which is what the previous positional `executemany` over
        1..len(song_ids) broke: sending a subset silently produced duplicate
        positions and made `ORDER BY position` ambiguous.
        """
        song_ids = data.get("song_ids")
        if not song_ids:
            return _error("No song IDs", 400)
        if not isinstance(song_ids, list) or not all(
            isinstance(sid, int) and not isinstance(sid, bool) for sid in song_ids
        ):
            return _error("song_ids must be a list of integers", 400)
        if len(set(song_ids)) != len(song_ids):
            return _error("song_ids must not contain duplicates", 400)

        conn = _get_conn()
        with _write(conn):
            if not _setlist_exists(conn, setlist_id):
                return _error("Not found", 404)

            owned = [r[0] for r in conn.execute(
                "SELECT id FROM setlist_songs WHERE setlist_id = ?",
                (setlist_id,)
            ).fetchall()]

            foreign = [sid for sid in song_ids if sid not in set(owned)]
            if foreign:
                # Ids from another setlist used to be ignored by the WHERE
                # clause while the response still claimed success.
                return _error(
                    "Unknown song id(s) for this setlist: "
                    + ", ".join(str(sid) for sid in foreign),
                    400,
                )

            requested_set = set(song_ids)
            ordered = list(song_ids) + [sid for sid in owned if sid not in requested_set]

            if ordered != owned:
                conn.executemany(
                    "UPDATE setlist_songs SET position = ? WHERE id = ? AND setlist_id = ?",
                    [(i + 1, sid, setlist_id) for i, sid in enumerate(ordered)]
                )
                _touch(conn, setlist_id)
        return {"ok": True}