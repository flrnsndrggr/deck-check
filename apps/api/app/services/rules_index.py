from __future__ import annotations

import re
from pathlib import Path
from typing import List

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.rules_ref import RulesReference

COMMANDER_RULES_URL = "https://mtgcommander.net/index.php/rules/"
WIZARDS_COMMANDER_URL = "https://magic.wizards.com/en/formats/commander"
WIZARDS_RULES_PAGE_URL = "https://magic.wizards.com/en/rules"
COMP_RULES_PDF = "https://media.wizards.com/2026/downloads/MagicCompRules%2020260116.pdf"


def _cache_path(name: str) -> Path:
    p = Path(settings.rules_cache_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p / name


def _download(url: str, filename: str) -> Path:
    dest = _cache_path(filename)
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        r = client.get(url)
        r.raise_for_status()
        dest.write_bytes(r.content)
    return dest


def _latest_comp_rules_url() -> str:
    # Prefer latest official Wizards rules page link; fall back to configured known-good PDF.
    try:
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            html = client.get(WIZARDS_RULES_PAGE_URL).text
        m = re.search(r"https://media\\.wizards\\.com[^\"'\\s]*MagicCompRules[^\"'\\s]*\\.pdf", html)
        if m:
            return m.group(0).replace("\\u0026", "&")
    except Exception:
        pass
    return COMP_RULES_PDF


def refresh_rules_index(db: Session):
    db.execute(delete(RulesReference))

    commander_html = _download(COMMANDER_RULES_URL, "commander_rules.html")
    wizards_html = _download(WIZARDS_COMMANDER_URL, "wizards_commander.html")
    comp_url = _latest_comp_rules_url()
    comp_pdf = _download(comp_url, "MagicCompRules-latest.pdf")

    for path, source, url in [
        (commander_html, "mtgcommander", COMMANDER_RULES_URL),
        (wizards_html, "wizards_commander", WIZARDS_COMMANDER_URL),
    ]:
        soup = BeautifulSoup(path.read_text(errors="ignore"), "html.parser")
        text = re.sub(r"\s+", " ", soup.get_text(" ")).strip()
        chunks = [text[i : i + 2500] for i in range(0, len(text), 2500)]
        for i, chunk in enumerate(chunks):
            db.add(RulesReference(source=source, title=f"{source}-{i}", body=chunk, url=url))

    reader = PdfReader(str(comp_pdf))
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
    extracted = re.sub(r"\s+", " ", extracted).strip()
    chunks = [extracted[i : i + 2500] for i in range(0, len(extracted), 2500)]
    for i, chunk in enumerate(chunks):
        db.add(RulesReference(source="comp_rules", title=f"comp-rules-{i}", body=chunk, url=comp_url))

    db.commit()


def search_rules(db: Session, q: str, limit: int = 20) -> List[dict]:
    rows = (
        db.query(RulesReference)
        .filter(RulesReference.body.ilike(f"%{q}%"))
        .limit(limit)
        .all()
    )
    return [{"title": r.title, "source": r.source, "url": r.url, "snippet": r.body[:240]} for r in rows]
