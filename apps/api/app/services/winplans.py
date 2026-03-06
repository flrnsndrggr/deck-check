from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

from app.schemas.deck import CardEntry

WINCON_ORDER = [
    "Combo",
    "Alt Win",
    "Poison",
    "Commander Damage",
    "Drain/Burn",
    "Mill",
    "Control Lock",
    "Combat",
]

_NUM_WORDS = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "twenty": 20,
}
_PUMP_RE = re.compile(r"(creatures you control|other creatures you control|attacking creatures you control) get \+(\d+)\/\+\d+", re.IGNORECASE)
_VOLTRON_PUMP_RE = re.compile(r"(equipped|enchanted) creature gets \+(\d+)\/\+\d+", re.IGNORECASE)
_TOKEN_RE = re.compile(r"create (x|a|an|\d+|one|two|three|four|five|six|seven|eight|nine|ten|twenty)? ?(?:tapped and attacking )?(?:legendary )?(\d+)\/(\d+)", re.IGNORECASE)
_TOXIC_RE = re.compile(r"toxic (\d+)", re.IGNORECASE)
_DAMAGE_RE = re.compile(r"(deals|deal) (x|\d+|one|two|three|four|five|six|seven|eight|nine|ten) damage to (each opponent|target opponent|any target|target player|each player)", re.IGNORECASE)
_LOSE_LIFE_RE = re.compile(r"(each opponent|target opponent|each player|target player) loses (x|\d+|one|two|three|four|five|six|seven|eight|nine|ten) life", re.IGNORECASE)
_MILL_RE = re.compile(r"(each opponent|target opponent|target player|each player) mills? (x|\d+|one|two|three|four|five|six|seven|eight|nine|ten)", re.IGNORECASE)


def _normalize_name(name: str | None) -> str:
    return (name or "").strip().lower()


def _text(payload: Dict[str, Any]) -> str:
    parts = [str(payload.get("type_line") or ""), str(payload.get("oracle_text") or "")]
    for face in payload.get("card_faces") or []:
        parts.append(str(face.get("type_line") or ""))
        parts.append(str(face.get("oracle_text") or ""))
    return " ".join(parts).lower()


def _keywords(payload: Dict[str, Any]) -> set[str]:
    out = {str(k).lower() for k in (payload.get("keywords") or [])}
    for face in payload.get("card_faces") or []:
        out.update(str(k).lower() for k in (face.get("keywords") or []))
    return out


def _float_or_zero(value: Any) -> float:
    try:
        text = str(value).strip()
        if not text or text in {"*", "*+1", "1+*", "X"}:
            return 0.0
        return float(text)
    except Exception:
        return 0.0


def _base_power(payload: Dict[str, Any]) -> float:
    power = _float_or_zero(payload.get("power"))
    if power:
        return power
    for face in payload.get("card_faces") or []:
        power = _float_or_zero(face.get("power"))
        if power:
            return power
    return 0.0


def _to_number(token: str | None) -> float:
    if token is None:
        return 0.0
    t = str(token).strip().lower()
    if not t:
        return 0.0
    if t == "x":
        return 4.0
    if t.isdigit():
        return float(int(t))
    return float(_NUM_WORDS.get(t, 0))


def _evasion_score(text: str, keywords: set[str]) -> float:
    if any(k in keywords for k in {"unblockable"}):
        return 1.0
    if "can't be blocked" in text or "unblockable" in text or "horsemanship" in text:
        return 1.0
    score = 0.0
    if any(k in keywords for k in {"flying", "fear", "intimidate", "menace", "shadow"}):
        score = max(score, 0.55)
    if any(k in text for k in ["flying", "fear", "intimidate", "menace", "shadow", "skulk"]):
        score = max(score, 0.55)
    if "trample" in keywords or "trample" in text:
        score = max(score, 0.3)
    if any(k in text for k in ["islandwalk", "swampwalk", "forestwalk", "mountainwalk", "plainswalk"]):
        score = max(score, 0.65)
    return score


def _is_repeatable(text: str) -> bool:
    return any(k in text for k in ["whenever", "at the beginning of", "for each", "whenever one or more"])


