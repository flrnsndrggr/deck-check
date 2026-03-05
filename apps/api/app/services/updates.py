from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.data_source import DataSourceStatus
from app.services.rules_index import refresh_rules_index
from app.services.scryfall import CardDataService
from app.services.validator import DEFAULT_BRACKET_LIMITS, DEFAULT_BRACKET_PROFILES

URLS = {
    "format": "https://magic.wizards.com/en/formats/commander",
    "brackets_beta": "https://magic.wizards.com/en/news/announcements/commander-brackets-beta-update-october-21-2025",
    "banned_announcement": "https://magic.wizards.com/en/news/announcements/commander-banned-and-restricted-february-9-2026",
}


def _status_upsert(db: Session, key: str, url: str, content: bytes, warning: str = ""):
    checksum = hashlib.sha256(content).hexdigest()
    row = db.query(DataSourceStatus).filter(DataSourceStatus.source_key == key).one_or_none()
    if row is None:
        row = DataSourceStatus(source_key=key, source_url=url, checksum=checksum, warning=warning)
        db.add(row)
    else:
        row.source_url = url
        row.checksum = checksum
        row.warning = warning
        row.last_fetched_at = datetime.now(timezone.utc)
    db.commit()


def _read_or_create(path: Path, default):
    if path.exists():
        return json.loads(path.read_text())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(default, indent=2))
    return default


def update_banned_and_brackets(db: Session):
    cache_dir = Path(settings.rules_cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    warnings = []
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        format_resp = client.get(URLS["format"])
        beta_resp = client.get(URLS["brackets_beta"])
        banned_resp = client.get(URLS["banned_announcement"])

    _status_upsert(db, "format_page", URLS["format"], format_resp.content)
    _status_upsert(db, "brackets_beta", URLS["brackets_beta"], beta_resp.content)
    _status_upsert(db, "banned_announcement", URLS["banned_announcement"], banned_resp.content)

    beta_text = BeautifulSoup(beta_resp.text, "html.parser").get_text(" ")
    banned_text = BeautifulSoup(banned_resp.text, "html.parser").get_text(" ")

    gc_candidates = sorted(set(re.findall(r"\b[A-Z][A-Za-z'\-, ]{2,}\b", beta_text)))
    # Conservative extraction: keep likely card-like entries (title cased, short, no URLs)
    game_changers = [c.strip() for c in gc_candidates if 2 <= len(c.split()) <= 4 and "Commander" not in c][:80]
    if not game_changers:
        warnings.append("Could not confidently parse Game Changers list.")

    banned_cards = sorted(set(re.findall(r"\b[A-Z][A-Za-z'\-, ]{2,}\b", banned_text)))
    banned_cards = [c.strip() for c in banned_cards if 1 <= len(c.split()) <= 5 and "Commander" not in c][:120]

    banned_as_companion = []
    for m in re.finditer(r"([A-Z][A-Za-z'\-, ]+) banned as companion", banned_text, flags=re.IGNORECASE):
        banned_as_companion.append(m.group(1).strip())

    (cache_dir / "game_changers.json").write_text(json.dumps({"cards": game_changers, "fetched_at": datetime.now(timezone.utc).isoformat(), "source": URLS["brackets_beta"]}, indent=2))
    (cache_dir / "banned.json").write_text(json.dumps({"banned": banned_cards, "banned_as_companion": banned_as_companion, "fetched_at": datetime.now(timezone.utc).isoformat(), "source": URLS["banned_announcement"]}, indent=2))

    bracket_defaults = {
        "limits": {str(k): int(v) for k, v in DEFAULT_BRACKET_LIMITS.items()},
        "profiles": DEFAULT_BRACKET_PROFILES,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": URLS["format"],
        "warnings": warnings,
    }
    (cache_dir / "brackets.json").write_text(json.dumps(bracket_defaults, indent=2))

    warn = "; ".join(warnings)
    _status_upsert(db, "derived_lists", URLS["format"], json.dumps(bracket_defaults).encode(), warning=warn)


def update_all_data(db: Session):
    svc = CardDataService()
    bulk = svc.refresh_bulk_snapshot()
    svc.ingest_bulk_snapshot(limit=20000)
    _status_upsert(db, "scryfall_oracle_bulk", bulk["source_url"], bulk["checksum"].encode())
    update_banned_and_brackets(db)
    refresh_rules_index(db)
