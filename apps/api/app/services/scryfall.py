from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List
from urllib.parse import quote, quote_plus

import httpx
from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.scryfall_cache import ScryfallCard, ScryfallName, ScryfallRuling
from app.workers.queue import redis_conn

BULK_DATA_URL = "https://api.scryfall.com/bulk-data"
COLLECTION_URL = "https://api.scryfall.com/cards/collection"
NAMED_URL = "https://api.scryfall.com/cards/named"

CARD_FIELDS = [
    "name",
    "oracle_id",
    "mana_cost",
    "cmc",
    "power",
    "toughness",
    "type_line",
    "oracle_text",
    "colors",
    "color_identity",
    "keywords",
    "produced_mana",
    "legalities",
    "games",
    "rarity",
    "set",
    "edhrec_rank",
    "prices",
    "purchase_uris",
    "cardmarket_id",
    "image_uris",
    "layout",
    "scryfall_uri",
    "rulings_uri",
    "image_status",
    "related_cards",
    "all_parts",
    "card_faces",
]


def _as_payload(obj: Any) -> Dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, str):
        try:
            return json.loads(obj)
        except Exception:
            return {}
    return {}


def _cardmarket_card_url(card_name: str) -> str:
    if not card_name:
        return "https://www.cardmarket.com/en/Magic/Products/Search"
    normalized = re.sub(r"\s*//\s*", " ", card_name.strip())
    normalized = normalized.replace("’", "'")
    slug = re.sub(r"[^A-Za-z0-9\s-]", "", normalized)
    slug = re.sub(r"\s+", "-", slug.strip())
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        search = quote_plus(card_name.strip())
        return f"https://www.cardmarket.com/en/Magic/Products/Search?searchString={search}"
    return (
        f"https://www.cardmarket.com/en/Magic/Cards/{quote(slug)}"
        "?sellerCountry=4&language=1&minCondition=3"
    )


