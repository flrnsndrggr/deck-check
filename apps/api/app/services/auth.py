from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.auth_session import AuthSession
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User
from app.workers.queue import redis_conn


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 64


@dataclass
class AuthContext:
    user: User
    session: AuthSession
    raw_token: str | None = None


def normalize_email(email: str) -> str:
    return str(email or "").strip().lower()


def admin_email_set() -> set[str]:
    return {normalize_email(email) for email in str(settings.admin_emails or "").split(",") if normalize_email(email)}


def is_admin_user(user: User | None) -> bool:
    if user is None:
        return False
    return normalize_email(user.email) in admin_email_set()


def normalize_project_name_key(name: str) -> str:
    normalized = re.sub(r"\s+", " ", str(name or "").strip().lower())
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return normalized[:200] or "untitled-project"


def validate_email(email: str) -> str:
    normalized = normalize_email(email)
    if not EMAIL_RE.fullmatch(normalized):
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    return normalized


def validate_password(password: str) -> str:
    value = str(password or "")
    if len(value) < 10:
        raise HTTPException(status_code=400, detail="Password must be at least 10 characters.")
    return value


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"))


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n_s, r_s, p_s, salt_b64, digest_b64 = encoded.split("$", 5)
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_unb64(salt_b64),
            n=int(n_s),
            r=int(r_s),
            p=int(p_s),
            dklen=len(_unb64(digest_b64)),
        )
        return hmac.compare_digest(digest, _unb64(digest_b64))
    except Exception:
        return False


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _cookie_samesite() -> str:
    mode = str(settings.auth_cookie_samesite or "lax").strip().lower()
    if mode not in {"lax", "strict", "none"}:
        return "lax"
    return mode


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=_cookie_samesite(),
        max_age=settings.auth_session_ttl_days * 24 * 60 * 60,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.auth_cookie_name,
        path="/",
        secure=settings.auth_cookie_secure,
        samesite=_cookie_samesite(),
    )


def _auth_identifier_bucket(identifier: str) -> str:
    return hashlib.sha1(identifier.encode("utf-8")).hexdigest()[:20]


def _auth_rate_key(kind: str, identifier: str) -> str:
    bucket = _auth_identifier_bucket(identifier)
    return f"authrate:{kind}:{bucket}"


def auth_rate_limited(email: str, ip_address: str | None) -> bool:
    keys = [_auth_rate_key("email", normalize_email(email))]
    if ip_address:
        keys.append(_auth_rate_key("ip", ip_address))
    try:
        for key in keys:
            value = redis_conn.get(key)
            if value is not None and int(value) >= settings.auth_rate_limit_attempts:
                return True
    except Exception:
        return False
    return False


def record_auth_failure(email: str, ip_address: str | None) -> None:
    keys = [_auth_rate_key("email", normalize_email(email))]
    if ip_address:
        keys.append(_auth_rate_key("ip", ip_address))
    try:
        for key in keys:
            current = redis_conn.incr(key)
            if int(current) == 1:
                redis_conn.expire(key, settings.auth_rate_limit_window_s)
    except Exception:
        return


def reset_rate_limited(email: str, ip_address: str | None) -> bool:
    keys = [_auth_rate_key("reset-email", normalize_email(email))]
    if ip_address:
        keys.append(_auth_rate_key("reset-ip", ip_address))
    try:
        for key in keys:
            value = redis_conn.get(key)
            if value is not None and int(value) >= settings.auth_rate_limit_attempts:
                return True
    except Exception:
        return False
    return False


def record_reset_request(email: str, ip_address: str | None) -> None:
    keys = [_auth_rate_key("reset-email", normalize_email(email))]
    if ip_address:
        keys.append(_auth_rate_key("reset-ip", ip_address))
    try:
        for key in keys:
            current = redis_conn.incr(key)
            if int(current) == 1:
                redis_conn.expire(key, settings.auth_rate_limit_window_s)
    except Exception:
        return


