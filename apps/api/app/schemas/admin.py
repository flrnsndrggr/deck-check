from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AdminProblemEntry(BaseModel):
    id: int
    level: str
    source: str
    category: str
    message: str
    detail: str | None = None
    path: str | None = None
    request_id: str | None = None
    user_id: int | None = None
    user_email: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    copy_blob: str = ""


class AdminProblemsResponse(BaseModel):
    problems: list[AdminProblemEntry] = Field(default_factory=list)


class AdminSystemCheck(BaseModel):
    key: str
    label: str
    status: str
    message: str
    latency_ms: int | None = None
    detail: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class AdminSystemsResponse(BaseModel):
    ok: bool = False
    checks: list[AdminSystemCheck] = Field(default_factory=list)
    checked_at: datetime


class AdminUserSummary(BaseModel):
    id: int
    email: str
    role: str
    status: str
    plan: str
    admin_notes: str | None = None
    is_protected_admin: bool = False
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None = None
    project_count: int = 0
    version_count: int = 0
    active_session_count: int = 0


class AdminUsersResponse(BaseModel):
    users: list[AdminUserSummary] = Field(default_factory=list)


class AdminUserUpdateRequest(BaseModel):
    role: str | None = None
    status: str | None = None
    plan: str | None = None
    admin_notes: str | None = None


class AdminUserResponse(AdminUserSummary):
    pass
