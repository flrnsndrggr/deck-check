from __future__ import annotations

from uuid import uuid4
from threading import Thread
from queue import Queue as ThreadQueue, Empty as QueueEmpty
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select, text
from sqlalchemy.orm import Session
from rq import Worker

from app.db.session import get_db
from app.models.data_source import DataSourceStatus
from app.models.run_record import RunRecord
from app.models.sim_job import SimJob
from app.schemas.deck import (
    AnalyzeRequest,
    ComboIntel,
    ComboIntelRequest,
    DeckImportUrlRequest,
    DeckImportUrlResponse,
    DeckParseRequest,
    DeckParseResponse,
    GuideRequest,
    GuideResponse,
    RulesSearchResponse,
    RulesWatchoutRequest,
    StrictlyBetterRequest,
    StrictlyBetterResponse,
    SimJobResponse,
    SimRunRequest,
    SimRunResponse,
    TagRequest,
    TagResponse,
)
from app.services.analyzer import analyze
from app.services.commanderspellbook import ComboIntelService
from app.services.guides import generate_guides
from app.services.importer import UrlImportError, import_decklist_from_url
from app.services.parser import parse_decklist
from app.services.rules_index import search_rules
from app.services.scryfall import CardDataService
from app.services.tagger import TAG_PARENT_RELATIONS, UNIVERSAL_TAG_GROUPS, tag_cards
from app.services.updates import update_all_data
from app.services.validator import validate_deck
from app.services.rules_watchouts import build_rules_watchouts
from app.services.replacements import strictly_better_replacements
from app.workers.queue import redis_conn, sim_queue
from app.workers.cache import get_cached_simulation
from app.workers.tasks import get_vector_backend_status, run_simulation_task
from app.core.config import settings

router = APIRouter(prefix="/api")


def _run_with_timeout(fn, timeout_s: float = 1.5):
    q: ThreadQueue = ThreadQueue(maxsize=1)

    def _runner():
        try:
            q.put((True, fn()))
        except Exception as exc:
            q.put((False, exc))

    t = Thread(target=_runner, daemon=True)
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        raise TimeoutError(f"Timed out after {timeout_s}s")
    try:
        ok, val = q.get_nowait()
    except QueueEmpty:
        raise TimeoutError("Timed out while awaiting result")
    if ok:
        return val
    raise val


def _has_live_workers(max_stale_seconds: int = 120) -> bool:
    """Return True when at least one RQ worker has a recent heartbeat."""
    try:
        rq_workers = _run_with_timeout(lambda: Worker.all(connection=redis_conn), timeout_s=1.5)
    except Exception:
        return False

    if not rq_workers:
        return False

    now = datetime.now(timezone.utc)
    for w in rq_workers:
        hb = w.last_heartbeat
        if hb is None:
            continue
        if hb.tzinfo is None:
            hb = hb.replace(tzinfo=timezone.utc)
        age_s = (now - hb.astimezone(timezone.utc)).total_seconds()
        if age_s <= max_stale_seconds:
            return True
    return False


@router.post("/decks/import-url", response_model=DeckImportUrlResponse)
def import_deck_url(req: DeckImportUrlRequest):
    try:
        decklist_text, source, warnings = import_decklist_from_url(req.url)
        return DeckImportUrlResponse(decklist_text=decklist_text, source=source, warnings=warnings)
    except UrlImportError as e:
        raise HTTPException(status_code=400, detail=e.to_detail())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/decks/parse", response_model=DeckParseResponse)
def parse_deck(req: DeckParseRequest, db: Session = Depends(get_db)):
    parsed = parse_decklist(req.decklist_text)
    names = [c.name for c in parsed.cards]
    card_map = CardDataService().get_cards_by_name(names)
    v_errors, v_warnings, _ = validate_deck(parsed.cards, parsed.commander, card_map, req.bracket)
    parsed.errors.extend(v_errors)
    parsed.warnings.extend(v_warnings)
    commander_colors = list(card_map.get(parsed.commander or "", {}).get("color_identity") or [])
    parsed.color_identity = commander_colors
    parsed.color_identity_size = len(commander_colors)
    return parsed


@router.post("/decks/tag", response_model=TagResponse)
def tag_deck(req: TagRequest):
    svc = CardDataService()
    card_map = svc.get_cards_by_name([c.name for c in req.cards])
    cards, archetypes, lines = tag_cards(req.cards, card_map, req.commander, use_global_prefix=req.global_tags)
    display = svc.get_display_by_names([c.name for c in req.cards])
    commander_colors = list(card_map.get(req.commander or "", {}).get("color_identity") or [])
    return TagResponse(
        tagged_lines=lines,
        cards=cards,
        archetype_weights=archetypes,
        card_display=display,
        color_identity=commander_colors,
        color_identity_size=len(commander_colors),
    )


