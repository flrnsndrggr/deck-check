from __future__ import annotations

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.sim_job import SimJob
from app.workers.cache import set_cached_simulation
from sim.engine import run_simulation_batch as run_simulation_batch_python

_VECTORIZED_IMPORT_ERROR: str | None = None
try:
    from sim.engine_vectorized import run_simulation_batch_vectorized
except Exception as exc:
    run_simulation_batch_vectorized = None  # type: ignore[assignment]
    _VECTORIZED_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"


def get_vector_backend_status() -> dict:
    return {
        "vectorized_available": run_simulation_batch_vectorized is not None,
        "vectorized_import_error": _VECTORIZED_IMPORT_ERROR,
    }


def run_simulation_task(job_id: str, payload: dict):
    db = SessionLocal()
    try:
        row = db.execute(select(SimJob).where(SimJob.job_id == job_id)).scalar_one()
        row.status = "running"
        db.commit()

        requested_backend = payload.get("sim_backend", "vectorized")
        warning: str | None = None
        result = None

        sim_kwargs = dict(
            cards=payload["cards"],
            commander=payload.get("commander"),
            runs=payload.get("runs", 1000),
            turn_limit=payload.get("turn_limit", 8),
            policy=payload.get("policy", "auto"),
            multiplayer=payload.get("multiplayer", True),
            threat_model=payload.get("threat_model", False),
            seed=payload.get("seed", 42),
            bracket=payload.get("bracket", 3),
            primary_wincons=payload.get("primary_wincons", []),
            color_identity_size=payload.get("color_identity_size", 3),
            combo_variants=payload.get("combo_variants", []),
            combo_source_live=payload.get("combo_source_live", False),
        )

        if requested_backend == "vectorized":
            if run_simulation_batch_vectorized is None:
                warning = (
                    "Vectorized backend unavailable; NumPy/vector module import failed. "
                    f"Used python_fallback. Import error: {_VECTORIZED_IMPORT_ERROR or 'unknown'}"
                )
            else:
                try:
                    result = run_simulation_batch_vectorized(
                        **sim_kwargs,
                        batch_size=payload.get("batch_size", 512),
                    )
                except Exception as exc:
                    warning = f"Vectorized backend failed at runtime ({type(exc).__name__}: {exc}). Used python_fallback."

        if result is None:
            result = run_simulation_batch_python(**sim_kwargs)
            summary = result.setdefault("summary", {})
            summary["backend_used"] = "python_fallback"
            if warning:
                summary["warning"] = warning

        row.result = result
        row.status = "done"
        db.commit()
        set_cached_simulation(payload, result)
        return result
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        row = db.execute(select(SimJob).where(SimJob.job_id == job_id)).scalar_one_or_none()
        if row is not None:
            row.status = "failed"
            row.result = {"error": err, "summary": {"backend_used": "failed"}}
            db.commit()
        return {"error": err, "summary": {"backend_used": "failed"}}
    finally:
        db.close()
