from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.routes as routes
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.problem_event import ProblemEvent
from app.models.user import User
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

    def ping(self):
        return True


class _FakeQueue:
    count = 0


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
    fake_redis = _FakeRedis()
    monkeypatch.setattr(auth_mod, "redis_conn", fake_redis)
    monkeypatch.setattr(routes, "redis_conn", fake_redis)
    monkeypatch.setattr(routes, "sim_queue", _FakeQueue())
    return TestClient(app), TestingSessionLocal


def _register(client: TestClient, email: str, password: str = "averysecurepw"):
    response = client.post("/api/auth/register", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()


def test_admin_endpoints_reject_non_admin(monkeypatch):
    client, _ = _client_with_db(monkeypatch)
    _register(client, "user@example.com")

    problems = client.get("/api/admin/problems")
    assert problems.status_code == 403
    users = client.get("/api/admin/users")
    assert users.status_code == 403


def test_admin_problem_feed_and_user_management(monkeypatch):
    client, SessionLocal = _client_with_db(monkeypatch)
    _register(client, "florian.sonderegger@me.com")
    _register(client, "member@example.com")
    login = client.post("/api/auth/login", json={"email": "florian.sonderegger@me.com", "password": "averysecurepw"})
    assert login.status_code == 200
    csrf = login.json()["csrf_token"]

    db = SessionLocal()
    try:
        user_row = db.query(User).filter(User.email == "member@example.com").one()
        db.add(
            ProblemEvent(
                level="error",
                source="api",
                category="test_problem",
                message="Synthetic failure",
                detail="Traceback line 1\nTraceback line 2",
                path="/api/example",
                user_id=user_row.id,
                user_email=user_row.email,
                request_id="req_test_123",
                context={"stage": "test"},
            )
        )
        db.commit()
    finally:
        db.close()

    problems = client.get("/api/admin/problems")
    assert problems.status_code == 200
    body = problems.json()
    assert body["problems"]
    assert "Synthetic failure" in body["problems"][0]["copy_blob"]
    assert "req_test_123" in body["problems"][0]["copy_blob"]

    users = client.get("/api/admin/users")
    assert users.status_code == 200
    member = next(row for row in users.json()["users"] if row["email"] == "member@example.com")
    assert member["role"] == "user"

    updated = client.patch(
        f"/api/admin/users/{member['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"role": "moderator", "status": "suspended", "plan": "pro", "admin_notes": "watchlist"},
    )
    assert updated.status_code == 200
    payload = updated.json()
    assert payload["role"] == "moderator"
    assert payload["status"] == "suspended"
    assert payload["plan"] == "pro"
    assert payload["admin_notes"] == "watchlist"
    assert payload["active_session_count"] == 0

    protected = next(row for row in users.json()["users"] if row["email"] == "florian.sonderegger@me.com")
    forbidden = client.patch(
        f"/api/admin/users/{protected['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"status": "inactive"},
    )
    assert forbidden.status_code == 400


def test_admin_systems_returns_expected_checks(monkeypatch):
    client, _ = _client_with_db(monkeypatch)
    _register(client, "florian.sonderegger@me.com")

    monkeypatch.setattr(routes, "_http_probe", lambda *args, **kwargs: True)
    monkeypatch.setattr(routes, "_has_live_workers", lambda: True)
    monkeypatch.setattr(routes, "get_vector_backend_status", lambda: {"vectorized_available": True})
    monkeypatch.setattr(routes.settings, "ai_enabled", False, raising=False)
    monkeypatch.setattr(routes.settings, "resend_api_key", "", raising=False)

    systems = client.get("/api/admin/systems")
    assert systems.status_code == 200
    payload = systems.json()
    keys = {row["key"] for row in payload["checks"]}
    assert {"database", "redis", "worker", "simulation_backend", "openai", "scryfall", "commanderspellbook", "resend"} <= keys
