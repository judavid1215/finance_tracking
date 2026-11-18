from fastapi.testclient import TestClient

from finanzas import __version__
from finanzas.api.main import create_app
from finanzas.config import Settings


def test_health_ok(tmp_path):
    settings = Settings(db_path=str(tmp_path / "test.sqlite3"), _env_file=None)
    with TestClient(create_app(settings)) as client:  # el 'with' ejecuta el lifespan
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["database"]["ok"] is True
    assert body["database"]["journal_mode"] == "wal"
    assert body["database"]["schema_version"] == "0001"
