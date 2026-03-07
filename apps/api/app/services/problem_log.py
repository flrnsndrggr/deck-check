from __future__ import annotations

import traceback
from typing import Any

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.problem_event import ProblemEvent


def format_exception_detail(exc: Exception) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()


def build_problem_copy_blob(row: ProblemEvent) -> str:
    lines = [
        f"[{row.created_at.isoformat() if row.created_at else 'unknown-time'}] {row.source}/{row.category}",
        f"Level: {row.level}",
        f"Message: {row.message}",
    ]
    if row.path:
        lines.append(f"Path: {row.path}")
    if row.request_id:
        lines.append(f"Request ID: {row.request_id}")
    if row.user_email:
        lines.append(f"User: {row.user_email}")
    if row.detail:
        lines.extend(["", row.detail])
    if row.context:
        lines.extend(["", f"Context: {row.context}"])
    return "\n".join(lines)


def _truncate(value: Any, limit: int = 8000) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text[:limit]


def record_problem_event(
    db: Session,
    *,
    source: str,
    category: str,
    message: str,
    detail: str | None = None,
    path: str | None = None,
    request_id: str | None = None,
    user_id: int | None = None,
    user_email: str | None = None,
    context: dict[str, Any] | None = None,
    level: str = "error",
) -> ProblemEvent | None:
    row = ProblemEvent(
        level=_truncate(level, 16) or "error",
        source=_truncate(source, 64) or "unknown",
        category=_truncate(category, 64) or "unknown",
        message=_truncate(message, 2000) or "Unknown problem",
        detail=_truncate(detail, 16000),
        path=_truncate(path, 255),
        request_id=_truncate(request_id, 64),
        user_id=user_id,
        user_email=_truncate(user_email, 320),
        context=context or {},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def record_problem_event_safe(**kwargs: Any) -> None:
    db = SessionLocal()
    try:
        record_problem_event(db, **kwargs)
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()
