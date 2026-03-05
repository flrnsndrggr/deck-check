from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Tuple
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup


MOXFIELD_API_CANDIDATES = [
    "https://api2.moxfield.com/v3/decks/all/{deck_id}",
    "https://api2.moxfield.com/v2/decks/all/{deck_id}",
]

ARCHIDEKT_API_CANDIDATE = "https://archidekt.com/api/decks/{deck_id}/"


def extract_moxfield_deck_id(url: str) -> str | None:
    parsed = urlparse(url.strip())
    host = (parsed.netloc or "").lower()
    if "moxfield.com" not in host:
        return None

    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 2 and parts[0].lower() == "decks":
        return parts[1]
    return None


def extract_archidekt_deck_id(url: str) -> str | None:
    parsed = urlparse(url.strip())
    host = (parsed.netloc or "").lower()
    if "archidekt.com" not in host:
        return None

    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 2 and parts[0].lower() == "decks":
        return parts[1]
    return None


def _coerce_int(value: Any, default: int = 1) -> int:
    try:
        out = int(value)
        return out if out > 0 else default
    except Exception:
        return default


def _extract_card_name(key: str, value: Any) -> str:
    if isinstance(value, dict):
        card_obj = value.get("card") if isinstance(value.get("card"), dict) else {}
        return (
            card_obj.get("name")
            or value.get("name")
            or value.get("cardName")
            or key
        )
    return key


def _extract_qty(value: Any) -> int:
    if isinstance(value, dict):
        return _coerce_int(value.get("quantity") or value.get("qty") or value.get("count") or 1)
    if isinstance(value, (int, float)):
        return _coerce_int(value)
    return 1


def _board_to_entries(board: Any) -> List[Tuple[int, str]]:
    if isinstance(board, dict) and isinstance(board.get("cards"), (dict, list)):
        board = board["cards"]

    out: List[Tuple[int, str]] = []
    if isinstance(board, dict):
        for key, value in board.items():
            name = _extract_card_name(str(key), value)
            qty = _extract_qty(value)
            if name:
                out.append((qty, name))
    elif isinstance(board, list):
        for item in board:
            if not isinstance(item, dict):
                continue
            name = _extract_card_name(item.get("name", ""), item)
            qty = _extract_qty(item)
            if name:
                out.append((qty, name))
    return out


def _find_boards_like(obj: Any) -> Dict[str, Any] | None:
    if isinstance(obj, dict):
        keys = {k.lower() for k in obj.keys()}
        if "boards" in obj and isinstance(obj["boards"], dict):
            return obj["boards"]
        boardish = {"mainboard", "deck", "commander", "commanders", "sideboard", "companion", "companions"}
        if keys & boardish:
            return obj
        for value in obj.values():
            found = _find_boards_like(value)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_boards_like(item)
            if found is not None:
                return found
    return None


def decklist_from_moxfield_payload(payload: Dict[str, Any]) -> str:
    boards = _find_boards_like(payload)
    if boards is None:
        raise ValueError("Could not locate deck boards in Moxfield payload.")

    alias_map = {
        "Commander": ["commander", "commanders"],
        "Deck": ["mainboard", "deck", "main"],
        "Sideboard": ["sideboard", "side"],
        "Companion": ["companion", "companions"],
    }

    lines: List[str] = []
    for section, aliases in alias_map.items():
        section_entries: List[Tuple[int, str]] = []
        for alias in aliases:
            key = next((k for k in boards.keys() if k.lower() == alias), None)
            if key is None:
                continue
            section_entries.extend(_board_to_entries(boards[key]))
        if section_entries:
            lines.append(section)
            lines.extend([f"{qty} {name}" for qty, name in section_entries])
            lines.append("")

    decklist = "\n".join(lines).strip()
    if not decklist:
        raise ValueError("No cards found in imported payload.")
    return decklist


