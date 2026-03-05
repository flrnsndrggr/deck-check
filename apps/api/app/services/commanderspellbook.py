from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Set

import httpx

from app.workers.queue import redis_conn

COMMANDERSPELLBOOK_VARIANTS_URL = "https://backend.commanderspellbook.com/variants/"


def _deck_hash(cards: Iterable[str], commander: str | None) -> str:
    payload = {
        "commander": (commander or "").strip().lower(),
        "cards": sorted({c.strip().lower() for c in cards if c and c.strip()}),
    }
    stable = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(stable.encode()).hexdigest()


def _normalize_variant(raw: Dict[str, Any], deck_names: Set[str], commander: str | None) -> Dict[str, Any]:
    uses = raw.get("uses") or []
    name_set = {str(u.get("card", {}).get("name") or u.get("name") or "").strip() for u in uses}
    name_set = {n for n in name_set if n}
    if not name_set:
        return {}
    present = sorted([n for n in name_set if n.lower() in deck_names])
    missing = sorted([n for n in name_set if n.lower() not in deck_names])
    total = len(name_set)
    coverage = len(present) / total if total else 0.0
    missing_count = len(missing)
    status = "not_close"
    if missing_count == 0:
        status = "complete"
    elif missing_count <= 2:
        status = "near_miss"

    recipe = str(raw.get("description") or raw.get("notes") or "").strip().replace("\n", " ")
    variant_id = str(raw.get("id") or raw.get("variant_id") or "")
    identity = str(raw.get("identity") or "")
    commander_bonus = 0.05 if commander and commander in present else 0.0
    base_score = coverage * 0.75 + (0.2 if status == "complete" else 0.08 if status == "near_miss" else 0.0)
    score = round(min(1.0, base_score + commander_bonus), 4)
    source_url = f"https://commanderspellbook.com/combo/{variant_id}" if variant_id else "https://commanderspellbook.com"
    return {
        "variant_id": variant_id or f"anon-{hashlib.md5('|'.join(sorted(name_set)).encode()).hexdigest()[:8]}",
        "identity": identity,
        "recipe": recipe,
        "cards": sorted(name_set),
        "present_cards": present,
        "missing_cards": missing,
        "missing_count": missing_count,
        "card_coverage": round(coverage, 4),
        "score": score,
        "status": status,
        "source_url": source_url,
    }


class ComboIntelService:
    def __init__(self, timeout_s: float = 8.0, retries: int = 2, ttl_seconds: int = 86400):
        self.timeout_s = timeout_s
        self.retries = retries
        self.ttl_seconds = ttl_seconds

    def _cache_key(self, cards: List[str], commander: str | None) -> str:
        return f"combointel:{_deck_hash(cards, commander)}:{(commander or '').strip().lower()}"

    def _read_cache(self, key: str) -> Dict[str, Any] | None:
        try:
            raw = redis_conn.get(key)
        except Exception:
            return None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    def _write_cache(self, key: str, payload: Dict[str, Any]) -> None:
        try:
            redis_conn.setex(key, self.ttl_seconds, json.dumps(payload))
        except Exception:
            return

    def _fetch_variants_for_cards(self, cards: List[str], limit: int = 200) -> List[Dict[str, Any]]:
        variants: List[Dict[str, Any]] = []
        # Query by a subset of deck cards to keep requests bounded.
        query_cards = sorted({c.strip() for c in cards if c and c.strip()})[:8]
        if not query_cards:
            return variants

        with httpx.Client(timeout=self.timeout_s) as client:
            for card_name in query_cards:
                page = 1
                while len(variants) < limit:
                    resp = client.get(COMMANDERSPELLBOOK_VARIANTS_URL, params={"card": card_name, "limit": 50, "page": page})
                    if resp.status_code >= 400:
                        break
                    payload = resp.json()
                    rows = payload.get("results") or payload.get("data") or []
                    if not rows:
                        break
                    variants.extend(rows)
                    if not payload.get("next"):
                        break
                    page += 1
                    if page > 3:
                        break
                if len(variants) >= limit:
                    break
        # Deduplicate by id.
        unique: Dict[str, Dict[str, Any]] = {}
        for row in variants:
            rid = str(row.get("id") or row.get("variant_id") or "")
            if not rid:
                rid = hashlib.md5(json.dumps(row, sort_keys=True).encode()).hexdigest()
            unique[rid] = row
        return list(unique.values())[:limit]

    def get_combo_intel(self, cards: List[str], commander: str | None = None, max_variants: int = 200) -> Dict[str, Any]:
        key = self._cache_key(cards, commander)
        cached = self._read_cache(key)
        if cached:
            return cached

        warnings: List[str] = []
        variants_raw: List[Dict[str, Any]] = []
        attempts = self.retries + 1
        for attempt in range(attempts):
            try:
                variants_raw = self._fetch_variants_for_cards(cards, limit=max_variants)
                break
            except Exception as exc:
                if attempt == attempts - 1:
                    warnings.append(f"CommanderSpellbook unavailable: {exc}")
                else:
                    time.sleep(0.2 * (2**attempt))

        deck_names = {c.strip().lower() for c in cards if c and c.strip()}
        normalized = [
            _normalize_variant(row, deck_names, commander)
            for row in variants_raw
        ]
        normalized = [row for row in normalized if row]
        normalized.sort(key=lambda x: (-x["score"], x["missing_count"], x["variant_id"]))

        matched = [v for v in normalized if v["status"] == "complete"][:10]
        near_miss = [v for v in normalized if v["status"] == "near_miss"][:10]
        support_score = 0.0
        if normalized:
            top_weight = sum(v["score"] for v in normalized[:10]) / min(10, len(normalized))
            hit_bonus = min(0.35, len(matched) * 0.07)
            support_score = round(min(100.0, (top_weight + hit_bonus) * 100), 1)

        result = {
            "source": "commanderspellbook",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source_hash": hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest() if normalized else "",
            "combo_support_score": support_score,
            "matched_variants": matched,
            "near_miss_variants": near_miss,
            "warnings": warnings,
        }
        self._write_cache(key, result)
        return result
