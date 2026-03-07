from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
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
RANDOM_URL = "https://api.scryfall.com/cards/random"
SEARCH_URL = "https://api.scryfall.com/cards/search"
UNIVERSES_BEYOND_SET_TYPES = {"universes_beyond"}
ART_PREFERENCES = {"original", "classic", "clean", "showcase", "newest"}

CARD_FIELDS = [
    "name",
    "oracle_id",
    "mana_cost",
    "cmc",
    "released_at",
    "set_name",
    "set_type",
    "frame",
    "border_color",
    "full_art",
    "promo",
    "promo_types",
    "frame_effects",
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
    "prints_search_uri",
    "image_status",
    "related_cards",
    "all_parts",
    "card_faces",
]


@dataclass(frozen=True)
class QuerySpec:
    label: str
    query: str
    limit: int = 120
    order: str = "name"
    direction: str = "asc"


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


def _scryfall_search_url(card_name: str) -> str:
    query = quote_plus(f'!"{card_name.strip()}"')
    return f"https://scryfall.com/search?q={query}"


def _normalize_art_preference(value: str | None) -> str:
    pref = str(value or "").strip().lower()
    return pref if pref in ART_PREFERENCES else "clean"


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
        if not card.get("released_at"):
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

    def _display_sort_key(self, card: Dict[str, Any]) -> tuple:
        set_type = str(card.get("set_type") or "").strip().lower()
        games = set(card.get("games") or [])
        has_image = self._has_display_payload(card)
        released_at = str(card.get("released_at") or "")
        preferred_set_bucket = 0
        if set_type in {"expansion", "core"}:
            preferred_set_bucket = 4
        elif set_type in {"masters", "commander", "draft_innovation"}:
            preferred_set_bucket = 3
        elif set_type in {"promo", "box", "arsenal", "spellbook"}:
            preferred_set_bucket = 1
        return (
            1 if set_type not in UNIVERSES_BEYOND_SET_TYPES else 0,
            1 if "paper" in games else 0,
            1 if has_image else 0,
            preferred_set_bucket,
            released_at,
        )

    def _is_showcase_like(self, card: Dict[str, Any]) -> bool:
        if bool(card.get("full_art")):
            return True
        if str(card.get("border_color") or "").strip().lower() == "borderless":
            return True
        promo_types = {str(x).strip().lower() for x in (card.get("promo_types") or [])}
        if promo_types & {"showcase", "borderless", "fullart", "concept", "halofoil", "galaxyfoil"}:
            return True
        frame_effects = {str(x).strip().lower() for x in (card.get("frame_effects") or [])}
        if frame_effects & {"showcase", "extendedart", "legendary", "inverted", "etched", "snow", "shatteredglass"}:
            return True
        return False

    def _frame_rank(self, card: Dict[str, Any]) -> int:
        frame = str(card.get("frame") or "").strip().lower()
        if frame in {"1993", "1997"}:
            return 3
        if frame == "2003":
            return 2
        if frame in {"2015", "future"}:
            return 0
        return 1

    def _is_regular_modern_printing(self, card: Dict[str, Any]) -> bool:
        set_type = str(card.get("set_type") or "").strip().lower()
        if self._is_showcase_like(card):
            return False
        if bool(card.get("promo")):
            return False
        if set_type in {"promo", "box", "arsenal", "spellbook"}:
            return False
        return True

    def _art_preference_sort_key(self, card: Dict[str, Any], art_preference: str) -> tuple:
        art_preference = _normalize_art_preference(art_preference)
        released_at = str(card.get("released_at") or "")
        set_type = str(card.get("set_type") or "").strip().lower()
        showcase_like = self._is_showcase_like(card)
        regular_modern = self._is_regular_modern_printing(card)
        frame_rank = self._frame_rank(card)
        set_bucket = 0
        if set_type in {"expansion", "core"}:
            set_bucket = 4
        elif set_type in {"masters", "commander", "draft_innovation"}:
            set_bucket = 3
        elif set_type in {"promo", "box", "arsenal", "spellbook"}:
            set_bucket = 1

        if art_preference == "original":
            # "Original Printing" should mean the earliest viable paper printing,
            # not "the oldest regular modern-looking printing".
            return (
                released_at or "9999-12-31",
                0 if not bool(card.get("promo")) else 1,
                0 if not showcase_like else 1,
                -set_bucket,
                -frame_rank,
                str(card.get("set") or ""),
                str(card.get("name") or ""),
            )
        if art_preference == "classic":
            return (-frame_rank, 0 if not showcase_like else 1, -set_bucket, released_at)
        if art_preference == "showcase":
            return (1 if showcase_like else 0, 1 if bool(card.get("promo")) else 0, released_at, set_bucket)
        if art_preference == "newest":
            return (released_at, 1 if regular_modern else 0, set_bucket)
        return (1 if regular_modern else 0, set_bucket, released_at)

    def _get_print_candidates(self, card: Dict[str, Any]) -> List[Dict[str, Any]]:
        oracle_id = str(card.get("oracle_id") or "").strip()
        if not oracle_id:
            return []
        cache_key = f"scryfall:prints:{oracle_id}"
        cached = self._cache_json_get(cache_key)
        if isinstance(cached, list) and cached:
            return [_as_payload(row) for row in cached]

        prints_search_uri = str(card.get("prints_search_uri") or "").strip()
        search_query = f'oracleid:{oracle_id} unique:prints game:paper'
        candidates: List[Dict[str, Any]] = []
        try:
            with httpx.Client(timeout=20) as client:
                next_url = prints_search_uri
                while next_url:
                    resp = client.get(next_url)
                    if resp.status_code >= 400:
                        break
                    payload = resp.json()
                    rows = payload.get("data", [])
                    if isinstance(rows, list):
                        candidates.extend(rows)
                    if len(candidates) >= 80:
                        break
                    next_url = str(payload.get("next_page") or "").strip() if payload.get("has_more") else ""
                if not candidates:
                    resp = client.get(SEARCH_URL, params={"q": search_query, "unique": "prints"})
                    if resp.status_code < 400:
                        payload = resp.json()
                        rows = payload.get("data", [])
                        if isinstance(rows, list):
                            candidates.extend(rows)
        except Exception:
            candidates = []

        trimmed = [{k: row.get(k) for k in CARD_FIELDS + ["games"]} for row in candidates]
        if trimmed:
            self._cache_json_set(cache_key, trimmed, ttl_seconds=7 * 86400)
        return trimmed

    def _preferred_non_ub_display_card(self, card: Dict[str, Any], art_preference: str = "clean") -> Dict[str, Any]:
        if not card:
            return {}
        art_preference = _normalize_art_preference(art_preference)
        set_type = str(card.get("set_type") or "").strip().lower()
        candidates = self._get_print_candidates(card)
        if not candidates:
            if not set_type or set_type not in UNIVERSES_BEYOND_SET_TYPES:
                return card

        viable = [
            candidate
            for candidate in candidates
            if str(candidate.get("set_type") or "").strip().lower() not in UNIVERSES_BEYOND_SET_TYPES
            and self._has_display_payload(candidate)
            and ("paper" in set(candidate.get("games") or []))
        ]
        if viable:
            reverse = art_preference not in {"original", "classic"}
            chosen = sorted(viable, key=lambda candidate: self._art_preference_sort_key(candidate, art_preference), reverse=reverse)[0]
            return {k: chosen.get(k) for k in CARD_FIELDS}

        fallback = {k: card.get(k) for k in CARD_FIELDS}
        if not set_type or set_type not in UNIVERSES_BEYOND_SET_TYPES:
            return fallback
        fallback["image_uris"] = {}
        fallback["card_faces"] = []
        fallback["scryfall_uri"] = _scryfall_search_url(card.get("name") or "")
        return fallback

    def get_cards_by_name(self, names: List[str]) -> Dict[str, Dict[str, Any]]:
        names = [n.strip() for n in names if n and n.strip()]
        if not names:
            return {}
        cached = self._get_cached_by_name(names)
        stale = [
            n
            for n, card in cached.items()
            if not self._has_display_payload(card)
            or not self._has_sim_payload(card)
            or card.get("set_type") is None
            or card.get("frame") is None
            or card.get("border_color") is None
            or card.get("promo_types") is None
        ]
        missing = [n for n in names if n not in cached]
        to_fetch = sorted(set(missing + stale))
        if to_fetch:
            fetched = self.fetch_collection_by_name(to_fetch)
            self._store_cards(fetched)
            cached.update(self._get_cached_by_name(to_fetch))
        return cached

    def card_display(self, card: Dict[str, Any], art_preference: str = "clean") -> Dict[str, Any]:
        display_card = self._preferred_non_ub_display_card(card, art_preference=art_preference) or card or {}
        image_uris = display_card.get("image_uris") or {}
        faces = display_card.get("card_faces") or []
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

        card_name = display_card.get("name") or card.get("name") or ""
        cardmarket_url = _cardmarket_card_url(card_name)
        return {
            "name": card_name,
            "small": image_uris.get("small"),
            "normal": image_uris.get("normal"),
            "art_crop": image_uris.get("art_crop"),
            "face_images": face_images,
            "scryfall_uri": display_card.get("scryfall_uri") or card.get("scryfall_uri") or _scryfall_search_url(card_name),
            "cardmarket_url": cardmarket_url,
            "prices": display_card.get("prices") or card.get("prices") or {},
            "art_preference": _normalize_art_preference(art_preference),
        }

    def get_display_by_names(self, names: List[str], art_preference: str = "clean") -> Dict[str, Dict[str, Any]]:
        card_map = self.get_cards_by_name(names)
        return {name: self.card_display(card_map.get(name, {}), art_preference=art_preference) for name in names if name in card_map}

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

    def fetch_random_card(self, query: str) -> Dict[str, Any]:
        with httpx.Client(timeout=30) as client:
            resp = client.get(RANDOM_URL, params={"q": query})
            resp.raise_for_status()
            payload = resp.json()
        return {k: payload.get(k) for k in CARD_FIELDS + ["games"]}

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
        if missing_cards:
            with httpx.Client(timeout=20) as client:
                for card in missing_cards:
                    oid = card.get("oracle_id")
                    uri = card.get("rulings_uri")
                    if not oid or not uri:
                        continue
                    try:
                        resp = client.get(uri)
                        resp.raise_for_status()
                        rows = resp.json().get("data", [])
                    except Exception:
                        # Do not cache transient failures as empty forever.
                        continue
                    fetched[oid] = rows if isinstance(rows, list) else []
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

    def search_candidates(
        self,
        query: str,
        color_identity: str | None,
        limit: int = 10,
        order: str = "name",
        direction: str = "asc",
    ) -> List[Dict[str, Any]]:
        cache_key = f"scryfall:search:{hashlib.sha256(json.dumps({'q': query, 'ci': color_identity, 'limit': limit, 'order': order, 'direction': direction}, sort_keys=True).encode()).hexdigest()}"
        cached = self._cache_json_get(cache_key)
        if isinstance(cached, list):
            return cached
        ci = None if color_identity is None else (color_identity or "").upper()
        ci_filter = f"id<={ci}" if ci else ("id:c" if color_identity == "" else "")
        q = " ".join(part for part in [query, ci_filter, "game:paper", "legal:commander"] if part)
        with httpx.Client(timeout=30) as client:
            params: Dict[str, Any] = {"q": q, "unique": "cards"}
            if order:
                params["order"] = order
            if direction and order in {"name", "set", "released", "cmc", "power", "toughness", "usd", "eur", "tix", "edhrec", "artist"}:
                params["dir"] = direction
            data: List[Dict[str, Any]] = []
            next_page: str | None = SEARCH_URL
            first_page = True
            while next_page and len(data) < max(limit, 1):
                resp = client.get(next_page, params=params if first_page else None)
                first_page = False
                if resp.status_code >= 400:
                    break
                payload = resp.json()
                data.extend(payload.get("data", []) or [])
                next_page = payload.get("next_page") if payload.get("has_more") else None
        ci_set = set(ci or "")
        out = []
        seen_oracles = set()
        for d in data:
            card_ci = set(d.get("color_identity") or [])
            if ci_set:
                if not card_ci.issubset(ci_set):
                    continue
            else:
                if color_identity == "" and card_ci:
                    continue
            oracle_id = str(d.get("oracle_id") or "")
            if oracle_id and oracle_id in seen_oracles:
                continue
            if oracle_id:
                seen_oracles.add(oracle_id)
            out.append({k: d.get(k) for k in CARD_FIELDS})
            if len(out) >= limit:
                break
        self._cache_json_set(cache_key, out)
        return out

    def annotate_popularity_percentile(self, cards: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        rows = [dict(card) for card in cards]
        ranked = sorted(
            [(idx, int(card.get("edhrec_rank"))) for idx, card in enumerate(rows) if card.get("edhrec_rank") not in (None, "")],
            key=lambda row: row[1],
        )
        if not ranked:
            for row in rows:
                row["popularity_pct"] = None
            return rows
        total = len(ranked)
        pct_by_idx: Dict[int, float] = {}
        for pos, (idx, _rank) in enumerate(ranked):
            pct_by_idx[idx] = round((pos + 1) / total, 4)
        for idx, row in enumerate(rows):
            row["popularity_pct"] = pct_by_idx.get(idx)
        return rows

    def search_union(
        self,
        queries: Iterable[QuerySpec],
        color_identity: str | None,
    ) -> List[Dict[str, Any]]:
        specs = list(queries)
        cache_key = f"scryfall:search-union:{hashlib.sha256(json.dumps({'queries': [spec.__dict__ for spec in specs], 'ci': color_identity}, sort_keys=True).encode()).hexdigest()}"
        cached = self._cache_json_get(cache_key)
        if isinstance(cached, list):
            return cached

        merged: Dict[str, Dict[str, Any]] = {}
        for spec in specs:
            results = self.search_candidates(
                spec.query,
                color_identity,
                limit=spec.limit,
                order=spec.order,
                direction=spec.direction,
            )
            for card in results:
                oracle_id = str(card.get("oracle_id") or "")
                dedupe_key = oracle_id or _safe_union_fallback_key(card)
                if not dedupe_key:
                    continue
                if dedupe_key not in merged:
                    merged[dedupe_key] = dict(card)
                    merged[dedupe_key]["matched_queries"] = []
                labels = merged[dedupe_key]["matched_queries"]
                if spec.label not in labels:
                    labels.append(spec.label)

        out = self.annotate_popularity_percentile(merged.values())
        self._cache_json_set(cache_key, out)
        return out


def _safe_union_fallback_key(card: Dict[str, Any]) -> str:
    return str(card.get("name") or "").strip().lower()
