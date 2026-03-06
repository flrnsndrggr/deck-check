from __future__ import annotations

from uuid import uuid4
from threading import Thread
from queue import Queue as ThreadQueue, Empty as QueueEmpty
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import desc, select, text
from sqlalchemy.orm import Session
from rq import Worker

from app.db.session import get_db
from app.models.project import Project
from app.models.project_version import ProjectVersion
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User
from app.models.data_source import DataSourceStatus
from app.models.run_record import RunRecord
from app.models.sim_job import SimJob
from app.schemas.auth import (
    AuthCredentialsRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    PasswordResetResponse,
    AuthSessionResponse,
    ProjectListResponse,
    ProjectResponse,
    ProjectSaveRequest,
    ProjectSummary,
    ProjectVersionListResponse,
    ProjectVersionResponse,
    ProjectVersionSummary,
)
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
from app.services.auth import (
    auth_rate_limited,
    clear_auth_failures,
    clear_session_cookie,
    create_session,
    create_password_reset_token,
    get_session_context,
    get_valid_password_reset_token,
    hash_password,
    normalize_email,
    normalize_project_name_key,
    record_auth_failure,
    record_reset_request,
    require_csrf,
    reset_rate_limited,
    revoke_user_sessions,
    session_payload,
    set_session_cookie,
    validate_email,
    validate_password,
    verify_password,
)
from app.services.analyzer import analyze
from app.services.commander_utils import combined_color_identity, commander_display_name, commander_names_from_cards, primary_commander_name
from app.services.commanderspellbook import ComboIntelService
from app.services.guides import generate_guides
from app.services.mail import send_password_reset_email
from app.services.ai_enrichment import AIEnrichmentService
from app.services.importer import UrlImportError, import_decklist_from_url
from app.services.parser import parse_decklist
from app.services.rules_index import search_rules
from app.services.scryfall import CardDataService
from app.services.tagger import TAG_PARENT_RELATIONS, UNIVERSAL_TAG_GROUPS, compute_type_theme_profile, tag_cards
from app.services.updates import update_all_data
from app.services.validator import validate_deck
from app.services.rules_watchouts import build_rules_watchouts
from app.services.replacements import strictly_better_replacements
from app.services.winplans import enrich_sim_cards, infer_supported_wincons
from app.workers.queue import redis_conn, sim_queue
from app.workers.cache import get_cached_simulation
from app.workers.tasks import get_vector_backend_status, run_simulation_task
from app.core.config import settings

router = APIRouter(prefix="/api")


def _project_summary(row: Project) -> ProjectSummary:
    version_count = row.summary.get("version_count") if isinstance(row.summary, dict) else None
    latest_version_number = row.summary.get("latest_version_number") if isinstance(row.summary, dict) else None
    return ProjectSummary(
        id=row.id,
        name=row.name,
        name_key=row.name_key,
        deck_name=row.deck_name,
        commander_label=row.commander_label,
        bracket=row.bracket,
        summary=row.summary or {},
        version_count=int(version_count or 1),
        latest_version_number=int(latest_version_number or 1),
        updated_at=row.updated_at,
        created_at=row.created_at,
    )


def _project_version_summary(row: ProjectVersion) -> ProjectVersionSummary:
    return ProjectVersionSummary(
        id=row.id,
        project_id=row.project_id,
        version_number=row.version_number,
        name=row.name,
        deck_name=row.deck_name,
        commander_label=row.commander_label,
        bracket=row.bracket,
        summary=row.summary or {},
        created_at=row.created_at,
    )


def _next_version_number(db: Session, project_id: int) -> int:
    rows = db.execute(select(ProjectVersion.version_number).where(ProjectVersion.project_id == project_id)).scalars().all()
    return (max(rows) if rows else 0) + 1


