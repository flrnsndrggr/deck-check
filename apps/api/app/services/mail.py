from __future__ import annotations

import logging

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)
RESEND_SEND_URL = "https://api.resend.com/emails"


def send_password_reset_email(*, to_email: str, magic_link: str) -> str | None:
    subject = "Deck.Check password reset"
    html = f"""
    <p>You requested a password reset for Deck.Check.</p>
    <p><a href=\"{magic_link}\">Open your reset link</a></p>
    <p>This link expires in {settings.auth_magic_link_ttl_minutes} minutes and can only be used once.</p>
    <p>If you did not request this, you can ignore this email.</p>
    """.strip()

    if settings.resend_api_key and settings.auth_email_from:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                RESEND_SEND_URL,
                headers={
                    "Authorization": f"Bearer {settings.resend_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": settings.auth_email_from,
                    "to": [to_email],
                    "subject": subject,
                    "html": html,
                },
            )
        response.raise_for_status()
        return None

    if settings.environment == "local":
        log.info("Password reset link for %s: %s", to_email, magic_link)
        return magic_link

    raise RuntimeError("Password reset email delivery is not configured.")
