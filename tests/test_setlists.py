"""Setlist CRUD + song ordering."""

import pytest

BASE = "/api/plugins/setlist"


def test_list_empty(client):
    assert client.get(f"{BASE}/list").json() == []


def test_create_and_list(client):
    r = client.post(f"{BASE}/create", json={"name": "Show 1"})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Show 1"
    assert isinstance(body["id"], int)

    listed = client.get(f"{BASE}/list").json()
    assert len(listed) == 1
    assert listed[0]["song_count"] == 0


def test_create_requires_name(client):
    r = client.post(f"{BASE}/create", json={"name": "  "})
    assert r.status_code == 400
    assert r.json() == {"error": "Name required"}
    r = client.post(f"{BASE}/create", json={})
    assert r.status_code == 400
    assert r.json() == {"error": "Name required"}


def test_get_setlist_not_found(client):
    r = client.get(f"{BASE}/9999")
    assert r.status_code == 404
    assert r.json() == {"error": "Not found"}


def test_get_setlist_with_no_songs(client, setlist):
    r = client.get(f"{BASE}/{setlist}")
    body = r.json()
    assert body["name"] == "Show 1"
    assert body["songs"] == []


def test_delete_setlist(client, setlist):
    assert client.delete(f"{BASE}/{setlist}").json() == {"ok": True}
    assert client.get(f"{BASE}/{setlist}").json() == {"error": "Not found"}
    assert client.get(f"{BASE}/list").json() == []


def test_delete_setlist_cascades_songs(client, setlist):
    client.post(f"{BASE}/{setlist}/add", json={"filename": "song.sloppak"})
    client.delete(f"{BASE}/{setlist}")
    # Re-creating a setlist with the same auto-increment id space should
    # not resurrect orphaned song rows; verify via a fresh setlist's songs.
    r2 = client.post(f"{BASE}/create", json={"name": "Show 2"})
    assert client.get(f"{BASE}/{r2.json()['id']}").json()["songs"] == []


def test_rename_setlist(client, setlist):
    assert client.post(f"{BASE}/{setlist}/rename", json={"name": "New Name"}).json() == {"ok": True}
    assert client.get(f"{BASE}/{setlist}").json()["name"] == "New Name"


def test_rename_requires_name(client, setlist):
    r = client.post(f"{BASE}/{setlist}/rename", json={"name": ""})
    assert r.status_code == 400
    assert r.json() == {"error": "Name required"}


def test_add_song_requires_filename(client, setlist):
    for body in ({}, {"filename": ""}, {"filename": "   "}):
        r = client.post(f"{BASE}/{setlist}/add", json=body)
        assert r.status_code == 400
        assert r.json() == {"error": "No filename"}


def test_add_songs_assigns_incrementing_positions(client, setlist):
    r1 = client.post(f"{BASE}/{setlist}/add", json={"filename": "a.sloppak", "title": "A"})
    r2 = client.post(f"{BASE}/{setlist}/add", json={"filename": "b.sloppak", "title": "B"})
    assert r1.json()["position"] == 1
    assert r2.json()["position"] == 2

    songs = client.get(f"{BASE}/{setlist}").json()["songs"]
    assert [s["title"] for s in songs] == ["A", "B"]
    assert [s["position"] for s in songs] == [1, 2]


def test_add_song_bumps_setlist_updated_at_ordering(client):
    a = client.post(f"{BASE}/create", json={"name": "A"}).json()["id"]
    b = client.post(f"{BASE}/create", json={"name": "B"}).json()["id"]
    client.post(f"{BASE}/{a}/add", json={"filename": "x.sloppak"})
    names = [s["name"] for s in client.get(f"{BASE}/list").json()]
    assert names[0] == "A"  # most recently updated first