def _record_project_version(db: Session, project: Project) -> ProjectVersion:
    version_number = _next_version_number(db, project.id)
    row = ProjectVersion(
        project_id=project.id,
        version_number=version_number,
        name=project.name,
        deck_name=project.deck_name,
        commander_label=project.commander_label,
        decklist_text=project.decklist_text,
        bracket=project.bracket,
        summary=project.summary or {},
        saved_bundle=project.saved_bundle or {},
    )
    db.add(row)
    db.flush()
    summary = dict(project.summary or {})
    summary["version_count"] = version_number
    summary["latest_version_number"] = version_number
    project.summary = summary
    return row


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


@router.get("/auth/session", response_model=AuthSessionResponse)
def get_auth_session(request: Request, db: Session = Depends(get_db)):
    ctx = get_session_context(db, request, allow_missing=True)
    return AuthSessionResponse(**session_payload(ctx))


@router.post("/auth/register", response_model=AuthSessionResponse)
def register_auth(req: AuthCredentialsRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    email = validate_email(req.email)
    password = validate_password(req.password)
    if auth_rate_limited(email, request.client.host if request.client else None):
        raise HTTPException(status_code=429, detail="Too many auth attempts. Try again later.")
    existing = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="An account with that email already exists.")
    user = User(email=email, password_hash=hash_password(password))
    db.add(user)
    db.flush()
    session_row, raw_token = create_session(db, user, request)
    db.commit()
    set_session_cookie(response, raw_token)
    return AuthSessionResponse(
        authenticated=True,
        user={"id": user.id, "email": user.email},
        csrf_token=session_row.csrf_token,
    )


@router.post("/auth/login", response_model=AuthSessionResponse)
def login_auth(req: AuthCredentialsRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    email = validate_email(req.email)
    if auth_rate_limited(email, request.client.host if request.client else None):
        raise HTTPException(status_code=429, detail="Too many auth attempts. Try again later.")
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None or not verify_password(req.password, user.password_hash):
        record_auth_failure(email, request.client.host if request.client else None)
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    clear_auth_failures(email, request.client.host if request.client else None)
    user.last_login_at = datetime.now(timezone.utc)
    session_row, raw_token = create_session(db, user, request)
    db.commit()
    set_session_cookie(response, raw_token)
    return AuthSessionResponse(
        authenticated=True,
        user={"id": user.id, "email": user.email},
        csrf_token=session_row.csrf_token,
    )


@router.post("/auth/logout", response_model=AuthSessionResponse)
def logout_auth(request: Request, response: Response, db: Session = Depends(get_db)):
    ctx = get_session_context(db, request, allow_missing=True)
    if ctx:
        require_csrf(request, ctx)
        db.delete(ctx.session)
        db.commit()
    clear_session_cookie(response)
    return AuthSessionResponse(authenticated=False, user=None, csrf_token=None)


@router.post("/auth/password-reset/request", response_model=PasswordResetResponse)
def request_password_reset(req: PasswordResetRequest, request: Request, db: Session = Depends(get_db)):
    email = validate_email(req.email)
    ip_address = request.client.host if request.client else None
    if reset_rate_limited(email, ip_address):
        raise HTTPException(status_code=429, detail="Too many reset requests. Try again later.")
    record_reset_request(email, ip_address)
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    debug_magic_link = None
    if user is not None:
        existing = db.execute(select(PasswordResetToken).where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))).scalars().all()
        for row in existing:
            db.delete(row)
        db.flush()
        _row, _raw_token, magic_link = create_password_reset_token(db, user, request)
        try:
            debug_magic_link = send_password_reset_email(to_email=user.email, magic_link=magic_link)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        db.commit()
    return PasswordResetResponse(
        ok=True,
        message="If that email exists, a one-time reset link has been sent.",
        debug_magic_link=debug_magic_link,
    )


