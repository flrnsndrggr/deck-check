from __future__ import annotations

import re
from typing import Dict, Iterable, List, Sequence

from app.schemas.deck import CardEntry

WUBRG_ORDER = ["W", "U", "B", "R", "G"]
_PARTNER_WITH_RE = re.compile(r"partner with ([^.]+)", re.IGNORECASE)
_PARTNER_VARIANT_RE = re.compile(r"partner\s*[—-]\s*(.+)", re.IGNORECASE)


def normalize_name(name: str | None) -> str:
    return re.sub(r"\s+", " ", str(name or "").replace("’", "'")).strip().lower()


def commander_names_from_cards(cards: Sequence[CardEntry], fallback_commander: str | None = None) -> List[str]:
    names: List[str] = []
    seen = set()
    for card in cards:
        if card.section != "commander":
            continue
        name = str(card.name or "").strip()
        key = normalize_name(name)
        if not key or key in seen:
            continue
        seen.add(key)
        names.append(name)
    if names:
        return names
    if fallback_commander and fallback_commander.strip():
        return [fallback_commander.strip()]
    return []


def commander_display_name(names: Sequence[str]) -> str | None:
    cleaned = [str(name).strip() for name in names if str(name or "").strip()]
    if not cleaned:
        return None
    return " + ".join(cleaned)


def primary_commander_name(names: Sequence[str]) -> str | None:
    return next((str(name).strip() for name in names if str(name or "").strip()), None)


def combined_color_identity(card_map: Dict[str, Dict], commander_names: Sequence[str]) -> List[str]:
    ci = set()
    for name in commander_names:
        ci.update(card_map.get(name, {}).get("color_identity") or [])
    return [color for color in WUBRG_ORDER if color in ci]


def commander_lookup_names(cards: Sequence[CardEntry], fallback_commander: str | None = None) -> List[str]:
    return commander_names_from_cards(cards, fallback_commander=fallback_commander)


def _oracle_lines(card: Dict) -> List[str]:
    oracle = str(card.get("oracle_text") or "").replace("’", "'")
    return [line.strip().lower() for line in oracle.splitlines() if line.strip()]


def has_choose_a_background(card: Dict) -> bool:
    return any(line == "choose a background" for line in _oracle_lines(card))


def has_doctors_companion(card: Dict) -> bool:
    return any("doctor's companion" == line or "doctor’s companion" == line for line in _oracle_lines(card))


def is_background_card(card: Dict) -> bool:
    type_line = str(card.get("type_line") or "").lower()
    return "legendary enchantment" in type_line and "background" in type_line


def is_doctor_card(card: Dict) -> bool:
    type_line = str(card.get("type_line") or "").lower()
    return "legendary creature" in type_line and "time lord doctor" in type_line


def partner_mode(card: Dict) -> tuple[str | None, str | None]:
    for line in _oracle_lines(card):
        if line == "partner":
            return "partner", None
        match = _PARTNER_WITH_RE.fullmatch(line)
        if match:
            return "partner_with", normalize_name(match.group(1))
        match = _PARTNER_VARIANT_RE.fullmatch(line)
        if match:
            return "partner_variant", normalize_name(match.group(1))
        if line == "friends forever":
            return "partner_variant", "friends forever"
    return None, None


def legal_commander_pairing(cards_by_name: Dict[str, Dict], commander_names: Sequence[str], legal_commander_fn) -> tuple[bool, str | None]:
    names = [name for name in commander_names if name]
    if len(names) != 2:
        return False, "Commander pairings require exactly two commanders."

    first = cards_by_name.get(names[0]) or {}
    second = cards_by_name.get(names[1]) or {}
    if not first or not second:
        missing = names[0] if not first else names[1]
        return False, f"Commander not found on Scryfall: {missing}"

    if has_choose_a_background(first) and is_background_card(second):
        return True, None
    if has_choose_a_background(second) and is_background_card(first):
        return True, None

    if has_doctors_companion(first) and is_doctor_card(second) and legal_commander_fn(first) and legal_commander_fn(second):
        return True, None
    if has_doctors_companion(second) and is_doctor_card(first) and legal_commander_fn(first) and legal_commander_fn(second):
        return True, None

    if not legal_commander_fn(first) or not legal_commander_fn(second):
        return False, f"Commander pair is not legal/valid: {names[0]} + {names[1]}"

    first_mode, first_value = partner_mode(first)
    second_mode, second_value = partner_mode(second)

    if first_mode == "partner" and second_mode == "partner":
        return True, None
    if first_mode == "partner_with" and second_mode == "partner_with":
        if first_value == normalize_name(names[1]) and second_value == normalize_name(names[0]):
            return True, None
    if first_mode == "partner_variant" and second_mode == "partner_variant" and first_value and first_value == second_value:
        return True, None

    return False, f"Commander pair is not a legal pairing: {names[0]} + {names[1]}"

