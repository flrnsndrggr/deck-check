from __future__ import annotations

import argparse
import json
from pathlib import Path

import app.models  # noqa: F401
from app.db.session import SessionLocal
from app.models.ai_enrichment_audit import AIEnrichmentAudit
from app.services.ai_enrichment import AIEnrichmentService


def _load_recent_accepted(db, limit: int) -> list[AIEnrichmentAudit]:
    return (
        db.query(AIEnrichmentAudit)
        .filter(AIEnrichmentAudit.status == "accepted")
        .order_by(AIEnrichmentAudit.created_at.desc())
        .limit(limit)
        .all()
    )


def run_narrative_audit(limit: int, out_path: str | None) -> dict:
    db = SessionLocal()
    try:
        svc = AIEnrichmentService(db)
        items = []
        for row in _load_recent_accepted(db, limit):
            request_json = row.request_json or {}
            prompt_payload = request_json.get("prompt_payload") or {}
            if row.family not in {"intent_summary", "graph_blurb", "primer"}:
                continue
            evidence = prompt_payload
            sections = {}
            parsed = (row.response_json or {}).get("parsed") or {}
            if row.family == "intent_summary":
                for item in parsed.get("sections", []):
                    key = item.get("key")
                    text = item.get("text")
                    if key and text:
                        sections[str(key)] = str(text)
            elif row.family == "graph_blurb":
                for item in parsed.get("items", []):
                    key = f"{item.get('kind')}:{item.get('key')}"
                    text = item.get("text")
                    if key and text:
                        sections[str(key)] = str(text)
            elif row.family == "primer":
                for key in ("optimization_overview", "play_overview"):
                    text = ((parsed.get(key) or {}).get("text") or "").strip()
                    if text:
                        sections[key] = text
            audit = svc.run_consistency_audit(evidence=evidence, sections=sections)
            items.append(
                {
                    "audit_id": row.id,
                    "family": row.family,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "status": audit.get("status"),
                    "issues": audit.get("issues", []),
                }
            )
        payload = {"items": items}
        if out_path:
            Path(out_path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload
    finally:
        db.close()


def run_override_candidate_mining(limit: int, out_path: str | None) -> dict:
    db = SessionLocal()
    try:
        payload = AIEnrichmentService(db).mine_override_candidates(limit=limit)
        if out_path:
            Path(out_path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--narrative-audit", action="store_true")
    parser.add_argument("--override-candidates", action="store_true")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    out_path = args.out or None
    if args.narrative_audit:
        payload = run_narrative_audit(limit=args.limit, out_path=out_path)
        print(json.dumps(payload, indent=2))
        return
    if args.override_candidates:
        payload = run_override_candidate_mining(limit=args.limit, out_path=out_path)
        print(json.dumps(payload, indent=2))
        return

    parser.error("select --narrative-audit or --override-candidates")


if __name__ == "__main__":
    main()