def test_remove_song_renumbers_remaining_positions(client, setlist):
    client.post(f"{BASE}/{setlist}/add", json={"filename": "a.sloppak", "title": "A"})
    s2 = client.post(f"{BASE}/{setlist}/add", json={"filename": "b.sloppak", "title": "B"}).json()
    client.post(f"{BASE}/{setlist}/add", json={"filename": "c.sloppak", "title": "C"})

    songs_before = client.get(f"{BASE}/{setlist}").json()["songs"]
    song_b_id = next(s["id"] for s in songs_before if s["title"] == "B")

    client.delete(f"{BASE}/{setlist}/song/{song_b_id}")
    songs = client.get(f"{BASE}/{setlist}").json()["songs"]
    assert [s["title"] for s in songs] == ["A", "C"]
    assert [s["position"] for s in songs] == [1, 2]


def test_remove_song_scoped_to_its_setlist(client, setlist):
    other = client.post(f"{BASE}/create", json={"name": "Other"}).json()["id"]
    song = client.post(f"{BASE}/{setlist}/add", json={"filename": "a.sloppak"}).json()
    # song ids are global; find the actual song row id via the setlist view.
    song_id = client.get(f"{BASE}/{setlist}").json()["songs"][0]["id"]

    client.delete(f"{BASE}/{other}/song/{song_id}")  # wrong setlist -> 404
    assert len(client.get(f"{BASE}/{setlist}").json()["songs"]) == 1


def test_remove_missing_song_returns_404(client, setlist):
    r = client.delete(f"{BASE}/{setlist}/song/424242")
    assert r.status_code == 404
    assert r.json() == {"error": "Not found"}


def test_reorder_songs(client, setlist):
    client.post(f"{BASE}/{setlist}/add", json={"filename": "a.sloppak", "title": "A"})
    client.post(f"{BASE}/{setlist}/add", json={"filename": "b.sloppak", "title": "B"})
    client.post(f"{BASE}/{setlist}/add", json={"filename": "c.sloppak", "title": "C"})

    ids = [s["id"] for s in client.get(f"{BASE}/{setlist}").json()["songs"]]
    reordered = [ids[2], ids[0], ids[1]]

    client.post(f"{BASE}/{setlist}/reorder", json={"song_ids": reordered})
    songs = client.get(f"{BASE}/{setlist}").json()["songs"]
    assert [s["title"] for s in songs] == ["C", "A", "B"]


def test_reorder_requires_song_ids(client, setlist):
    for body in ({"song_ids": []}, {}):
        r = client.post(f"{BASE}/{setlist}/reorder", json=body)
        assert r.status_code == 400
        assert r.json() == {"error": "No song IDs"}


def test_create_rejects_non_string_name_instead_of_500ing(client):
    # data.get("name", "").strip() alone assumes "name" is a string whenever
    # present; a client sending null/a number for it used to raise
    # AttributeError (500) instead of the intended "Name required" 400.
    for bad_name in (None, 123, ["a"]):
        r = client.post(f"{BASE}/create", json={"name": bad_name})
        assert r.status_code == 400
        assert r.json() == {"error": "Name required"}


def test_rename_rejects_non_string_name_instead_of_500ing(client, setlist):
    for bad_name in (None, 123):
        r = client.post(f"{BASE}/{setlist}/rename", json={"name": bad_name})
        assert r.status_code == 400
        assert r.json() == {"error": "Name required"}


def test_get_conn_is_race_safe_under_concurrent_first_access(config_dir, routes_module):
    """Regression test for the unguarded `if _conn is None: _conn = ...`
    double-connect race: two threads hitting _get_conn() for the very first
    time used to be able to both pass the None check, each open (and DDL-
    initialize) their own sqlite3 connection, and race to assign the module
    global — the loser's connection (and anything written through it before
    the race resolved) silently vanishes. Simulate the race directly rather
    than through TestClient (real concurrent HTTP requests aren't
    reliably schedulable in a unit test) by having N threads call
    _get_conn() at (as close to) the same moment as a barrier can arrange,
    and asserting every thread observed the exact same connection object.
    """
    import threading

    routes_module._reset_conn()
    routes_module._db_path = str(config_dir / "race.db")

    n_threads = 16
    barrier = threading.Barrier(n_threads)
    results = [None] * n_threads

    def worker(i):
        barrier.wait()
        results[i] = routes_module._get_conn()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert all(conn is results[0] for conn in results)
    assert routes_module._conn is results[0]


