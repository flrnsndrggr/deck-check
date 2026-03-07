from __future__ import annotations

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.sim_job import SimJob
from app.services.problem_log import format_exception_detail, record_problem_event
from app.workers.cache import set_cached_simulation
from sim.config import resolve_sim_config
from sim.engine import run_simulation_batch as run_simulation_batch_python

_VECTORIZED_IMPORT_ERROR: str | None = None
_VECTORIZED_STRICT_WIN_ROLLOUT_ENABLED = False
try:
    from sim.engine_vectorized import run_simulation_batch_vectorized
except Exception as exc:
    run_simulation_batch_vectorized = None  # type: ignore[assignment]
    _VECTORIZED_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"


def get_vector_backend_status() -> dict:
    return {
        "vectorized_available": run_simulation_batch_vectorized is not None,
        "vectorized_import_error": _VECTORIZED_IMPORT_ERROR,
        "vectorized_strict_win_rollout_enabled": _VECTORIZED_STRICT_WIN_ROLLOUT_ENABLED,
    }


def run_simulation_task(job_id: str, payload: dict):
    db = SessionLocal()
    try:
        row = db.execute(select(SimJob).where(SimJob.job_id == job_id)).scalar_one()
        row.status = "running"
        db.commit()

        requested_backend = payload.get("sim_backend", "vectorized")
        commander_names = payload.get("commanders") or []
        warning: str | None = None
        result = None
        resolved_config = resolve_sim_config(
            commander=commander_names or payload.get("commander"),
            requested_policy=payload.get("policy", "auto"),
            bracket=payload.get("bracket", 3),
            turn_limit=payload.get("turn_limit", 8),
            multiplayer=payload.get("multiplayer", True),
            threat_model=payload.get("threat_model", False),
            primary_wincons=payload.get("primary_wincons", []),
            color_identity_size=payload.get("color_identity_size", 3),
            seed=payload.get("seed", 42),
        )

        sim_kwargs = dict(
            cards=payload["cards"],
            commander=[name for name in resolved_config.commander_slots if name],
            runs=payload.get("runs", 1000),
            turn_limit=payload.get("turn_limit", 8),
            policy=resolved_config.policy.resolved_policy,
            multiplayer=payload.get("multiplayer", True),
            threat_model=payload.get("threat_model", False),
            seed=resolved_config.seed,
            bracket=payload.get("bracket", 3),
            primary_wincons=payload.get("primary_wincons", []),
            color_identity_size=resolved_config.color_identity_size,
            combo_variants=payload.get("combo_variants", []),
            combo_source_live=payload.get("combo_source_live", False),
            resolved_config=resolved_config.to_payload(),
        )

        if requested_backend == "vectorized":
            if run_simulation_batch_vectorized is None:
                warning = (
                    "Vectorized backend unavailable; NumPy/vector module import failed. "
                    f"Used python_fallback. Import error: {_VECTORIZED_IMPORT_ERROR or 'unknown'}"
                )
            elif not _VECTORIZED_STRICT_WIN_ROLLOUT_ENABLED:
                warning = (
                    "Vectorized backend temporarily disabled during strict win-evaluator rollout. "
                    "Used python_fallback so combat/combo outcome tiers stay on the coherent reference path."
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
        try:
            record_problem_event(
                db,
                source="worker",
                category="simulation_task_failed",
                message=err,
                detail=format_exception_detail(exc),
                context={"job_id": job_id, "requested_backend": payload.get("sim_backend", "vectorized")},
                level="error",
            )
        except Exception:
            pass
        return {"error": err, "summary": {"backend_used": "failed"}}
    finally:
        db.close()
