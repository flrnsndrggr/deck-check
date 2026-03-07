from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Set

import httpx

from app.workers.queue import redis_conn
from app.services.commander_utils import normalize_name

COMMANDERSPELLBOOK_VARIANTS_URL = "https://backend.commanderspellbook.com/variants/"
BASIC_LANDS = {"plains", "island", "swamp", "mountain", "forest", "wastes"}
COLOR_ORDER = ("W", "U", "B", "R", "G")


def _commander_list(commander: str | List[str] | None) -> List[str]:
    if isinstance(commander, list):
        return [str(name).strip() for name in commander if str(name or "").strip()]
    if commander and str(commander).strip():
        return [str(commander).strip()]
    return []


def _deck_hash(cards: Iterable[str], commander: str | List[str] | None) -> str:
    payload = {
        "commanders": sorted({normalize_name(name) for name in _commander_list(commander)}),
        "cards": sorted({c.strip().lower() for c in cards if c and c.strip()}),
    }
    stable = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(stable.encode()).hexdigest()


def _normalize_color_identity(colors: Iterable[str] | None) -> Set[str]:
    return {str(color).strip().upper() for color in (colors or []) if str(color).strip().upper() in COLOR_ORDER}


def _variant_within_color_identity(identity: str, deck_colors: Iterable[str] | None) -> bool:
    allowed = _normalize_color_identity(deck_colors)
    if not allowed:
        return True
    variant_colors = {char for char in str(identity or "").upper() if char in COLOR_ORDER}
    return variant_colors.issubset(allowed)


def _normalize_variant(raw: Dict[str, Any], deck_names: Set[str], commander: str | List[str] | None) -> Dict[str, Any]:
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
    commander_set = set(_commander_list(commander))
    commander_bonus = 0.05 if commander_set & set(present) else 0.0
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

    def _cache_key(self, cards: List[str], commander: str | List[str] | None, deck_colors: Iterable[str] | None = None) -> str:
        commander_key = ",".join(sorted(normalize_name(name) for name in _commander_list(commander)))
        color_key = "".join(sorted(_normalize_color_identity(deck_colors)))
        return f"combointel:v4:{_deck_hash(cards, commander)}:{commander_key}:{color_key}"

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
        unique_rows: Dict[str, Dict[str, Any]] = {}
        query_cards: List[str] = []
        seen_names: Set[str] = set()

        for raw_name in cards:
            name = (raw_name or "").strip()
            lowered = name.lower()
            if not name or lowered in seen_names or lowered in BASIC_LANDS:
                continue
            seen_names.add(lowered)
            query_cards.append(name)

        if not query_cards:
            return []

        with httpx.Client(timeout=self.timeout_s) as client:
            for card_name in query_cards:
                page = 1
                while len(unique_rows) < limit:
                    resp = client.get(COMMANDERSPELLBOOK_VARIANTS_URL, params={"card": card_name, "limit": 50, "page": page})
                    if resp.status_code >= 400:
                        break
                    payload = resp.json()
                    rows = payload.get("results") or payload.get("data") or []
                    if not rows:
                        break
                    for row in rows:
                        rid = str(row.get("id") or row.get("variant_id") or "")
                        if not rid:
                            rid = hashlib.md5(json.dumps(row, sort_keys=True).encode()).hexdigest()
                        unique_rows[rid] = row
                    if len(unique_rows) >= limit or not payload.get("next"):
                        break
                    page += 1
                    if page > 3:
                        break
                if len(unique_rows) >= limit:
                    break
        return list(unique_rows.values())[:limit]

    def get_combo_intel(
        self,
        cards: List[str],
        commander: str | List[str] | None = None,
        max_variants: int = 200,
        deck_colors: Iterable[str] | None = None,
    ) -> Dict[str, Any]:
        key = self._cache_key(cards, commander, deck_colors)
        cached = self._read_cache(key)
        if cached:
            return cached

        warnings: List[str] = []
        variants_raw: List[Dict[str, Any]] = []
        attempts = self.retries + 1
        for attempt in range(attempts):
            try:
                query_cards = _commander_list(commander) + cards
                variants_raw = self._fetch_variants_for_cards(query_cards, limit=max_variants)
                break
            except Exception as exc:
                if attempt == attempts - 1:
                    warnings.append(f"CommanderSpellbook unavailable: {exc}")
                else:
                    time.sleep(0.2 * (2**attempt))

        deck_names = {c.strip().lower() for c in cards if c and c.strip()}
        normalized = [_normalize_variant(row, deck_names, commander) for row in variants_raw]
        normalized = [row for row in normalized if row]
        if len(variants_raw) >= max_variants:
            warnings.append(f"CommanderSpellbook results capped at {max_variants} variants; some combo lines may be omitted.")
        matched = [v for v in normalized if v["status"] == "complete"]
        near_miss = [
            v
            for v in normalized
            if v["status"] == "near_miss"
            and int(v.get("missing_count", 99)) == 1
            and _variant_within_color_identity(v.get("identity", ""), deck_colors)
        ]
        matched.sort(key=lambda x: (-x["score"], x["missing_count"], x["variant_id"]))
        near_miss.sort(key=lambda x: (-x["score"], x["missing_count"], x["variant_id"]))
        support_score = 0.0
        if matched:
            top_weight = sum(v["score"] for v in matched[:10]) / min(10, len(matched))
            hit_bonus = min(0.35, len(matched) * 0.07)
            support_score = round(min(100.0, (top_weight + hit_bonus) * 100), 1)

        result = {
            "source": "commanderspellbook",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source_hash": hashlib.sha256(json.dumps(matched, sort_keys=True).encode()).hexdigest() if matched else "",
            "combo_support_score": support_score,
            "matched_variants": matched,
            "near_miss_variants": near_miss,
            "warnings": warnings,
        }
        self._write_cache(key, result)
        return result