def _try_parse_json_from_html(html: str) -> Dict[str, Any] | None:
    soup = BeautifulSoup(html, "html.parser")
    next_data = soup.find("script", {"id": "__NEXT_DATA__"})
    if next_data and next_data.string:
        try:
            return json.loads(next_data.string)
        except Exception:
            pass

    for script in soup.find_all("script", {"type": "application/json"}):
        content = script.string or script.get_text() or ""
        if not content.strip():
            continue
        try:
            return json.loads(content)
        except Exception:
            continue
    return None


def decklist_from_archidekt_payload(payload: Dict[str, Any]) -> str:
    rows = payload.get("cards") or []
    lines: List[str] = []
    commander_entries: List[str] = []
    deck_entries: List[str] = []
    side_entries: List[str] = []

    for row in rows:
        card_obj = row.get("card") or {}
        oracle = card_obj.get("oracleCard") or {}
        name = (
            card_obj.get("displayName")
            or card_obj.get("name")
            or oracle.get("name")
            or (oracle.get("faces") or [{}])[0].get("name")
        )
        if not name:
            continue
        qty = _coerce_int(row.get("quantity") or 1)
        categories = [str(c).lower() for c in (row.get("categories") or [])]
        entry = f"{qty} {name}"
        if "commander" in categories:
            commander_entries.append(entry)
        elif "sideboard" in categories or "maybeboard" in categories:
            side_entries.append(entry)
        else:
            deck_entries.append(entry)

    if commander_entries:
        lines.append("Commander")
        lines.extend(commander_entries)
        lines.append("")
    if deck_entries:
        lines.append("Deck")
        lines.extend(deck_entries)
        lines.append("")
    if side_entries:
        lines.append("Sideboard")
        lines.extend(side_entries)
        lines.append("")

    decklist = "\n".join(lines).strip()
    if not decklist:
        raise ValueError("No cards found in Archidekt payload.")
    return decklist


def import_decklist_from_url(url: str) -> Tuple[str, str, List[str]]:
    deck_id = extract_moxfield_deck_id(url)
    archidekt_id = extract_archidekt_deck_id(url)
    if deck_id is None and archidekt_id is None:
        raise ValueError("Supported URL import hosts: Moxfield, Archidekt. Paste text export as fallback.")

    warnings: List[str] = []
    headers = {"User-Agent": "Deck.Check/0.1 (+https://localhost)"}

    with httpx.Client(timeout=20, follow_redirects=True, headers=headers) as client:
        if archidekt_id is not None:
            endpoint = ARCHIDEKT_API_CANDIDATE.format(deck_id=archidekt_id)
            try:
                resp = client.get(endpoint)
                resp.raise_for_status()
                payload = resp.json()
                decklist = decklist_from_archidekt_payload(payload)
                return decklist, endpoint, warnings
            except Exception as exc:
                raise ValueError(f"Archidekt URL import failed: {exc}. Paste text export as fallback.")

        for api_url in MOXFIELD_API_CANDIDATES:
            endpoint = api_url.format(deck_id=deck_id)
            try:
                resp = client.get(endpoint)
                if resp.status_code >= 400:
                    warnings.append(f"Moxfield API endpoint failed: {endpoint} ({resp.status_code})")
                    continue
                payload = resp.json()
                decklist = decklist_from_moxfield_payload(payload)
                return decklist, endpoint, warnings
            except Exception:
                warnings.append(f"Moxfield API endpoint parse failed: {endpoint}")

        # Fallback: HTML -> embedded JSON extraction
        html_resp = client.get(url)
        if html_resp.status_code >= 400:
            raise ValueError("Moxfield URL could not be fetched. Paste text export as fallback.")

        embedded_json = _try_parse_json_from_html(html_resp.text)
        if embedded_json is None:
            raise ValueError("Could not parse Moxfield page payload. Paste text export as fallback.")

        decklist = decklist_from_moxfield_payload(embedded_json)
        warnings.append("Imported via HTML payload fallback instead of direct API.")
        return decklist, url, warnings