def clear_auth_failures(email: str, ip_address: str | None) -> None:
    keys = [_auth_rate_key("email", normalize_email(email))]
    if ip_address:
        keys.append(_auth_rate_key("ip", ip_address))
    try:
        if keys:
            redis_conn.delete(*keys)
    except Exception:
        return


def create_session(db: Session, user: User, request: Request) -> tuple[AuthSession, str]:
    raw_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(24)
    now = datetime.now(timezone.utc)
    row = AuthSession(
        user_id=user.id,
        token_hash=_sha256(raw_token),
        csrf_token=csrf_token,
        ip_address=request.client.host if request.client else None,
        user_agent=str(request.headers.get("user-agent") or "")[:255] or None,
        expires_at=now + timedelta(days=settings.auth_session_ttl_days),
    )
    db.add(row)
    db.flush()
    return row, raw_token


def revoke_user_sessions(db: Session, user_id: int) -> None:
    rows = db.execute(select(AuthSession).where(AuthSession.user_id == user_id)).scalars().all()
    for row in rows:
        db.delete(row)


def create_password_reset_token(db: Session, user: User, request: Request) -> tuple[PasswordResetToken, str, str]:
    raw_token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    row = PasswordResetToken(
        user_id=user.id,
        token_hash=_sha256(raw_token),
        email=user.email,
        ip_address=request.client.host if request.client else None,
        user_agent=str(request.headers.get("user-agent") or "")[:255] or None,
        expires_at=now + timedelta(minutes=settings.auth_magic_link_ttl_minutes),
    )
    db.add(row)
    db.flush()
    query = urlencode({"reset_token": raw_token})
    base = settings.app_base_url.rstrip("/")
    magic_link = f"{base}/?{query}"
    return row, raw_token, magic_link


def get_valid_password_reset_token(db: Session, raw_token: str) -> PasswordResetToken | None:
    if not raw_token:
        return None
    row = db.execute(select(PasswordResetToken).where(PasswordResetToken.token_hash == _sha256(raw_token))).scalar_one_or_none()
    if row is None:
        return None
    now = datetime.now(timezone.utc)
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if row.used_at is not None or expires_at < now:
        return None
    return row


def get_session_context(db: Session, request: Request, allow_missing: bool = False) -> AuthContext | None:
    raw_token = request.cookies.get(settings.auth_cookie_name)
    if not raw_token:
        if allow_missing:
            return None
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    token_hash = _sha256(raw_token)
    row = db.execute(select(AuthSession).where(AuthSession.token_hash == token_hash)).scalar_one_or_none()
    if row is None:
        if allow_missing:
            return None
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    now = datetime.now(timezone.utc)
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now:
        db.delete(row)
        db.commit()
        if allow_missing:
            return None
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired.")
    user = db.execute(select(User).where(User.id == row.user_id)).scalar_one()
    if str(user.status or "active").strip().lower() != "active":
        db.delete(row)
        db.commit()
        if allow_missing:
            return None
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is not active.")
    return AuthContext(user=user, session=row, raw_token=raw_token)


def require_admin_context(db: Session, request: Request) -> AuthContext:
    ctx = get_session_context(db, request)
    if not is_admin_user(ctx.user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")
    return ctx


def require_csrf(request: Request, ctx: AuthContext) -> None:
    header_name = settings.auth_csrf_header
    provided = request.headers.get(header_name)
    if not provided or not hmac.compare_digest(str(provided), str(ctx.session.csrf_token)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")


def session_payload(ctx: AuthContext | None) -> dict:
    if not ctx:
        return {"authenticated": False, "user": None, "csrf_token": None}
    return {
        "authenticated": True,
        "user": {
            "id": ctx.user.id,
            "email": ctx.user.email,
            "is_admin": is_admin_user(ctx.user),
            "role": ctx.user.role,
            "status": ctx.user.status,
            "plan": ctx.user.plan,
        },
        "csrf_token": ctx.session.csrf_token,
    }
