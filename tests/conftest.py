import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import routes  # noqa: E402


@pytest.fixture
def config_dir(tmp_path):
    d = tmp_path / "config"
    d.mkdir()
    return d


@pytest.fixture
def client(config_dir):
    routes._conn = None
    routes._db_path = None
    app = FastAPI()
    routes.setup(app, {"config_dir": config_dir, "meta_db": None})
    with TestClient(app) as c:
        yield c


@pytest.fixture
def setlist(client):
    """A created setlist; returns its id."""
    r = client.post("/api/plugins/setlist/create", json={"name": "Show 1"})
    return r.json()["id"]
