from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Set

from app.core.config import settings
from app.schemas.deck import CardEntry
from app.services.parser import singleton_violations

BASIC_LANDS = {
    "Plains",
    "Island",
    "Swamp",
    "Mountain",
    "Forest",
    "Wastes",
    "Snow-Covered Plains",
    "Snow-Covered Island",
    "Snow-Covered Swamp",
    "Snow-Covered Mountain",
    "Snow-Covered Forest",
}

DEFAULT_BRACKET_LIMITS = {1: 0, 2: 0, 3: 2, 4: 5, 5: 100}

DEFAULT_BRACKET_PROFILES = {
    "1": {
        "name": "Low-Power Social",
        "criteria": [
            {
                "key": "game_changers",
                "label": "Game Changers",
                "source": "official",
                "type": "max",
                "max": 0,
                "description": "Official bracket cap for Game Changer cards.",
                "card_source": "game_changers",
            },
            {
                "key": "tutor_density",
                "label": "Tutors",
                "source": "heuristic",
                "type": "max",
                "max": 2,
                "description": "Lower tutor density preserves variance and casual pacing.",
                "tags": ["#Tutor"],
            },
            {
                "key": "fast_mana_density",
                "label": "Fast Mana",
                "source": "heuristic",
                "type": "max",
                "max": 2,
                "description": "Fast acceleration spikes early turns and can overpower slower tables.",
                "tags": ["#FastMana"],
            },
            {
                "key": "combo_density",
                "label": "Dedicated Combo Pieces",
                "source": "heuristic",
                "type": "max",
                "max": 3,
                "description": "Lower deterministic combo concentration generally matches lower-bracket expectations.",
                "tags": ["#Combo"],
            },
            {
                "key": "boardwipe_density",
                "label": "Boardwipes",
                "source": "heuristic",
                "type": "range",
                "min": 1,
                "max": 4,
                "description": "Some reset tools improve recovery, but too many can suppress casual board play.",
                "tags": ["#Boardwipe"],
            },
        ],
    },
    "2": {
        "name": "Casual Upgraded",
        "criteria": [
            {
                "key": "game_changers",
                "label": "Game Changers",
                "source": "official",
                "type": "max",
                "max": 0,
                "description": "Official bracket cap for Game Changer cards.",
                "card_source": "game_changers",
            },
            {"key": "tutor_density", "label": "Tutors", "source": "heuristic", "type": "max", "max": 3, "description": "Moderate tutor density keeps games less scripted.", "tags": ["#Tutor"]},
            {"key": "fast_mana_density", "label": "Fast Mana", "source": "heuristic", "type": "max", "max": 3, "description": "Moderate fast mana supports tempo without cEDH pacing.", "tags": ["#FastMana"]},
            {"key": "combo_density", "label": "Dedicated Combo Pieces", "source": "heuristic", "type": "max", "max": 4, "description": "Combo plans are fine, but heavy deterministic concentration may outpace pods.", "tags": ["#Combo"]},
            {"key": "boardwipe_density", "label": "Boardwipes", "source": "heuristic", "type": "range", "min": 1, "max": 4, "description": "1-4 wipes is a typical casual control pressure range.", "tags": ["#Boardwipe"]},
        ],
    },
    "3": {
        "name": "Focused Mid-Power",
        "criteria": [
            {
                "key": "game_changers",
                "label": "Game Changers",
                "source": "official",
                "type": "max",
                "max": 2,
                "description": "Official bracket cap for Game Changer cards.",
                "card_source": "game_changers",
            },
            {"key": "tutor_density", "label": "Tutors", "source": "heuristic", "type": "max", "max": 5, "description": "Higher consistency is expected, but excessive tutors can over-script games.", "tags": ["#Tutor"]},
            {"key": "fast_mana_density", "label": "Fast Mana", "source": "heuristic", "type": "max", "max": 5, "description": "Fast starts are acceptable but still bounded for healthy pacing.", "tags": ["#FastMana"]},
            {"key": "combo_density", "label": "Dedicated Combo Pieces", "source": "heuristic", "type": "max", "max": 6, "description": "Combo is normal here; very dense combo packages trend into higher-power expectations.", "tags": ["#Combo"]},
            {"key": "boardwipe_density", "label": "Boardwipes", "source": "heuristic", "type": "range", "min": 1, "max": 5, "description": "Wide boardwipe range supports both proactive and reactive shells.", "tags": ["#Boardwipe"]},
        ],
    },
    "4": {
        "name": "High-Power Optimized",
        "criteria": [
            {
                "key": "game_changers",
                "label": "Game Changers",
                "source": "official",
                "type": "max",
                "max": 5,
                "description": "Official bracket cap for Game Changer cards.",
                "card_source": "game_changers",
            },
            {"key": "tutor_density", "label": "Tutors", "source": "heuristic", "type": "max", "max": 8, "description": "High tutor density is expected, but extreme levels reduce line diversity.", "tags": ["#Tutor"]},
            {"key": "fast_mana_density", "label": "Fast Mana", "source": "heuristic", "type": "max", "max": 8, "description": "Fast starts are expected in high-power tables.", "tags": ["#FastMana"]},
            {"key": "combo_density", "label": "Dedicated Combo Pieces", "source": "heuristic", "type": "max", "max": 9, "description": "Dense combo packages are common in this bracket.", "tags": ["#Combo"]},
            {"key": "boardwipe_density", "label": "Boardwipes", "source": "heuristic", "type": "range", "min": 0, "max": 6, "description": "Control decks may run many wipes; proactive decks can run very few.", "tags": ["#Boardwipe"]},
        ],
    },
    "5": {
        "name": "cEDH/Competitive",
        "criteria": [
            {
                "key": "game_changers",
                "label": "Game Changers",
                "source": "official",
                "type": "max",
                "max": 100,
                "description": "No practical cap at this bracket.",
                "card_source": "game_changers",
            },
            {"key": "tutor_density", "label": "Tutors", "source": "heuristic", "type": "max", "max": 100, "description": "No strict heuristic cap in fully competitive contexts.", "tags": ["#Tutor"]},
            {"key": "fast_mana_density", "label": "Fast Mana", "source": "heuristic", "type": "max", "max": 100, "description": "No strict heuristic cap in fully competitive contexts.", "tags": ["#FastMana"]},
            {"key": "combo_density", "label": "Dedicated Combo Pieces", "source": "heuristic", "type": "max", "max": 100, "description": "No strict heuristic cap in fully competitive contexts.", "tags": ["#Combo"]},
            {"key": "boardwipe_density", "label": "Boardwipes", "source": "heuristic", "type": "range", "min": 0, "max": 100, "description": "Boardwipe count is entirely strategy-driven at this bracket.", "tags": ["#Boardwipe"]},
        ],
    },
}