@router.post("/auth/password-reset/confirm", response_model=AuthSessionResponse)
def confirm_password_reset(req: PasswordResetConfirmRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    password = validate_password(req.password)
    token_row = get_valid_password_reset_token(db, req.token)
    if token_row is None:
        raise HTTPException(status_code=400, detail="This reset link is invalid or expired.")
    user = db.execute(select(User).where(User.id == token_row.user_id)).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=400, detail="This reset link is invalid or expired.")
    token_row.used_at = datetime.now(timezone.utc)
    other_tokens = db.execute(select(PasswordResetToken).where(PasswordResetToken.user_id == user.id, PasswordResetToken.id != token_row.id)).scalars().all()
    for row in other_tokens:
        db.delete(row)
    user.password_hash = hash_password(password)
    user.last_login_at = datetime.now(timezone.utc)
    revoke_user_sessions(db, user.id)
    session_row, raw_token = create_session(db, user, request)
    db.commit()
    set_session_cookie(response, raw_token)
    return AuthSessionResponse(
        authenticated=True,
        user={"id": user.id, "email": user.email},
        csrf_token=session_row.csrf_token,
    )


@router.get("/projects", response_model=ProjectListResponse)
def list_projects(request: Request, db: Session = Depends(get_db)):
    ctx = get_session_context(db, request)
    rows = db.execute(select(Project).where(Project.user_id == ctx.user.id).order_by(desc(Project.updated_at), desc(Project.id))).scalars().all()
    return ProjectListResponse(projects=[_project_summary(row) for row in rows])


