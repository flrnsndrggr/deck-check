from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AuthCredentialsRequest(BaseModel):
    email: str
    password: str


class AuthUserResponse(BaseModel):
    id: int
    email: str


class AuthSessionResponse(BaseModel):
    authenticated: bool = False
    user: AuthUserResponse | None = None
    csrf_token: str | None = None


class PasswordResetRequest(BaseModel):
    email: str


class PasswordResetConfirmRequest(BaseModel):
    token: str
    password: str


class PasswordResetResponse(BaseModel):
    ok: bool = True
    message: str
    debug_magic_link: str | None = None


class ProjectSummary(BaseModel):
    id: int
    name: str
    name_key: str
    deck_name: str
    commander_label: str | None = None
    bracket: int
    summary: dict[str, Any] = Field(default_factory=dict)
    version_count: int = 1
    latest_version_number: int = 1
    updated_at: datetime
    created_at: datetime


class ProjectVersionSummary(BaseModel):
    id: int
    project_id: int
    version_number: int
    name: str
    deck_name: str
    commander_label: str | None = None
    bracket: int
    summary: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ProjectSaveRequest(BaseModel):
    name: str | None = None
    deck_name: str | None = None
    commander_label: str | None = None
    decklist_text: str
    bracket: int = 3
    summary: dict[str, Any] = Field(default_factory=dict)
    saved_bundle: dict[str, Any] = Field(default_factory=dict)


class ProjectResponse(ProjectSummary):
    decklist_text: str
    saved_bundle: dict[str, Any] = Field(default_factory=dict)


class ProjectListResponse(BaseModel):
    projects: list[ProjectSummary] = Field(default_factory=list)


class ProjectVersionListResponse(BaseModel):
    versions: list[ProjectVersionSummary] = Field(default_factory=list)


class ProjectVersionResponse(ProjectVersionSummary):
    decklist_text: str
    saved_bundle: dict[str, Any] = Field(default_factory=dict)