def _token_stats(text: str) -> tuple[float, float]:
    total_power = 0.0
    total_bodies = 0.0
    for qty_raw, p_raw, _ in _TOKEN_RE.findall(text):
        qty = max(1.0, _to_number(qty_raw))
        power = max(0.0, _to_number(p_raw))
        total_power += qty * max(1.0, power)
        total_bodies += qty
    return total_power, total_bodies


def _damage_stats(text: str) -> tuple[float, float]:
    immediate = 0.0
    repeatable = 0.0
    for _, amount_raw, _ in _DAMAGE_RE.findall(text):
        amount = _to_number(amount_raw)
        if _is_repeatable(text):
            repeatable = max(repeatable, amount)
        else:
            immediate += amount
    for _, amount_raw in _LOSE_LIFE_RE.findall(text):
        amount = _to_number(amount_raw)
        if _is_repeatable(text):
            repeatable = max(repeatable, amount)
        else:
            immediate += amount
    return immediate, repeatable


def _mill_stats(text: str) -> tuple[float, float]:
    immediate = 0.0
    repeatable = 0.0
    for _, amount_raw in _MILL_RE.findall(text):
        amount = _to_number(amount_raw)
        if _is_repeatable(text):
            repeatable = max(repeatable, amount)
        else:
            immediate += amount
    return immediate, repeatable


def _alt_win_kind(text: str) -> str | None:
    if "you win the game" not in text and "loses the game" not in text:
        return None
    if "40 or more life" in text:
        return "life40"
    if "twenty or more artifacts" in text:
        return "artifacts20"
    if "twenty or more creatures" in text:
        return "creatures20"
    if "twenty or more cards in your graveyard" in text:
        return "graveyard20"
    if "two or fewer cards in your library" in text:
        return "library2"
    if "no cards in your library" in text:
        return "library0"
    if "no cards in hand" in text:
        return "hand0"
    if "exactly 1 life" in text:
        return "life1"
    return "generic"


def enrich_sim_cards(cards: Iterable[CardEntry], card_map: Dict[str, Dict[str, Any]], commander: str | None) -> List[Dict[str, Any]]:
    commander_key = _normalize_name(commander)
    out: List[Dict[str, Any]] = []
    for entry in cards:
        payload = card_map.get(entry.name, {}) or {}
        text = _text(payload)
        type_line = str(payload.get("type_line") or "").lower()
        keywords = _keywords(payload)
        token_power, token_bodies = _token_stats(text)
        burn_value, repeatable_burn = _damage_stats(text)
        mill_value, repeatable_mill = _mill_stats(text)
        toxic_match = _TOXIC_RE.search(text)
        toxic = float(toxic_match.group(1)) if toxic_match else 0.0
        combat_buff = sum(float(m.group(2)) for m in _PUMP_RE.finditer(text))
        commander_buff = sum(float(m.group(2)) for m in _VOLTRON_PUMP_RE.finditer(text))
        power = _base_power(payload)
        alt_kind = _alt_win_kind(text)
        is_creature = "creature" in type_line
        is_permanent = any(t in type_line for t in ("artifact", "creature", "enchantment", "planeswalker", "battle", "land"))
        is_commander = commander_key and _normalize_name(entry.name) == commander_key

        hints = set()
        if is_creature or "#Tokens" in entry.tags:
            hints.add("Combat")
        if is_commander and (power >= 3 or "#Voltron" in entry.tags):
            hints.add("Commander Damage")
        if "#Voltron" in entry.tags or commander_buff > 0:
            hints.add("Commander Damage")
        if any(k in keywords for k in {"infect"}) or "infect" in text or toxic > 0 or "poison counter" in text:
            hints.add("Poison")
        if burn_value > 0 or repeatable_burn > 0 or "#Aristocrats" in entry.tags:
            hints.add("Drain/Burn")
        if mill_value > 0 or repeatable_mill > 0 or "mill" in text:
            hints.add("Mill")
        if alt_kind:
            hints.add("Alt Win")
        if "#Stax" in entry.tags or "#Counter" in entry.tags or "#Control" in entry.tags:
            hints.add("Control Lock")
        if "#Combo" in entry.tags:
            hints.add("Combo")

        out.append(
            {
                **entry.model_dump(),
                "type_line": payload.get("type_line"),
                "oracle_text": payload.get("oracle_text"),
                "keywords": sorted(keywords),
                "power": power,
                "toughness": _float_or_zero(payload.get("toughness")),
                "is_creature": is_creature,
                "is_permanent": is_permanent,
                "has_haste": ("haste" in keywords) or ("haste" in text),
                "is_commander": bool(is_commander),
                "evasion_score": _evasion_score(text, keywords),
                "combat_buff": combat_buff,
                "commander_buff": commander_buff,
                "token_attack_power": token_power,
                "token_bodies": token_bodies,
                "extra_combat_factor": 2.0 if "additional combat phase" in text or "extra combat phase" in text else 1.0,
                "infect": ("infect" in keywords) or ("infect" in text),
                "toxic": toxic,
                "proliferate": "proliferate" in text,
                "burn_value": burn_value,
                "repeatable_burn": repeatable_burn,
                "mill_value": mill_value,
                "repeatable_mill": repeatable_mill,
                "alt_win_kind": alt_kind,
                "win_vector_hints": sorted(hints),
            }
        )
    return out