def _load_json(name: str, default):
    p = Path(settings.rules_cache_dir) / name
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def _singleton_exceptions(card_map: Dict[str, Dict]) -> Set[str]:
    exceptions: Set[str] = set()
    for name, card in card_map.items():
        txt = (card.get("oracle_text") or "").lower()
        if "a deck can have any number of cards named" in txt:
            exceptions.add(name)
    return exceptions


def _is_legal_commander(card: Dict) -> bool:
    type_line = (card.get("type_line") or "").lower()
    oracle_text = (card.get("oracle_text") or "").lower()
    legal = (card.get("legalities") or {}).get("commander") == "legal"
    if not legal:
        return False
    # Accept any legendary creature, including lines like "Legendary Artifact Creature".
    if "legendary" in type_line and "creature" in type_line:
        return True
    if "can be your commander" in oracle_text:
        return True
    return False


def _deck_main_entries(cards: List[CardEntry]) -> List[CardEntry]:
    return [c for c in cards if c.section in {"deck", "commander"}]


def _sum_by_names(entries: List[CardEntry], allowed_names: Set[str]) -> tuple[int, List[Dict]]:
    rows = []
    count = 0
    for c in entries:
        if c.name in allowed_names:
            count += c.qty
            rows.append({"name": c.name, "qty": c.qty})
    rows.sort(key=lambda x: (-x["qty"], x["name"]))
    return count, rows


def _sum_by_tags(entries: List[CardEntry], tags: Set[str]) -> tuple[int, List[Dict]]:
    rows = []
    count = 0
    for c in entries:
        if set(c.tags or []) & tags:
            count += c.qty
            rows.append({"name": c.name, "qty": c.qty})
    rows.sort(key=lambda x: (-x["qty"], x["name"]))
    return count, rows


def _criterion_status(criterion_type: str, current: int, min_v: int | None, max_v: int | None) -> tuple[str, str]:
    if criterion_type == "max":
        if max_v is None:
            return "pass", "No maximum configured."
        if current <= max_v:
            return "pass", f"{current} <= {max_v}"
        return "fail", f"{current} > {max_v}"
    if criterion_type == "min":
        if min_v is None:
            return "pass", "No minimum configured."
        if current >= min_v:
            return "pass", f"{current} >= {min_v}"
        return "warn", f"{current} < {min_v}"
    if criterion_type == "range":
        lo = 0 if min_v is None else min_v
        hi = 10**9 if max_v is None else max_v
        if lo <= current <= hi:
            return "pass", f"{lo} <= {current} <= {hi}"
        return "warn", f"{current} outside {lo}-{hi}"
    return "pass", "Unsupported criterion type."