# ── Audit regressions ──────────────────────────────────────────────────


def test_foreign_keys_pragma_is_enforced(routes_module, config_dir):
    """`ON DELETE CASCADE` was declared but never enabled.

    SQLite defaults `PRAGMA foreign_keys` to OFF per connection, so the
    constraint on setlist_songs was documentation only. delete_setlist masks
    this by deleting children explicitly; nothing else did.
    """
    routes_module._reset_conn()
    routes_module._db_path = str(config_dir / "fk.db")
    conn = routes_module._get_conn()
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_add_song_to_missing_setlist_rejected_instead_of_orphaning(client):
    """Adding to a nonexistent setlist returned ok:true and leaked a row."""
    before = client.get(f"{BASE}/list").json()
    r = client.post(f"{BASE}/98765/add", json={"filename": "ghost.sloppak"})
    assert r.status_code == 404
    assert r.json() == {"error": "Not found"}
    assert len(client.get(f"{BASE}/list").json()) == len(before)


def test_foreign_key_now_blocks_orphan_insert(routes_module, config_dir):
    """Belt-and-braces: the DB itself refuses a dangling setlist_id."""
    routes_module._reset_conn()
    routes_module._db_path = str(config_dir / "fk2.db")
    conn = routes_module._get_conn()
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO setlist_songs (setlist_id, filename, position) VALUES (?, ?, ?)",
            (999999, "ghost.sloppak", 1),
        )
    conn.rollback()


def test_add_song_rejects_non_string_fields_instead_of_500ing(client, setlist):
    """Non-string values reached sqlite3 and raised InterfaceError -> 500."""
    for bad in (["a"], {"k": 1}, True):
        r = client.post(f"{BASE}/{setlist}/add", json={"filename": bad})
        assert r.status_code == 400
        assert r.json() == {"error": "No filename"}

    # Non-string title/artist/arrangement coerce to "" instead of 500ing.
    r = client.post(f"{BASE}/{setlist}/add",
                    json={"filename": "ok.sloppak", "title": {"x": 1}, "artist": [1]})
    assert r.status_code == 200
    song = client.get(f"{BASE}/{setlist}").json()["songs"][-1]
    assert song["filename"] == "ok.sloppak"
    assert song["title"] == ""
    assert song["artist"] == ""


def test_reorder_partial_list_keeps_positions_dense(client, setlist):
    """A partial song_ids list used to assign 1..len() and duplicate positions."""
    for t in "ABC":
        client.post(f"{BASE}/{setlist}/add", json={"filename": f"{t}.sloppak", "title": t})
    ids = {s["title"]: s["id"] for s in client.get(f"{BASE}/{setlist}").json()["songs"]}

    client.post(f"{BASE}/{setlist}/reorder", json={"song_ids": [ids["C"]]})

    songs = client.get(f"{BASE}/{setlist}").json()["songs"]
    assert [s["title"] for s in songs] == ["C", "A", "B"]
    assert sorted(s["position"] for s in songs) == [1, 2, 3]


