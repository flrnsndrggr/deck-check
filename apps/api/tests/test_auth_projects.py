from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.services import auth as auth_mod


class _FakeRedis:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def incr(self, key):
        next_value = int(self.store.get(key, 0)) + 1
        self.store[key] = next_value
        return next_value

    def expire(self, key, ttl):
        return True

    def delete(self, *keys):
        for key in keys:
            self.store.pop(key, None)
        return True


def _client_with_db(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(auth_mod, "redis_conn", _FakeRedis())
    return TestClient(app)


def test_register_and_project_crud(monkeypatch):
    client = _client_with_db(monkeypatch)
    register = client.post("/api/auth/register", json={"email": "user@example.com", "password": "averysecurepw"})
    assert register.status_code == 200
    body = register.json()
    assert body["authenticated"] is True
    csrf = body["csrf_token"]
    assert csrf

    create = client.post(
        "/api/projects",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": "My Deck",
            "deck_name": "Bird Law",
            "commander_label": "Soraya the Falconer",
            "decklist_text": "Commander\n1 Soraya the Falconer",
            "bracket": 3,
            "summary": {"card_count": 100},
            "saved_bundle": {"analysis": {"deck_name": "Bird Law"}},
        },
    )
    assert create.status_code == 201
    project = create.json()
    assert project["name"] == "My Deck"
    assert project["version_count"] == 1
    project_id = project["id"]

    listed = client.get("/api/projects")
    assert listed.status_code == 200
    assert len(listed.json()["projects"]) == 1

    loaded = client.get(f"/api/projects/{project_id}")
    assert loaded.status_code == 200
    assert loaded.json()["saved_bundle"]["analysis"]["deck_name"] == "Bird Law"

    updated = client.put(
        f"/api/projects/{project_id}",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": "My Deck v2",
            "deck_name": "Bird Law",
            "commander_label": "Soraya the Falconer",
            "decklist_text": "Commander\n1 Soraya the Falconer",
            "bracket": 4,
            "summary": {"card_count": 100, "has_analysis": True},
            "saved_bundle": {"analysis": {"deck_name": "Bird Law"}, "status": "done"},
        },
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "My Deck v2"
    assert updated.json()["bracket"] == 4
    assert updated.json()["version_count"] == 2

    versions = client.get(f"/api/projects/{project_id}/versions")
    assert versions.status_code == 200
    assert [row["version_number"] for row in versions.json()["versions"]] == [2, 1]

    version_id = versions.json()["versions"][1]["id"]
    version_loaded = client.get(f"/api/projects/{project_id}/versions/{version_id}")
    assert version_loaded.status_code == 200
    assert version_loaded.json()["version_number"] == 1
    assert version_loaded.json()["saved_bundle"]["analysis"]["deck_name"] == "Bird Law"

    deleted = client.delete(f"/api/projects/{project_id}", headers={"X-CSRF-Token": csrf})
    assert deleted.status_code == 204
    assert client.get("/api/projects").json()["projects"] == []


def test_project_mutation_requires_csrf(monkeypatch):
    client = _client_with_db(monkeypatch)
    register = client.post("/api/auth/register", json={"email": "user2@example.com", "password": "averysecurepw"})
    assert register.status_code == 200

    create = client.post(
        "/api/projects",
        json={
            "name": "Unsafe Deck",
            "deck_name": "Unsafe Deck",
            "commander_label": "Cmdr",
            "decklist_text": "Commander\n1 Cmdr",
            "bracket": 3,
            "summary": {},
            "saved_bundle": {},
        },
    )
    assert create.status_code == 403


def test_password_reset_magic_link_rotates_password_and_session(monkeypatch):
    client = _client_with_db(monkeypatch)
    import app.api.routes as routes

    captured = {}

    def _fake_send_password_reset_email(*, to_email: str, magic_link: str):
        captured["to_email"] = to_email
        captured["magic_link"] = magic_link
        return magic_link

    monkeypatch.setattr(routes, "send_password_reset_email", _fake_send_password_reset_email)

    register = client.post("/api/auth/register", json={"email": "reset@example.com", "password": "averysecurepw"})
    assert register.status_code == 200

    requested = client.post("/api/auth/password-reset/request", json={"email": "reset@example.com"})
    assert requested.status_code == 200
    assert requested.json()["ok"] is True
    token = captured["magic_link"].split("reset_token=", 1)[1]

    confirmed = client.post("/api/auth/password-reset/confirm", json={"token": token, "password": "anewsecurepw"})
    assert confirmed.status_code == 200
    assert confirmed.json()["authenticated"] is True
    assert confirmed.json()["user"]["email"] == "reset@example.com"

    bad_old_login = client.post("/api/auth/login", json={"email": "reset@example.com", "password": "averysecurepw"})
    assert bad_old_login.status_code == 401
    good_new_login = client.post("/api/auth/login", json={"email": "reset@example.com", "password": "anewsecurepw"})
    assert good_new_login.status_code == 200