class CardDataService:
    def __init__(self, db_path: str | None = None, backend: str | None = None):
        self.backend = (backend or settings.card_cache_backend or "sqlite").lower()
        self.use_postgres = self.backend == "postgres"
        self.db_path = db_path or settings.card_cache_db

        if not self.use_postgres:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self._init_db()

    # sqlite backend
    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cards (
                    oracle_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS names (
                    name TEXT PRIMARY KEY,
                    oracle_id TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rulings (
                    oracle_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _sqlite_store_cards(self, cards: Iterable[Dict[str, Any]]):
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            for card in cards:
                if not card.get("oracle_id"):
                    continue
                payload = {k: card.get(k) for k in CARD_FIELDS}
                conn.execute(
                    "INSERT OR REPLACE INTO cards(oracle_id, name, payload, updated_at) VALUES(?,?,?,?)",
                    (card["oracle_id"], card.get("name", ""), json.dumps(payload), now),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO names(name, oracle_id) VALUES(?,?)",
                    (card.get("name", ""), card["oracle_id"]),
                )
                for face in card.get("card_faces") or []:
                    if face.get("name"):
                        conn.execute(
                            "INSERT OR REPLACE INTO names(name, oracle_id) VALUES(?,?)",
                            (face["name"], card["oracle_id"]),
                        )
            conn.commit()

    def _sqlite_get_cached_by_name(self, names: List[str]) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        with self._connect() as conn:
            for name in names:
                row = conn.execute(
                    "SELECT c.payload FROM names n JOIN cards c ON c.oracle_id=n.oracle_id WHERE n.name=?",
                    (name,),
                ).fetchone()
                if row:
                    out[name] = _as_payload(row[0])
        return out

    def _sqlite_get_cached_rulings(self, oracle_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        out: Dict[str, List[Dict[str, Any]]] = {}
        with self._connect() as conn:
            for oid in oracle_ids:
                row = conn.execute("SELECT payload FROM rulings WHERE oracle_id=?", (oid,)).fetchone()
                if row:
                    try:
                        out[oid] = json.loads(row[0])
                    except Exception:
                        continue
        return out

    def _sqlite_store_rulings(self, payload: Dict[str, List[Dict[str, Any]]]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            for oid, rows in payload.items():
                conn.execute(
                    "INSERT OR REPLACE INTO rulings(oracle_id, payload, updated_at) VALUES(?,?,?)",
                    (oid, json.dumps(rows), now),
                )
            conn.commit()

    # postgres backend
    def _pg_store_cards(self, cards: Iterable[Dict[str, Any]]) -> None:
        with SessionLocal() as db:
            for card in cards:
                oid = card.get("oracle_id")
                if not oid:
                    continue
                payload = {k: card.get(k) for k in CARD_FIELDS}
                row = db.execute(select(ScryfallCard).where(ScryfallCard.oracle_id == oid)).scalar_one_or_none()
                if row is None:
                    row = ScryfallCard(oracle_id=oid, name=card.get("name", ""), payload=payload)
                    db.add(row)
                else:
                    row.name = card.get("name", "")
                    row.payload = payload

                names = {card.get("name", "")}
                for face in card.get("card_faces") or []:
                    if face.get("name"):
                        names.add(face["name"])
                for nm in names:
                    if not nm:
                        continue
                    nrow = db.get(ScryfallName, nm)
                    if nrow is None:
                        db.add(ScryfallName(name=nm, oracle_id=oid))
                    else:
                        nrow.oracle_id = oid
            db.commit()

    def _pg_get_cached_by_name(self, names: List[str]) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        with SessionLocal() as db:
            for name in names:
                row = db.execute(
                    select(ScryfallCard.payload)
                    .join(ScryfallName, ScryfallName.oracle_id == ScryfallCard.oracle_id)
                    .where(ScryfallName.name == name)
                ).first()
                if row:
                    out[name] = _as_payload(row[0])
        return out

    def _pg_get_cached_rulings(self, oracle_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        out: Dict[str, List[Dict[str, Any]]] = {}
        if not oracle_ids:
            return out
        with SessionLocal() as db:
            rows = db.execute(select(ScryfallRuling).where(ScryfallRuling.oracle_id.in_(oracle_ids))).scalars().all()
            for row in rows:
                payload = _as_payload(row.payload)
                out[row.oracle_id] = payload if isinstance(payload, list) else []
        return out

    def _pg_store_rulings(self, payload: Dict[str, List[Dict[str, Any]]]) -> None:
        with SessionLocal() as db:
            for oid, rows in payload.items():
                row = db.get(ScryfallRuling, oid)
                if row is None:
                    db.add(ScryfallRuling(oracle_id=oid, payload=rows))
                else:
                    row.payload = rows
            db.commit()

    # shared API
    def _store_cards(self, cards: Iterable[Dict[str, Any]]):
        if self.use_postgres:
            self._pg_store_cards(cards)
            return
        self._sqlite_store_cards(cards)

    def _get_cached_by_name(self, names: List[str]) -> Dict[str, Dict[str, Any]]:
        if self.use_postgres:
            return self._pg_get_cached_by_name(names)
        return self._sqlite_get_cached_by_name(names)

    def _get_cached_rulings(self, oracle_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        if self.use_postgres:
            return self._pg_get_cached_rulings(oracle_ids)
        return self._sqlite_get_cached_rulings(oracle_ids)

    def _store_rulings(self, payload: Dict[str, List[Dict[str, Any]]]) -> None:
        if self.use_postgres:
            self._pg_store_rulings(payload)
            return
        self._sqlite_store_rulings(payload)

    def _has_display_payload(self, card: Dict[str, Any]) -> bool:
        img = card.get("image_uris") or {}
        if isinstance(img, dict) and img.get("normal"):
            return True
        for face in card.get("card_faces") or []:
            if (face.get("image_uris") or {}).get("normal"):
                return True
        return False

    def _has_sim_payload(self, card: Dict[str, Any]) -> bool:
        type_line = str(card.get("type_line") or "")
        if not type_line or card.get("oracle_text") is None:
            return False
        if "Creature" in type_line and card.get("power") is None:
            return False
        return True

    def _cache_json_get(self, key: str) -> Any | None:
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

    def _cache_json_set(self, key: str, payload: Any, ttl_seconds: int = 86400) -> None:
        try:
            redis_conn.setex(key, ttl_seconds, json.dumps(payload))
        except Exception:
            return

    def get_cards_by_name(self, names: List[str]) -> Dict[str, Dict[str, Any]]:
        names = [n.strip() for n in names if n and n.strip()]
        if not names:
            return {}
        cached = self._get_cached_by_name(names)
        stale = [n for n, card in cached.items() if not self._has_display_payload(card) or not self._has_sim_payload(card)]
        missing = [n for n in names if n not in cached]
        to_fetch = sorted(set(missing + stale))
        if to_fetch:
            fetched = self.fetch_collection_by_name(to_fetch)
            self._store_cards(fetched)
            cached.update(self._get_cached_by_name(to_fetch))
        return cached

    def card_display(self, card: Dict[str, Any]) -> Dict[str, Any]:
        image_uris = card.get("image_uris") or {}
        faces = card.get("card_faces") or []
        face_images = []
        for face in faces:
            fu = face.get("image_uris") or {}
            face_images.append(
                {
                    "name": face.get("name"),
                    "small": fu.get("small"),
                    "normal": fu.get("normal"),
                    "art_crop": fu.get("art_crop"),
                }
            )

        if not image_uris and face_images:
            image_uris = {
                "small": face_images[0].get("small"),
                "normal": face_images[0].get("normal"),
                "art_crop": face_images[0].get("art_crop"),
            }

        cardmarket_url = _cardmarket_card_url(card.get("name") or "")
        return {
            "name": card.get("name"),
            "small": image_uris.get("small"),
            "normal": image_uris.get("normal"),
            "art_crop": image_uris.get("art_crop"),
            "face_images": face_images,
            "scryfall_uri": card.get("scryfall_uri"),
            "cardmarket_url": cardmarket_url,
            "prices": card.get("prices") or {},
        }

    def get_display_by_names(self, names: List[str]) -> Dict[str, Dict[str, Any]]:
        card_map = self.get_cards_by_name(names)
        return {name: self.card_display(card_map.get(name, {})) for name in names if name in card_map}

    def _fetch_named_card(self, client: httpx.Client, name: str) -> Dict[str, Any] | None:
        candidates = [name]
        if "//" not in name and "/" in name:
            candidates.append(re.sub(r"\s*/\s*", " // ", name.strip()))

        seen: set[str] = set()
        for candidate in candidates:
            candidate = candidate.strip()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            for params in ({"exact": candidate}, {"fuzzy": candidate}):
                try:
                    resp = client.get(NAMED_URL, params=params)
                    if resp.status_code >= 400:
                        continue
                    payload = resp.json()
                    if payload.get("object") == "error":
                        continue
                    return payload
                except Exception:
                    continue
        return None

    def fetch_collection_by_name(self, names: List[str]) -> List[Dict[str, Any]]:
        cards: List[Dict[str, Any]] = []
        with httpx.Client(timeout=30) as client:
            for i in range(0, len(names), 70):
                chunk = names[i : i + 70]
                identifiers = [{"name": n} for n in chunk]
                resp = client.post(COLLECTION_URL, json={"identifiers": identifiers})
                resp.raise_for_status()
                payload = resp.json()
                cards.extend(payload.get("data", []))

                missing_names = [row.get("name") for row in payload.get("not_found", []) if row.get("name")]
                for missing_name in missing_names:
                    fallback = self._fetch_named_card(client, missing_name)
                    if fallback:
                        cards.append(fallback)
        return cards

    def get_rulings_by_oracle_id(self, card_map: Dict[str, Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        oracle_ids = [c.get("oracle_id") for c in card_map.values() if c.get("oracle_id")]
        cached = self._get_cached_rulings(oracle_ids)
        missing_cards = [c for c in card_map.values() if c.get("oracle_id") not in cached and c.get("rulings_uri")]
        fetched: Dict[str, List[Dict[str, Any]]] = {}
        for card in missing_cards[:30]:
            oid = card.get("oracle_id")
            uri = card.get("rulings_uri")
            if not oid or not uri:
                continue
            try:
                with httpx.Client(timeout=20) as client:
                    resp = client.get(uri)
                    resp.raise_for_status()
                    rows = resp.json().get("data", [])
                fetched[oid] = rows
            except Exception:
                fetched[oid] = []
        if fetched:
            self._store_rulings(fetched)
            cached.update(fetched)
        return cached

    def refresh_bulk_snapshot(self) -> Dict[str, str]:
        bulk_path = Path(settings.scryfall_bulk_path)
        bulk_path.parent.mkdir(parents=True, exist_ok=True)
        with httpx.Client(timeout=60) as client:
            data = client.get(BULK_DATA_URL).json().get("data", [])
            oracle = next((d for d in data if d.get("type") == "oracle_cards"), None)
            if oracle is None:
                raise RuntimeError("oracle_cards bulk dataset not found")
            dl = client.get(oracle["download_uri"])
            dl.raise_for_status()
            content = dl.content

        bulk_path.write_bytes(content)
        checksum = hashlib.sha256(content).hexdigest()
        return {
            "source_url": oracle["download_uri"],
            "checksum": checksum,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def ingest_bulk_snapshot(self, limit: int | None = None):
        bulk_path = Path(settings.scryfall_bulk_path)
        if not bulk_path.exists():
            return
        cards = json.loads(bulk_path.read_text())
        if limit:
            cards = cards[:limit]
        self._store_cards(cards)

    def search_candidates(self, query: str, color_identity: str, limit: int = 10) -> List[Dict[str, Any]]:
        cache_key = f"scryfall:search:{hashlib.sha256(json.dumps({'q': query, 'ci': color_identity, 'limit': limit}, sort_keys=True).encode()).hexdigest()}"
        cached = self._cache_json_get(cache_key)
        if isinstance(cached, list):
            return cached
        url = "https://api.scryfall.com/cards/search"
        ci = (color_identity or "").upper()
        ci_filter = f"id<={ci}" if ci else "id:c"
        q = f"{query} {ci_filter} game:paper legal:commander"
        with httpx.Client(timeout=30) as client:
            resp = client.get(url, params={"q": q, "order": "edhrec", "unique": "cards"})
            if resp.status_code >= 400:
                return []
            data = resp.json().get("data", [])
        ci_set = set(ci)
        out = []
        for d in data:
            card_ci = set(d.get("color_identity") or [])
            if ci_set:
                if not card_ci.issubset(ci_set):
                    continue
            else:
                if card_ci:
                    continue
            out.append({k: d.get(k) for k in CARD_FIELDS})
            if len(out) >= limit:
                break
        self._cache_json_set(cache_key, out)
        return out
