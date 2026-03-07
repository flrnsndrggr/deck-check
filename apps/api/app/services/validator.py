from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Set

from app.core.config import settings
from app.schemas.deck import CardEntry
from app.services.commander_utils import combined_color_identity, commander_names_from_cards, legal_commander_pairing
from app.services.parser import singleton_violations
from app.services.tagger import tag_cards

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


def _speed_bracket_hint(sim_summary: Dict | None) -> int | None:
    if not sim_summary:
        return None
    win_metrics = sim_summary.get("win_metrics", {}) or {}
    median_win_turn = win_metrics.get("median_win_turn")
    if isinstance(median_win_turn, (int, float)):
        if median_win_turn <= 5:
            return 5
        if median_win_turn <= 6:
            return 4
        if median_win_turn <= 8:
            return 3
        if median_win_turn <= 10:
            return 2
        return 1
    return None


def infer_bracket(
    cards: List[CardEntry],
    commander: str | None,
    card_map: Dict[str, Dict],
    sim_summary: Dict | None = None,
    tagged_cards: List[CardEntry] | None = None,
) -> Dict:
    commander_names = commander_names_from_cards(cards, fallback_commander=commander)
    working_cards = tagged_cards or [c.model_copy(deep=True) for c in cards]
    if tagged_cards is None:
        working_cards, _, _ = tag_cards(working_cards, card_map, commander_names, use_global_prefix=False)

    main_entries = _deck_main_entries(working_cards)
    game_changers = set(_load_json("game_changers.json", {}).get("cards", []))
    gc_count, gc_rows = _sum_by_names(main_entries, game_changers)
    bracket_limits = _load_json("brackets.json", {}).get("limits", {}) or {}
    profiles = _bracket_profiles()
    signal_rows = {
        "tutor_density": _sum_by_tags(main_entries, {"#Tutor"}),
        "fast_mana_density": _sum_by_tags(main_entries, {"#FastMana"}),
        "combo_density": _sum_by_tags(main_entries, {"#Combo"}),
        "boardwipe_density": _sum_by_tags(main_entries, {"#Boardwipe"}),
    }
    signal_counts = {
        "game_changers": gc_count,
        "tutor_density": signal_rows["tutor_density"][0],
        "fast_mana_density": signal_rows["fast_mana_density"][0],
        "combo_density": signal_rows["combo_density"][0],
        "boardwipe_density": signal_rows["boardwipe_density"][0],
    }
    speed_hint = _speed_bracket_hint(sim_summary)
    power_intensity = (
        signal_counts["game_changers"] * 3.0
        + signal_counts["fast_mana_density"] * 1.6
        + signal_counts["tutor_density"] * 1.3
        + signal_counts["combo_density"] * 1.4
        + ({None: 0.0, 1: 0.0, 2: 1.0, 3: 2.25, 4: 4.0, 5: 6.0}.get(speed_hint, 0.0))
    )
    intensity_floor = {1: 0.0, 2: 1.5, 3: 4.5, 4: 9.0, 5: 14.0}
    intensity_ceiling = {1: 4.0, 2: 8.0, 3: 14.0, 4: 22.0, 5: 999.0}
    score_rows: List[Dict] = []

    for bracket_value in range(1, 6):
        profile = profiles.get(str(bracket_value), profiles.get("3", {}))
        score = 0.0
        deltas: List[str] = []
        for cfg in profile.get("criteria", []):
            key = cfg.get("key")
            criterion_type = cfg.get("type", "max")
            weight = 4.0 if cfg.get("source") == "official" else 1.5
            if key == "game_changers":
                current = gc_count
                min_v = cfg.get("min")
                max_v = int(bracket_limits.get(str(bracket_value), DEFAULT_BRACKET_LIMITS.get(bracket_value, 2)))
            else:
                current = signal_counts.get(str(key), 0)
                min_v = cfg.get("min")
                max_v = cfg.get("max")

            if criterion_type == "max" and max_v is not None:
                delta = max(0, current - max_v)
            elif criterion_type == "min" and min_v is not None:
                delta = max(0, min_v - current)
            elif criterion_type == "range":
                lo = 0 if min_v is None else min_v
                hi = 10**9 if max_v is None else max_v
                delta = max(0, lo - current, current - hi)
            else:
                delta = 0
            if delta:
                score += weight * float(delta)
                deltas.append(f"{cfg.get('label', key)} {current}")

        if speed_hint is not None:
            score += abs(bracket_value - speed_hint) * 1.25
        if power_intensity < intensity_floor[bracket_value]:
            score += (intensity_floor[bracket_value] - power_intensity) * 1.15
        if power_intensity > intensity_ceiling[bracket_value]:
            score += (power_intensity - intensity_ceiling[bracket_value]) * 0.65
        score_rows.append(
            {
                "bracket": bracket_value,
                "score": round(score, 3),
                "name": profile.get("name", f"Bracket {bracket_value}"),
                "deltas": deltas[:4],
            }
        )

    score_rows.sort(key=lambda row: (row["score"], -row["bracket"]))
    best = score_rows[0]
    second_score = score_rows[1]["score"] if len(score_rows) > 1 else best["score"]
    confidence_gap = max(0.0, second_score - best["score"])
    reasons: List[str] = []
    if signal_counts["game_changers"]:
        reasons.append(f"{signal_counts['game_changers']} Game Changer card(s) push the deck upward.")
    if signal_counts["fast_mana_density"]:
        reasons.append(f"{signal_counts['fast_mana_density']} fast mana piece(s) suggest a faster table band.")
    if signal_counts["tutor_density"]:
        reasons.append(f"{signal_counts['tutor_density']} tutor-tagged card(s) increase consistency.")
    if signal_counts["combo_density"]:
        reasons.append(f"{signal_counts['combo_density']} combo-tagged card(s) raise deterministic finish density.")
    if speed_hint is not None:
        reasons.append(f"Simulated speed points toward bracket {speed_hint}.")
    if not reasons:
        reasons.append("Low density of fast mana, tutors, and combo pieces keeps this closer to lower-power brackets.")

    return {
        "bracket": best["bracket"],
        "bracket_name": best["name"],
        "source": "inferred",
        "confidence": round(min(1.0, 0.3 + confidence_gap / 4.0), 3),
        "signals": {
            **signal_counts,
            "game_changer_cards": gc_rows,
            "speed_hint": speed_hint,
            "power_intensity": round(power_intensity, 3),
        },
        "reasoning": reasons[:4],
        "score_table": score_rows,
    }


