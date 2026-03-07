from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy import text
from threading import Thread
from queue import Queue as ThreadQueue, Empty as QueueEmpty
from uuid import uuid4

from app.api.routes import router
from app.db.session import engine
from app.core.config import settings
import app.models  # noqa: F401
from app.workers.queue import redis_conn
from app.services.problem_log import format_exception_detail, record_problem_event_safe


app = FastAPI(title="Deck.Check API", version="0.1.0")

allowed_origins = [x.strip() for x in settings.cors_allowed_origins.split(",") if x.strip()]
if settings.environment == "local" and not allowed_origins:
    allowed_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

trusted_hosts = [x.strip() for x in settings.trusted_hosts.split(",") if x.strip()]
if settings.environment != "local" and trusted_hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts)

if settings.environment != "local" and settings.force_https:
    app.add_middleware(HTTPSRedirectMiddleware)


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


@app.middleware("http")
async def max_body_size_guard(request: Request, call_next):
    request.state.request_id = str(uuid4())
    cl = request.headers.get("content-length")
    if cl:
        try:
            if int(cl) > settings.max_request_bytes:
                resp = JSONResponse({"detail": "Request body too large", "request_id": request.state.request_id}, status_code=413)
                resp.headers["X-Request-ID"] = request.state.request_id
                return resp
        except Exception:
            pass
    response = await call_next(request)
    response.headers["X-Request-ID"] = getattr(request.state, "request_id", "")
    return response


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    request_id = getattr(request.state, "request_id", str(uuid4()))
    record_problem_event_safe(
        source="api",
        category="request_validation",
        message="Request validation failed.",
        detail=str(exc),
        path=request.url.path,
        request_id=request_id,
        context={"errors": exc.errors()[:20]},
        level="warning",
    )
    resp = JSONResponse({"detail": exc.errors(), "request_id": request_id}, status_code=422)
    resp.headers["X-Request-ID"] = request_id
    return resp


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", str(uuid4()))
    record_problem_event_safe(
        source="api",
        category="unhandled_exception",
        message=f"{type(exc).__name__}: {exc}",
        detail=format_exception_detail(exc),
        path=request.url.path,
        request_id=request_id,
        level="error",
    )
    resp = JSONResponse({"detail": "Internal server error", "request_id": request_id}, status_code=500)
    resp.headers["X-Request-ID"] = request_id
    return resp


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/health/live")
def health_live():
    return {"ok": True, "status": "live"}


@app.get("/health/ready")
def health_ready():
    db_ok = False
    redis_ok = False
    db_error = ""
    redis_error = ""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            db_ok = True
    except Exception as exc:
        db_error = f"{type(exc).__name__}: {exc}"

    try:
        redis_ok = bool(_run_with_timeout(lambda: bool(redis_conn.ping()), timeout_s=1.5))
    except TimeoutError:
        redis_error = "Timeout: redis ping exceeded 1.5s"
    except Exception as exc:
        redis_error = f"{type(exc).__name__}: {exc}"

    ready = db_ok and redis_ok
    body = {
        "ok": ready,
        "status": "ready" if ready else "degraded",
        "checks": {
            "database": {"ok": db_ok, "error": db_error},
            "redis": {"ok": redis_ok, "error": redis_error},
        },
    }
    return JSONResponse(body, status_code=200 if ready else 503)


app.include_router(router)
