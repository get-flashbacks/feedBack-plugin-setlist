"""Setlist CRUD + song ordering."""

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
    assert client.post(f"{BASE}/create", json={"name": "  "}).json() == {"error": "Name required"}
    assert client.post(f"{BASE}/create", json={}).json() == {"error": "Name required"}


def test_get_setlist_not_found(client):
    assert client.get(f"{BASE}/9999").json() == {"error": "Not found"}


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
    assert client.post(f"{BASE}/{setlist}/rename", json={"name": ""}).json() == {"error": "Name required"}


def test_add_song_requires_filename(client, setlist):
    assert client.post(f"{BASE}/{setlist}/add", json={}).json() == {"error": "No filename"}


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

    client.delete(f"{BASE}/{other}/song/{song_id}")  # wrong setlist -> no-op
    assert len(client.get(f"{BASE}/{setlist}").json()["songs"]) == 1


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
    assert client.post(f"{BASE}/{setlist}/reorder", json={"song_ids": []}).json() == {"error": "No song IDs"}
    assert client.post(f"{BASE}/{setlist}/reorder", json={}).json() == {"error": "No song IDs"}