def validate_deck(
    cards: List[CardEntry],
    commander: str | None,
    card_map: Dict[str, Dict],
    bracket: int | None,
    sim_summary: Dict | None = None,
    tagged_cards: List[CardEntry] | None = None,
) -> tuple[list[str], list[str], dict]:
    errors: List[str] = []
    warnings: List[str] = []

    main_total = sum(c.qty for c in cards if c.section in {"deck", "commander"})
    if main_total != 100:
        errors.append(f"Deck must contain exactly 100 cards including commander; found {main_total}.")

    commander_names = commander_names_from_cards(cards, fallback_commander=commander)
    if not commander_names:
        errors.append("Commander is required.")
        return errors, warnings, {}

    commander_entries = [c for c in cards if c.section == "commander"]
    if not commander_entries:
        errors.append("Commander section is missing.")
    if len(commander_names) > 2:
        errors.append("Commander section can include at most two commanders.")
    if any(c.qty != 1 for c in commander_entries):
        errors.append("Commander quantity must be exactly 1.")
    if len(commander_names) == 0:
        errors.append("Commander is required.")
        return errors, warnings, {}

    commander_cards = {name: card_map.get(name) for name in commander_names}
    missing = [name for name, payload in commander_cards.items() if not payload]
    if missing:
        errors.extend([f"Commander not found on Scryfall: {name}" for name in missing])
        return errors, warnings, {}

    if len(commander_names) == 1:
        commander_card = commander_cards[commander_names[0]]
        if not _is_legal_commander(commander_card):
            errors.append(f"Commander is not legal/valid as commander: {commander_names[0]}")
    elif len(commander_names) == 2:
        legal_pair, reason = legal_commander_pairing(commander_cards, commander_names, _is_legal_commander)
        if not legal_pair and reason:
            errors.append(reason)

    ci = set(combined_color_identity(card_map, commander_names))
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

    inferred = None
    if bracket is None:
        inferred = infer_bracket(cards, commander, card_map, sim_summary=sim_summary, tagged_cards=tagged_cards)
        bracket = int(inferred.get("bracket", 3) or 3)

    main_entries = _deck_main_entries(tagged_cards or cards)
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
        "source": "inferred" if inferred else "provided",
        "inference": inferred or {},
        "game_changers_count": gc_count,
        "game_changers_limit": gc_limit,
        "violations": [],
        "advisories": advisories,
        "criteria": criteria_rows,
    }
    if gc_count > gc_limit:
        bracket_report["violations"].append(f"Game Changers over limit for bracket {bracket}: {gc_count}/{gc_limit}")

    return errors, warnings, bracket_report