@router.get("/tags/taxonomy")
def tags_taxonomy():
    return {
        "groups": UNIVERSAL_TAG_GROUPS,
        "parent_relations": TAG_PARENT_RELATIONS,
    }


@router.post("/sim/run", response_model=SimRunResponse)
def run_sim(req: SimRunRequest, db: Session = Depends(get_db)):
    payload = req.model_dump()
    card_map = CardDataService().get_cards_by_name([req.commander] if req.commander else [])
    commander_colors = list(card_map.get(req.commander or "", {}).get("color_identity") or [])
    payload["color_identity"] = commander_colors
    payload["color_identity_size"] = len(commander_colors) if req.commander else 3
    cached = get_cached_simulation(payload)
    job_id = str(uuid4())
    if cached is not None:
        db.add(SimJob(job_id=job_id, status="done", payload=payload, result=cached))
        db.commit()
        return SimRunResponse(job_id=job_id)

    db.add(SimJob(job_id=job_id, status="queued", payload=payload))
    db.commit()

    workers_live = _has_live_workers()
    if workers_live:
        try:
            sim_queue.enqueue(run_simulation_task, job_id, payload, job_id=f"sim-{job_id}")
            return SimRunResponse(job_id=job_id)
        except Exception:
            # If enqueue fails, fall through to optional inline fallback.
            workers_live = False

    # Recovery mode: if no active worker is available, execute immediately so UI polling does not stall.
    if settings.sim_inline_fallback_no_worker and not workers_live:
        run_simulation_task(job_id, payload)

    return SimRunResponse(job_id=job_id)