def _bracket_profiles() -> Dict:
    brackets_json = _load_json("brackets.json", {})
    profiles = brackets_json.get("profiles") if isinstance(brackets_json, dict) else None
    if isinstance(profiles, dict) and profiles:
        return profiles
    return DEFAULT_BRACKET_PROFILES


def validate_deck(cards: List[CardEntry], commander: str | None, card_map: Dict[str, Dict], bracket: int) -> tuple[list[str], list[str], dict]:
    errors: List[str] = []
    warnings: List[str] = []

    main_total = sum(c.qty for c in cards if c.section in {"deck", "commander"})
    if main_total != 100:
        errors.append(f"Deck must contain exactly 100 cards including commander; found {main_total}.")

    if commander is None:
        errors.append("Commander is required.")
        return errors, warnings, {}

    commander_entries = [c for c in cards if c.section == "commander"]
    if not commander_entries:
        errors.append("Commander section is missing.")
    if len(commander_entries) > 1:
        warnings.append("Multiple commander entries detected; current validator treats the first commander as primary.")
    if any(c.qty != 1 for c in commander_entries):
        errors.append("Commander quantity must be exactly 1.")

    commander_card = card_map.get(commander)
    if not commander_card:
        errors.append(f"Commander not found on Scryfall: {commander}")
        return errors, warnings, {}
    if not _is_legal_commander(commander_card):
        errors.append(f"Commander is not legal/valid as commander: {commander}")

    ci = set(commander_card.get("color_identity") or [])
    for entry in cards:
        if entry.section not in {"deck", "commander"}:
            continue
        card = card_map.get(entry.name)
        if not card:
            warnings.append(f"No card data found for {entry.name}")
            continue
        card_ci = set(card.get("color_identity") or [])
        if not card_ci.issubset(ci):
            errors.append(f"Color identity violation: {entry.name} has {sorted(card_ci)} outside commander identity {sorted(ci)}")

    exceptions = _singleton_exceptions(card_map)
    errors.extend(singleton_violations(cards, exceptions=exceptions, basics=BASIC_LANDS))

    banned_data = _load_json("banned.json", {"banned": [], "banned_as_companion": []})
    banned = set(banned_data.get("banned", []))
    banned_comp = set(banned_data.get("banned_as_companion", []))

    for entry in cards:
        if entry.name in banned:
            errors.append(f"Banned card in commander: {entry.name}")
        if entry.section == "companion" and entry.name in banned_comp:
            errors.append(f"Banned as companion: {entry.name}")

    main_entries = _deck_main_entries(cards)
    game_changers = set(_load_json("game_changers.json", {}).get("cards", []))
    gc_count, gc_rows = _sum_by_names(main_entries, game_changers)
    bracket_limits = _load_json("brackets.json", {}).get("limits", {}) or {}
    gc_limit = int(bracket_limits.get(str(bracket), DEFAULT_BRACKET_LIMITS.get(bracket, 2)))
    profiles = _bracket_profiles()
    profile = profiles.get(str(bracket), profiles.get("3", {}))
    criteria_cfg = profile.get("criteria", [])
    criteria_rows: List[Dict] = []
    advisories: List[str] = []

    for cfg in criteria_cfg:
        ctype = cfg.get("type", "max")
        min_v = cfg.get("min")
        max_v = cfg.get("max")
        if cfg.get("key") == "game_changers":
            current = gc_count
            matched_cards = gc_rows
            max_v = gc_limit
        else:
            tags = set(cfg.get("tags", []))
            current, matched_cards = _sum_by_tags(main_entries, tags)

        status, status_detail = _criterion_status(ctype, current, min_v, max_v)
        row = {
            "key": cfg.get("key"),
            "label": cfg.get("label"),
            "source": cfg.get("source", "heuristic"),
            "type": ctype,
            "description": cfg.get("description", ""),
            "current": current,
            "target": {"min": min_v, "max": max_v},
            "status": status,
            "status_detail": status_detail,
            "cards": matched_cards,
        }
        criteria_rows.append(row)

        if status == "fail" and row["source"] == "official":
            errors.append(f"Bracket official criterion failed ({row['label']}): {status_detail}")
        if status in {"fail", "warn"} and row["source"] == "official":
            advisories.append(f"Official criterion issue: {row['label']} ({status_detail}).")
        elif status in {"fail", "warn"}:
            advisories.append(f"Heuristic mismatch: {row['label']} ({status_detail}).")

    bracket_report = {
        "bracket": bracket,
        "bracket_name": profile.get("name", f"Bracket {bracket}"),
        "game_changers_count": gc_count,
        "game_changers_limit": gc_limit,
        "violations": [],
        "advisories": advisories,
        "criteria": criteria_rows,
    }
    if gc_count > gc_limit:
        bracket_report["violations"].append(f"Game Changers over limit for bracket {bracket}: {gc_count}/{gc_limit}")

    return errors, warnings, bracket_report