def test_reorder_partial_list_preserves_current_order_of_omitted_songs(client, setlist):
    """Regression: omitted songs must keep their current relative order.

    `owned` was read without ORDER BY, so it came back in rowid (insertion)
    order. After any prior reorder that is a different sequence, and hoisting
    one song silently rewrote the rest of the setlist back to insertion order.
    A test that only adds songs and never reorders first cannot catch this,
    because rowid order and position order coincide until the first reorder.
    """
    for t in "ABCD":
        client.post(f"{BASE}/{setlist}/add", json={"filename": f"{t}.sloppak", "title": t})
    ids = {s["title"]: s["id"] for s in client.get(f"{BASE}/{setlist}").json()["songs"]}

    # Reverse, so current position order is D,C,B,A while rowid order stays A,B,C,D.
    client.post(f"{BASE}/{setlist}/reorder",
                json={"song_ids": [ids["D"], ids["C"], ids["B"], ids["A"]]})
    assert [s["title"] for s in client.get(f"{BASE}/{setlist}").json()["songs"]] == \
        ["D", "C", "B", "A"]

    # Hoist D only; C,B,A must stay in that relative order.
    client.post(f"{BASE}/{setlist}/reorder", json={"song_ids": [ids["D"]]})
    songs = client.get(f"{BASE}/{setlist}").json()["songs"]
    assert [s["title"] for s in songs] == ["D", "C", "B", "A"]
    assert [s["position"] for s in songs] == [1, 2, 3, 4]


def test_reorder_rejects_unknown_song_ids(client, setlist):
    """Foreign/duplicate ids returned ok:true while changing nothing."""
    client.post(f"{BASE}/{setlist}/add", json={"filename": "a.sloppak", "title": "A"})
    song_id = client.get(f"{BASE}/{setlist}").json()["songs"][0]["id"]

    r = client.post(f"{BASE}/{setlist}/reorder", json={"song_ids": [999999]})
    assert r.status_code == 400
    assert "999999" in r.json()["error"]

    r = client.post(f"{BASE}/{setlist}/reorder", json={"song_ids": [song_id, song_id]})
    assert r.status_code == 400
    assert r.json() == {"error": "song_ids must not contain duplicates"}


def test_reorder_rejects_non_integer_ids_instead_of_500ing(client, setlist):
    """`{"song_ids": 5}` raised TypeError: 'int' object is not iterable."""
    for bad in (5, "abc", [None], [{"id": 1}], [True], {"a": 1}):
        r = client.post(f"{BASE}/{setlist}/reorder", json={"song_ids": bad})
        assert r.status_code == 400, bad
        assert r.json() == {"error": "song_ids must be a list of integers"}


def test_mutations_on_missing_setlist_return_404(client):
    assert client.delete(f"{BASE}/98765").status_code == 404
    assert client.post(f"{BASE}/98765/rename", json={"name": "x"}).status_code == 404
    assert client.post(f"{BASE}/98765/reorder", json={"song_ids": [1]}).status_code == 404


def test_list_order_is_deterministic_when_timestamps_collide(client):
    """datetime('now') has 1s resolution, so ties ordered arbitrarily."""
    ids = [client.post(f"{BASE}/create", json={"name": f"S{i}"}).json()["id"] for i in range(5)]
    first = [s["id"] for s in client.get(f"{BASE}/list").json()]
    second = [s["id"] for s in client.get(f"{BASE}/list").json()]
    assert first == second
    # Newest-created first when nothing has bumped updated_at.
    assert first == list(reversed(ids))


def test_updated_at_has_subsecond_precision(client, setlist):
    """Millisecond stamps keep "most recently updated" honest within a second."""
    client.post(f"{BASE}/{setlist}/add", json={"filename": "a.sloppak"})
    stamps = [s["updated_at"] for s in client.get(f"{BASE}/list").json()]
    assert len(stamps) == 1
    assert len(stamps[0].split(".")[-1]) >= 3


def test_setup_resets_cached_connection_between_apps(config_dir, routes_module):
    """A second setup() kept serving the first db path."""
    other_dir = config_dir / "second"
    other_dir.mkdir()
    routes_module._reset_conn()
    routes_module._db_path = str(config_dir / "first.db")
    first = routes_module._get_conn()
    routes_module._reset_conn()
    routes_module._db_path = str(other_dir / "second.db")
    second = routes_module._get_conn()
    assert first is not second