@router.get("/sim/{job_id}", response_model=SimJobResponse)
def get_sim(job_id: str, db: Session = Depends(get_db)):
    row = db.execute(select(SimJob).where(SimJob.job_id == job_id)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if row.status == "done" and row.result:
        summary = row.result.get("summary", {})
        db.add(
            RunRecord(
                seed=row.payload.get("seed", 42),
                policy=row.payload.get("policy", "auto"),
                turn_limit=row.payload.get("turn_limit", 8),
                bracket=row.payload.get("bracket", 3),
                template_preset=row.payload.get("template", "balanced"),
                config={"job_id": job_id, **row.payload},
                summary=summary,
            )
        )
        db.commit()

    return SimJobResponse(job_id=job_id, status=row.status, result=row.result or {})


@router.post("/analyze")
def analyze_deck(req: AnalyzeRequest):
    card_map = CardDataService().get_cards_by_name([c.name for c in req.cards])
    commander_colors = list(card_map.get(req.commander or "", {}).get("color_identity") or [])
    commander_ci = "".join(commander_colors)
    _, _, bracket_report = validate_deck(req.cards, req.commander, card_map, req.bracket)
    combo_intel = ComboIntelService().get_combo_intel([c.name for c in req.cards], req.commander)
    out = analyze(
        req.cards,
        req.sim_summary,
        bracket_report,
        req.template,
        commander_ci,
        budget_max_usd=req.budget_max_usd,
        combo_intel=combo_intel,
        commander=req.commander,
        commander_colors=commander_colors,
        card_map=card_map,
    )
    watchouts = build_rules_watchouts(req.cards, req.commander)
    notes = []
    for w in watchouts[:8]:
        flags = ", ".join(w.get("complexity_flags", [])[:3]) or "Oracle nuance"
        notes.append(f"{w.get('card')}: {flags}.")
    out["rules_watchouts"] = watchouts
    out["rules_interaction_notes"] = notes
    return out


@router.post("/combos/intel", response_model=ComboIntel)
def combo_intel(req: ComboIntelRequest):
    return ComboIntelService().get_combo_intel(req.cards, req.commander)


@router.post("/rules/watchouts")
def rules_watchouts(req: RulesWatchoutRequest):
    return {"watchouts": build_rules_watchouts(req.cards, req.commander)}


@router.post("/cards/strictly-better", response_model=StrictlyBetterResponse)
def strictly_better(req: StrictlyBetterRequest):
    return strictly_better_replacements(
        cards=req.cards,
        selected_card=req.selected_card,
        commander=req.commander,
        budget_max_usd=req.budget_max_usd,
    )


@router.get("/cards/display")
def cards_display(names: str):
    requested = [n.strip() for n in names.split(",") if n.strip()]
    display = CardDataService().get_display_by_names(requested)
    return {"cards": display}


@router.post("/guides/generate", response_model=GuideResponse)
def generate(req: GuideRequest):
    res = generate_guides(req.analyze.model_dump(), req.sim_summary)
    return GuideResponse(**res)


@router.get("/rules/search", response_model=RulesSearchResponse)
def rules_search(q: str, db: Session = Depends(get_db)):
    return RulesSearchResponse(hits=search_rules(db, q))


@router.post("/admin/update-data")
def admin_update_data(db: Session = Depends(get_db)):
    update_all_data(db)
    return {"ok": True}


@router.get("/meta/updates")
def updates_meta(db: Session = Depends(get_db)):
    rows = db.execute(select(DataSourceStatus).order_by(desc(DataSourceStatus.last_fetched_at))).scalars().all()
    return {
        "sources": [
            {
                "source_key": r.source_key,
                "source_url": r.source_url,
                "checksum": r.checksum,
                "warning": r.warning,
                "last_fetched_at": r.last_fetched_at.isoformat() if r.last_fetched_at else None,
            }
            for r in rows
        ]
    }


@router.get("/meta/integrations")
def integrations_meta():
    return {
        "integrations": [
            {
                "key": "scryfall",
                "purpose": "oracle card data, legalities, prices, images, purchase links",
                "url": "https://scryfall.com/docs/api",
                "status": "enabled",
            },
            {
                "key": "commanderspellbook",
                "purpose": "combo variants for complete/near-miss gameplan inference",
                "url": "https://backend.commanderspellbook.com/variants/",
                "status": "enabled",
            },
            {
                "key": "edhrec",
                "purpose": "commander popularity priors blended with heuristic role-gap recommendations",
                "url": "https://json.edhrec.com",
                "status": "best_effort",
            },
            {
                "key": "archidekt_import",
                "purpose": "best-effort URL import for decklists",
                "url": "https://archidekt.com/api/decks/1/",
                "status": "enabled",
            },
            {
                "key": "moxfield_import",
                "purpose": "best-effort URL import (can be anti-bot blocked)",
                "url": "https://www.moxfield.com",
                "status": "best_effort",
            },
            {
                "key": "cardmarket_linking",
                "purpose": "market navigation via Scryfall purchase URIs and fallback search links",
                "url": "https://api.cardmarket.com/ws/documentation/API_Main_Page",
                "status": "link_only",
            },
        ]
    }


@router.get("/meta/runtime")
def runtime_meta(db: Session = Depends(get_db)):
    db_ok = False
    redis_ok = False
    db_error = ""
    redis_error = ""
    queue_depth = 0
    workers = []
    worker_online = False
    last_sim_error = ""

    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:
        db_error = f"{type(exc).__name__}: {exc}"

    try:
        redis_ok = bool(_run_with_timeout(lambda: bool(redis_conn.ping()), timeout_s=1.5))
        if redis_ok:
            queue_depth = int(_run_with_timeout(lambda: int(sim_queue.count), timeout_s=1.5))
            rq_workers = _run_with_timeout(lambda: Worker.all(connection=redis_conn), timeout_s=1.5)
            for w in rq_workers:
                hb_iso = w.last_heartbeat.isoformat() if w.last_heartbeat else None
                if w.last_heartbeat is not None:
                    hb = w.last_heartbeat
                    if hb.tzinfo is None:
                        hb = hb.replace(tzinfo=timezone.utc)
                    age_s = (datetime.now(timezone.utc) - hb.astimezone(timezone.utc)).total_seconds()
                    if age_s <= 120:
                        worker_online = True
                workers.append(
                    {
                        "name": w.name,
                        "state": w.get_state(),
                        "current_job_id": w.get_current_job_id(),
                        "last_heartbeat": hb_iso,
                    }
                )
    except TimeoutError:
        redis_error = "Timeout: redis runtime probe exceeded 1.5s"
    except Exception as exc:
        redis_error = f"{type(exc).__name__}: {exc}"

    try:
        failed = (
            db.execute(select(SimJob).where(SimJob.status == "failed").order_by(desc(SimJob.updated_at)).limit(1))
            .scalar_one_or_none()
        )
        if failed and isinstance(failed.result, dict):
            last_sim_error = str(failed.result.get("error", "") or "")
    except Exception:
        last_sim_error = ""

    vector_backend = get_vector_backend_status()

    return {
        "ok": db_ok and redis_ok,
        "checks": {
            "database": {"ok": db_ok, "error": db_error},
            "redis": {"ok": redis_ok, "error": redis_error},
        },
        "simulation_backend": vector_backend,
        "queue_depth": queue_depth,
        "worker_online": worker_online,
        "workers": workers,
        "last_failed_simulation_error": last_sim_error,
    }