@router.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project(project_id: int, request: Request, db: Session = Depends(get_db)):
    ctx = get_session_context(db, request)
    row = db.execute(select(Project).where(Project.id == project_id, Project.user_id == ctx.user.id)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return ProjectResponse(
        **_project_summary(row).model_dump(),
        decklist_text=row.decklist_text,
        saved_bundle=row.saved_bundle or {},
    )


@router.get("/projects/{project_id}/versions", response_model=ProjectVersionListResponse)
def list_project_versions(project_id: int, request: Request, db: Session = Depends(get_db)):
    ctx = get_session_context(db, request)
    row = db.execute(select(Project).where(Project.id == project_id, Project.user_id == ctx.user.id)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    versions = db.execute(
        select(ProjectVersion)
        .where(ProjectVersion.project_id == project_id)
        .order_by(desc(ProjectVersion.version_number), desc(ProjectVersion.id))
    ).scalars().all()
    return ProjectVersionListResponse(versions=[_project_version_summary(v) for v in versions])


@router.get("/projects/{project_id}/versions/{version_id}", response_model=ProjectVersionResponse)
def get_project_version(project_id: int, version_id: int, request: Request, db: Session = Depends(get_db)):
    ctx = get_session_context(db, request)
    project = db.execute(select(Project).where(Project.id == project_id, Project.user_id == ctx.user.id)).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    row = db.execute(select(ProjectVersion).where(ProjectVersion.id == version_id, ProjectVersion.project_id == project_id)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Project version not found.")
    return ProjectVersionResponse(**_project_version_summary(row).model_dump(), decklist_text=row.decklist_text, saved_bundle=row.saved_bundle or {})


@router.post("/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(req: ProjectSaveRequest, request: Request, db: Session = Depends(get_db)):
    ctx = get_session_context(db, request)
    require_csrf(request, ctx)
    name = (req.name or req.deck_name or req.commander_label or "Untitled Project").strip()[:200] or "Untitled Project"
    name_key = normalize_project_name_key(name)
    deck_name = (req.deck_name or name).strip()[:200] or "Untitled Deck"
    existing = db.execute(select(Project).where(Project.user_id == ctx.user.id, Project.name_key == name_key)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="A saved deck with that name already exists. Update it to create a new version.")
    row = Project(
        user_id=ctx.user.id,
        name=name,
        name_key=name_key,
        deck_name=deck_name,
        commander_label=(req.commander_label or "").strip()[:255] or None,
        decklist_text=req.decklist_text,
        bracket=req.bracket,
        summary=req.summary or {},
        saved_bundle=req.saved_bundle or {},
    )
    db.add(row)
    db.flush()
    _record_project_version(db, row)
    db.commit()
    db.refresh(row)
    return ProjectResponse(**_project_summary(row).model_dump(), decklist_text=row.decklist_text, saved_bundle=row.saved_bundle or {})


@router.put("/projects/{project_id}", response_model=ProjectResponse)
def update_project(project_id: int, req: ProjectSaveRequest, request: Request, db: Session = Depends(get_db)):
    ctx = get_session_context(db, request)
    require_csrf(request, ctx)
    row = db.execute(select(Project).where(Project.id == project_id, Project.user_id == ctx.user.id)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    next_name = (req.name or req.deck_name or req.commander_label or row.name or "Untitled Project").strip()[:200] or "Untitled Project"
    next_name_key = normalize_project_name_key(next_name)
    duplicate = db.execute(select(Project).where(Project.user_id == ctx.user.id, Project.name_key == next_name_key, Project.id != project_id)).scalar_one_or_none()
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="A saved deck with that name already exists.")
    row.name = next_name
    row.name_key = next_name_key
    row.deck_name = (req.deck_name or row.deck_name or row.name).strip()[:200] or "Untitled Deck"
    row.commander_label = (req.commander_label or "").strip()[:255] or None
    row.decklist_text = req.decklist_text
    row.bracket = req.bracket
    row.summary = req.summary or {}
    row.saved_bundle = req.saved_bundle or {}
    _record_project_version(db, row)
    db.commit()
    db.refresh(row)
    return ProjectResponse(**_project_summary(row).model_dump(), decklist_text=row.decklist_text, saved_bundle=row.saved_bundle or {})


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: int, request: Request, db: Session = Depends(get_db)):
    ctx = get_session_context(db, request)
    require_csrf(request, ctx)
    row = db.execute(select(Project).where(Project.id == project_id, Project.user_id == ctx.user.id)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    db.delete(row)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    commander_names = commander_names_from_cards(parsed.cards, fallback_commander=parsed.commander)
    parsed.commanders = commander_names
    parsed.commander = primary_commander_name(commander_names)
    commander_colors = combined_color_identity(card_map, commander_names)
    parsed.color_identity = commander_colors
    parsed.color_identity_size = len(commander_colors)
    return parsed


@router.post("/decks/tag", response_model=TagResponse)
def tag_deck(req: TagRequest):
    svc = CardDataService()
    card_map = svc.get_cards_by_name([c.name for c in req.cards])
    commander_names = commander_names_from_cards(req.cards, fallback_commander=req.commander)
    cards, archetypes, lines = tag_cards(req.cards, card_map, commander_names, use_global_prefix=req.global_tags)
    type_profile = compute_type_theme_profile(req.cards, card_map)
    display = svc.get_display_by_names([c.name for c in req.cards])
    commander_colors = combined_color_identity(card_map, commander_names)
    return TagResponse(
        tagged_lines=lines,
        cards=cards,
        archetype_weights=archetypes,
        type_theme_profile=type_profile,
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
    lookup_names = [c.name for c in req.cards]
    commander_names = commander_names_from_cards(req.cards, fallback_commander=req.commander)
    lookup_names.extend(commander_names)
    card_map = CardDataService().get_cards_by_name(lookup_names)
    commander_colors = combined_color_identity(card_map, commander_names)
    payload["color_identity"] = commander_colors
    payload["color_identity_size"] = len(commander_colors) if commander_names else 3
    payload["commanders"] = commander_names
    payload["commander"] = commander_display_name(commander_names) or req.commander
    combo_intel = ComboIntelService().get_combo_intel([c.name for c in req.cards], commander_names)
    payload["cards"] = enrich_sim_cards(req.cards, card_map, commander_names)
    payload["combo_variants"] = combo_intel.get("matched_variants", [])
    payload["combo_source_live"] = not bool(combo_intel.get("warnings"))
    payload["primary_wincons"] = infer_supported_wincons(payload["cards"], commander_names, combo_intel)
    cached = get_cached_simulation(payload)
    job_id = str(uuid4())
    if cached is not None:
        db.add(SimJob(job_id=job_id, status="done", payload=payload, result=cached))
        db.commit()
        return SimRunResponse(job_id=job_id)

    db.add(SimJob(job_id=job_id, status="queued", payload=payload))
    db.commit()
    db.close()

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
def analyze_deck(req: AnalyzeRequest, db: Session = Depends(get_db)):
    card_map = CardDataService().get_cards_by_name([c.name for c in req.cards])
    type_profile = compute_type_theme_profile(req.cards, card_map)
    commander_names = commander_names_from_cards(req.cards, fallback_commander=req.commander)
    commander_colors = combined_color_identity(card_map, commander_names)
    commander_ci = "".join(commander_colors)
    _, _, bracket_report = validate_deck(req.cards, req.commander, card_map, req.bracket)
    primary_commander = primary_commander_name(commander_names) or req.commander
    commander_display = commander_display_name(commander_names) or req.commander
    combo_intel = ComboIntelService().get_combo_intel([c.name for c in req.cards], commander_names)
    out = analyze(
        req.cards,
        req.sim_summary,
        bracket_report,
        req.template,
        commander_ci,
        budget_max_usd=req.budget_max_usd,
        combo_intel=combo_intel,
        commander=primary_commander,
        commander_colors=commander_colors,
        card_map=card_map,
    )
    out.setdefault("intent_summary", {})
    out["intent_summary"]["commander"] = commander_display
    out["type_theme_profile"] = type_profile
    watchouts = build_rules_watchouts(req.cards, commander_display)
    enricher = AIEnrichmentService(db)
    out = enricher.enrich_analysis(
        cards=req.cards,
        commander=commander_display,
        analysis=out,
        sim_summary=req.sim_summary,
        watchouts=watchouts,
        card_map=card_map,
    )
    final_watchouts = out.get("rules_watchouts", watchouts)
    notes = []
    for w in final_watchouts[:8]:
        flags = ", ".join(w.get("complexity_flags", [])[:3]) or "Oracle nuance"
        notes.append(f"{w.get('card')}: {flags}.")
    out["rules_watchouts"] = final_watchouts
    out["rules_interaction_notes"] = notes
    return out


@router.post("/combos/intel", response_model=ComboIntel)
def combo_intel(req: ComboIntelRequest):
    commander_names = [name for name in req.commanders if name] or ([req.commander] if req.commander else [])
    return ComboIntelService().get_combo_intel(req.cards, commander_names)


@router.post("/rules/watchouts")
def rules_watchouts(req: RulesWatchoutRequest, db: Session = Depends(get_db)):
    commander_names = commander_names_from_cards(req.cards, fallback_commander=req.commander)
    commander_display = commander_display_name(commander_names) or req.commander
    watchouts = build_rules_watchouts(req.cards, commander_display)
    watchouts = AIEnrichmentService(db).enrich_watchouts(cards=req.cards, commander=commander_display, watchouts=watchouts)
    return {"watchouts": watchouts}


@router.post("/cards/strictly-better", response_model=StrictlyBetterResponse)
def strictly_better(req: StrictlyBetterRequest):
    return strictly_better_replacements(
        cards=req.cards,
        selected_card=req.selected_card,
        commander=commander_display_name(commander_names_from_cards(req.cards, fallback_commander=req.commander)) or req.commander,
        budget_max_usd=req.budget_max_usd,
    )


@router.get("/cards/display")
def cards_display(names: str):
    requested = [n.strip() for n in names.split(",") if n.strip()]
    display = CardDataService().get_display_by_names(requested)
    return {"cards": display}


@router.post("/guides/generate", response_model=GuideResponse)
def generate(req: GuideRequest, db: Session = Depends(get_db)):
    res = generate_guides(req.analyze.model_dump(), req.sim_summary)
    res = AIEnrichmentService(db).enrich_guides(analyze=req.analyze.model_dump(), sim_summary=req.sim_summary, guides=res)
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
