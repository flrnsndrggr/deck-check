from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

from app.workers.queue import redis_conn


def simulation_cache_key(payload: Dict[str, Any]) -> str:
    stable = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(stable.encode()).hexdigest()
    return f"simcache:{digest}"


def get_cached_simulation(payload: Dict[str, Any]) -> Dict[str, Any] | None:
    key = simulation_cache_key(payload)
    raw = redis_conn.get(key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def set_cached_simulation(payload: Dict[str, Any], result: Dict[str, Any], ttl_seconds: int = 86400):
    key = simulation_cache_key(payload)
    redis_conn.setex(key, ttl_seconds, json.dumps(result))
