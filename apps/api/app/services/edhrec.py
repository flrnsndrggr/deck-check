from __future__ import annotations

import json
import re
from typing import Any, Dict, List

import httpx

from app.workers.queue import redis_conn

EDHREC_COMMANDER_JSON = "https://json.edhrec.com/pages/commanders/{slug}.json"


def _slugify_commander(name: str) -> str:
    slug = name.strip().lower()
    slug = slug.replace("'", "")
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


def _score_from_node(node: Dict[str, Any], rank_hint: int) -> float:
    # Prefer explicit relevance fields when present, then fallback to rank.
    for key in ("synergy", "score", "value"):
        try:
            if node.get(key) is not None:
                return float(node.get(key))
        except Exception:
            continue
    try:
        decks = float(node.get("num_decks") or node.get("decks") or 0.0)
    except Exception:
        decks = 0.0
    return decks + max(0.0, 100.0 - rank_hint)


def _walk_collect_cards(obj: Any, out: Dict[str, float], rank: List[int]) -> None:
    if isinstance(obj, dict):
        n = obj.get("name")
        if isinstance(n, str) and n.strip():
            name = n.strip()
            # Avoid obviously non-card labels.
            if 1 <= len(name) <= 80 and not name.lower().startswith("https://"):
                out[name] = max(out.get(name, float("-inf")), _score_from_node(obj, rank[0]))
                rank[0] += 1
        for v in obj.values():
            _walk_collect_cards(v, out, rank)
        return
    if isinstance(obj, list):
        for it in obj:
            _walk_collect_cards(it, out, rank)


class EDHRecService:
    def __init__(self, timeout_s: float = 8.0, ttl_seconds: int = 86400):
        self.timeout_s = timeout_s
        self.ttl_seconds = ttl_seconds

    def _cache_key(self, commander: str) -> str:
        return f"edhrec:commander:{_slugify_commander(commander)}"

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

    def get_commander_cards(self, commander: str | None, limit: int = 120) -> Dict[str, Any]:
        if not commander or not commander.strip():
            return {"source": "edhrec", "cards": [], "warning": "No commander provided."}

        key = self._cache_key(commander)
        cached = self._read_cache(key)
        if cached:
            return cached

        slug = _slugify_commander(commander)
        url = EDHREC_COMMANDER_JSON.format(slug=slug)
        warning = ""
        cards: List[Dict[str, Any]] = []
        try:
            with httpx.Client(timeout=self.timeout_s, follow_redirects=True) as client:
                resp = client.get(url)
                if resp.status_code >= 400:
                    warning = f"EDHREC unavailable for commander slug '{slug}' (status {resp.status_code})."
                else:
                    payload = resp.json()
                    found: Dict[str, float] = {}
                    _walk_collect_cards(payload, found, rank=[0])
                    cards = [{"name": n, "edhrec_score": s} for n, s in sorted(found.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]
        except Exception as exc:
            warning = f"EDHREC request failed: {type(exc).__name__}: {exc}"

        result = {
            "source": "edhrec",
            "slug": slug,
            "cards": cards,
            "warning": warning,
        }
        self._write_cache(key, result)
        return result