def infer_supported_wincons(cards: List[Dict[str, Any]], commander: str | None, combo_intel: Dict[str, Any] | None = None) -> List[str]:
    combo_intel = combo_intel or {}
    counts = {name: 0.0 for name in WINCON_ORDER}
    creature_power = 0.0
    commander_power = 0.0
    commander_support = 0.0
    protection = 0.0
    tutors = 0.0

    for card in cards:
        qty = float(card.get("qty", 1) or 1)
        hints = set(card.get("win_vector_hints") or [])
        creature_power += float(card.get("power", 0.0) or 0.0) * qty if card.get("is_creature") else 0.0
        if card.get("is_commander"):
            commander_power = float(card.get("power", 0.0) or 0.0)
        commander_support += float(card.get("commander_buff", 0.0) or 0.0) * qty
        commander_support += float(card.get("evasion_score", 0.0) or 0.0) * qty if "#Voltron" in (card.get("tags") or []) else 0.0
        protection += qty if "#Protection" in (card.get("tags") or []) else 0.0
        tutors += qty if "#Tutor" in (card.get("tags") or []) else 0.0
        for hint in hints:
            counts[hint] = counts.get(hint, 0.0) + qty
        if card.get("token_attack_power"):
            counts["Combat"] += 0.75 * qty
        if card.get("combat_buff"):
            counts["Combat"] += 0.5 * qty
        if card.get("extra_combat_factor", 1.0) > 1.0:
            counts["Combat"] += 1.5 * qty
        if card.get("proliferate") and counts.get("Poison", 0.0) > 0:
            counts["Poison"] += 0.5 * qty

    if combo_intel.get("matched_variants"):
        counts["Combo"] += 4.0 + min(3.0, len(combo_intel.get("matched_variants", [])))
    elif counts.get("Combo", 0.0) >= 2 and tutors >= 1:
        counts["Combo"] += 1.5

    if commander and (commander_power >= 4 or commander_support >= 3 or protection >= 2):
        counts["Commander Damage"] += 2.0
    if creature_power >= 18:
        counts["Combat"] += 2.0
    if counts.get("Control Lock", 0.0) >= 5 and counts.get("Combat", 0.0) >= 2:
        counts["Control Lock"] += 1.0

    chosen = []
    for name in WINCON_ORDER:
        threshold = {
            "Combo": 3.0,
            "Alt Win": 1.0,
            "Poison": 1.5,
            "Commander Damage": 2.5,
            "Drain/Burn": 2.5,
            "Mill": 2.0,
            "Control Lock": 4.0,
            "Combat": 4.0,
        }.get(name, 999.0)
        if counts.get(name, 0.0) >= threshold:
            chosen.append(name)

    if not chosen:
        chosen = ["Combat"]
    return chosen
