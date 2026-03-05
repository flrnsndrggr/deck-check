from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.db.session import SessionLocal
from app.models.sim_job import SimJob
import app.api.routes as routes


def _sim_request_payload():
    return {
        "cards": [
            {"qty": 1, "name": "Wastes", "section": "deck"},
            {"qty": 1, "name": "Mind Stone", "section": "deck"},
        ],
        "commander": "The Peregrine Dynamo",
        "runs": 10,
        "turn_limit": 5,
        "policy": "optimized",
        "bracket": 3,
        "multiplayer": True,
        "threat_model": False,
        "primary_wincons": ["Combat"],
        "sim_backend": "vectorized",
        "batch_size": 128,
        "seed": 42,
    }


def test_sim_run_uses_inline_fallback_when_no_worker(monkeypatch):
    monkeypatch.setattr(routes, "get_cached_simulation", lambda payload: None)
    monkeypatch.setattr(routes, "_has_live_workers", lambda: False)
    monkeypatch.setattr(routes.settings, "sim_inline_fallback_no_worker", True)

    # Ensure queue enqueue is not used in this path.
    monkeypatch.setattr(routes.sim_queue, "enqueue", lambda *a, **k: (_ for _ in ()).throw(AssertionError("enqueue should not be called")))

    calls = {"count": 0}

    def fake_run_simulation_task(job_id: str, payload: dict):
        calls["count"] += 1
        db = SessionLocal()
        try:
            row = db.execute(select(SimJob).where(SimJob.job_id == job_id)).scalar_one()
            row.status = "done"
            row.result = {"summary": {"backend_used": "python_fallback", "runs": payload.get("runs", 0)}}
            db.commit()
            return row.result
        finally:
            db.close()

    monkeypatch.setattr(routes, "run_simulation_task", fake_run_simulation_task)

    client = TestClient(app)
    res = client.post("/api/sim/run", json=_sim_request_payload())
    assert res.status_code == 200
    job_id = res.json()["job_id"]

    poll = client.get(f"/api/sim/{job_id}")
    assert poll.status_code == 200
    assert poll.json()["status"] == "done"
    assert calls["count"] == 1


def test_sim_run_enqueues_when_worker_live(monkeypatch):
    monkeypatch.setattr(routes, "get_cached_simulation", lambda payload: None)
    monkeypatch.setattr(routes, "_has_live_workers", lambda: True)
    monkeypatch.setattr(routes.settings, "sim_inline_fallback_no_worker", True)

    enqueued = {"count": 0}

    def fake_enqueue(*args, **kwargs):
        enqueued["count"] += 1
        return None

    monkeypatch.setattr(routes.sim_queue, "enqueue", fake_enqueue)
    monkeypatch.setattr(routes, "run_simulation_task", lambda *a, **k: (_ for _ in ()).throw(AssertionError("inline fallback should not run")))

    client = TestClient(app)
    res = client.post("/api/sim/run", json=_sim_request_payload())
    assert res.status_code == 200
    job_id = res.json()["job_id"]

    poll = client.get(f"/api/sim/{job_id}")
    assert poll.status_code == 200
    assert poll.json()["status"] == "queued"
    assert enqueued["count"] == 1
