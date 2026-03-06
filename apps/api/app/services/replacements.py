from __future__ import annotations

import re
from typing import Dict, List, Optional, Set

from app.schemas.deck import CardEntry
from app.services.scryfall import CardDataService

FUNCTIONAL_ROLES = {
    "#Ramp",
    "#Fixing",
    "#Draw",
    "#Tutor",
    "#Removal",
    "#Counter",
    "#Boardwipe",
    "#Protection",
    "#Recursion",
    "#GraveyardHate",
    "#Stax",
    "#Wincon",
    "#Combo",
    "#Payoff",
    "#Engine",
    "#Setup",
    "#Utility",
    "#SpotRemoval",
    "#MassRemoval",
    "#StackInteraction",
    "#Tax",
}

ROLE_QUERIES = {
    "#Ramp": "o:'add {' mv<=3",
    "#Fixing": "o:'add {' o:'any color' mv<=3",
    "#Draw": "o:'draw' mv<=4",
    "#Tutor": "o:'search your library' mv<=4",
    "#Removal": "(o:'destroy target' or o:'exile target') mv<=4",
    "#SpotRemoval": "(o:'destroy target' or o:'exile target') mv<=4",
    "#Counter": "o:'counter target' mv<=4",
    "#StackInteraction": "o:'counter target' mv<=4",
    "#Boardwipe": "(o:'destroy all' or o:'exile all') mv<=6",
    "#MassRemoval": "(o:'destroy all' or o:'exile all') mv<=6",
    "#Protection": "o:(hexproof or indestructible or \"phase out\") mv<=4",
    "#Recursion": "o:'return target' o:'graveyard' mv<=5",
    "#Engine": "(o:'whenever' or o:'at the beginning') mv<=5",
    "#Setup": "(o:'scry' or o:'draw' or o:'search your library') mv<=3",
    "#Wincon": "(o:'you win the game' or o:'each opponent loses') mv<=8",
    "#Payoff": "mv<=6",
    "#Combo": "(o:'untap' or o:'copy target spell' or o:'you win the game') mv<=6",
}


def _to_float(v: Optional[str]) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _card_text(card: Dict) -> str:
    return f"{card.get('type_line', '')} {card.get('oracle_text', '')}".lower()


def _main_types(card: Dict) -> Set[str]:
    type_line = str(card.get("type_line", "")).lower()
    return {t for t in ("artifact", "creature", "land", "instant", "sorcery", "enchantment", "planeswalker") if t in type_line}


def _mana_output_score(card: Dict) -> float:
    text = _card_text(card)
    symbol_matches = re.findall(r"add\s+((?:\{[^}]+\})+)", text)
    if symbol_matches:
        return float(max(len(re.findall(r"\{[^}]+\}", match)) for match in symbol_matches))
    if "add three mana" in text:
        return 3.0
    if "add two mana" in text:
        return 2.0
    if "add one mana" in text or "add one mana of" in text:
        return 1.0
    return 0.0


def _colored_source_score(card: Dict, commander_ci: Set[str]) -> int:
    text = _card_text(card)
    produced = {str(x).upper() for x in (card.get("produced_mana") or []) if isinstance(x, str)}
    produced_colors = produced & {"W", "U", "B", "R", "G"}
    if not commander_ci:
        return 1 if ("{c}" in text or "add {c}" in text or "colorless" in text or "C" in produced) else 0
    if "any color" in text:
        return 3
    if "chosen color" in text:
        return 2 if len(commander_ci) <= 1 else 3
    if produced_colors & commander_ci:
        return 2
    return 0


def _functional_family(card: Dict, roles: Set[str]) -> str:
    text = _card_text(card)
    main_types = _main_types(card)
    has_tap_mana = "{t}" in text and (
        "add {" in text
        or "add one mana" in text
        or "add two mana" in text
        or "add three mana" in text
        or "add one mana of" in text
    )
    if "land" in main_types and ("add {" in text or "add one mana" in text or "add two mana" in text):
        return "mana-land"
    if "artifact" in main_types and has_tap_mana:
        return "mana-rock"
    if "creature" in main_types and has_tap_mana:
        return "mana-dork"
    if ("instant" in main_types or "sorcery" in main_types) and "add {" in text:
        return "ritual"
    if "#Boardwipe" in roles or "#MassRemoval" in roles or "destroy all" in text or "exile all" in text:
        return "boardwipe"
    if "#Counter" in roles or "#StackInteraction" in roles or "counter target" in text:
        return "counterspell"
    if "#Removal" in roles or "#SpotRemoval" in roles or "destroy target" in text or "exile target" in text:
        return "spot-removal"
    if "#Tutor" in roles or "search your library" in text:
        return "tutor"
    if "#Draw" in roles or "draw" in text:
        return "draw"
    if "#Recursion" in roles or ("graveyard" in text and "return" in text):
        return "recursion"
    if "#Protection" in roles:
        return "protection"
    if "#Engine" in roles:
        return "engine"
    if main_types:
        return "+".join(sorted(main_types))
    return "utility"


def _candidate_roles(card: Dict) -> Set[str]:
    txt = _card_text(card)
    roles: Set[str] = set()
    if "add {" in txt:
        roles.add("#Ramp")
    if "draw" in txt:
        roles.add("#Draw")
    if "search your library" in txt:
        roles.add("#Tutor")
    if "destroy target" in txt or "exile target" in txt:
        roles.add("#Removal")
    if "counter target" in txt:
        roles.add("#Counter")
    if "destroy all" in txt or "exile all" in txt:
        roles.add("#Boardwipe")
    if "return target" in txt and "graveyard" in txt:
        roles.add("#Recursion")
    if "whenever" in txt or "at the beginning of" in txt:
        roles.add("#Engine")
    if "you win the game" in txt or "each opponent loses" in txt:
        roles.add("#Wincon")
    return roles


def _is_strict_upgrade(
    selected_data: Dict,
    candidate: Dict,
    selected_roles: Set[str],
    commander_ci_set: Set[str],
) -> tuple[bool, List[str], float]:
    selected_cmc = selected_data.get("cmc")
    cand_cmc = candidate.get("cmc")
    selected_family = _functional_family(selected_data, selected_roles)
    cand_roles = _candidate_roles(candidate)
    cand_family = _functional_family(candidate, cand_roles)
    reasons: List[str] = []

    if cand_family != selected_family:
        return False, [], 0.0

    selected_overlap_roles = {r for r in selected_roles if r != "#Utility"}
    role_overlap = sorted(selected_overlap_roles & cand_roles)
    if selected_overlap_roles and not role_overlap:
        return False, [], 0.0

    if not isinstance(selected_cmc, (int, float)) or not isinstance(cand_cmc, (int, float)):
        return False, [], 0.0

    if cand_cmc > selected_cmc:
        return False, [], 0.0

    strict_score = 0.0
    if selected_family in {"mana-rock", "mana-land", "mana-dork", "ritual"}:
        selected_output = _mana_output_score(selected_data)
        cand_output = _mana_output_score(candidate)
        selected_color = _colored_source_score(selected_data, commander_ci_set)
        cand_color = _colored_source_score(candidate, commander_ci_set)
        if cand_output < selected_output:
            return False, [], 0.0
        if cand_color < selected_color:
            return False, [], 0.0
        if cand_output == selected_output and cand_cmc == selected_cmc and cand_color == selected_color:
            return False, [], 0.0

        if cand_output > selected_output:
            reasons.append(f"Produces more mana per activation ({cand_output:.0f} vs {selected_output:.0f}).")
            strict_score += (cand_output - selected_output) * 5
        if cand_cmc < selected_cmc:
            reasons.append(f"Comes down earlier ({cand_cmc:.0f} vs {selected_cmc:.0f} mana value).")
            strict_score += (selected_cmc - cand_cmc) * 3
        if cand_color > selected_color:
            reasons.append("Improves colored mana coverage for this deck.")
            strict_score += 2
        if role_overlap:
            reasons.append(f"Matches role(s): {', '.join(role_overlap)}.")
            strict_score += len(role_overlap)
    else:
        if cand_cmc >= selected_cmc:
            return False, [], 0.0
        reasons.append(f"Does the same primary job earlier ({cand_cmc:.0f} vs {selected_cmc:.0f} mana value).")
        strict_score += (selected_cmc - cand_cmc) * 3
        if role_overlap:
            reasons.append(f"Matches role(s): {', '.join(role_overlap)}.")
            strict_score += len(role_overlap)

    return True, reasons, strict_score


def strictly_better_replacements(
    cards: List[CardEntry],
    selected_card: str,
    commander: str | None = None,
    budget_max_usd: float | None = None,
    limit: int = 6,
) -> Dict:
    svc = CardDataService()
    deck_cards = [c for c in cards if c.section in {"deck", "commander"}]
    deck_names = {c.name for c in deck_cards}
    selected_entry = next((c for c in deck_cards if c.name == selected_card), None)
    if selected_entry is None:
        return {"selected_card": selected_card, "options": []}

    card_map = svc.get_cards_by_name([selected_card] + ([commander] if commander else []))
    selected_data = card_map.get(selected_card, {})
    selected_roles = set(selected_entry.tags) & FUNCTIONAL_ROLES
    if not selected_roles:
        selected_roles = _candidate_roles(selected_data)
    if not selected_roles:
        selected_roles = {"#Utility"}

    commander_ci = "".join(card_map.get(commander or "", {}).get("color_identity") or [])
    commander_ci_set = set(commander_ci)
    selected_family = _functional_family(selected_data, selected_roles)

    # Keep "strictly better" conservative by searching the same functional family first.
    selected_cmc = selected_data.get("cmc")
    mana_limit = int(selected_cmc) if isinstance(selected_cmc, (int, float)) else 5
    if selected_family == "mana-rock":
        role_queries = [f"t:artifact o:'{{T}}: add' mv<={max(0, mana_limit)}"]
    elif selected_family == "mana-land":
        role_queries = ["t:land o:'add {'"]
    elif selected_family == "mana-dork":
        role_queries = [f"t:creature o:'{{T}}: add' mv<={max(0, mana_limit)}"]
    elif selected_family == "ritual":
        role_queries = [f"(t:instant or t:sorcery) o:'add {{' mv<={max(0, mana_limit)}"]
    else:
        role_queries = [ROLE_QUERIES.get(r) for r in selected_roles if ROLE_QUERIES.get(r)]
        if not role_queries:
            role_queries = [f"mv<={max(0, mana_limit)}"]

    options: List[Dict] = []
    seen_names = set()
    for q in role_queries[:3]:
        candidates = svc.search_candidates(q, commander_ci, limit=24)
        for cand in candidates:
            name = cand.get("name")
            if not name or name == selected_card:
                continue
            if name in deck_names or name in seen_names:
                continue

            price = _to_float((cand.get("prices") or {}).get("usd"))
            if budget_max_usd is not None:
                if price is None or price > budget_max_usd:
                    continue

            qualifies, reasons, strict_score = _is_strict_upgrade(
                selected_data=selected_data,
                candidate=cand,
                selected_roles=selected_roles,
                commander_ci_set=commander_ci_set,
            )
            if not qualifies:
                continue

            display = svc.card_display(cand)
            options.append(
                {
                    "card": name,
                    "reasons": reasons,
                    "price_usd": price,
                    "role_overlap": sorted(selected_roles & _candidate_roles(cand)),
                    "mana_value": cand.get("cmc"),
                    "selected_mana_value": selected_cmc,
                    "strict_score": round(strict_score, 3),
                    "scryfall_uri": cand.get("scryfall_uri") or display.get("scryfall_uri"),
                    "cardmarket_url": display.get("cardmarket_url"),
                }
            )
            seen_names.add(name)

    options.sort(
        key=lambda x: (
            -(x.get("strict_score") or 0.0),
            -(len(x.get("role_overlap") or [])),
            x["price_usd"] is None,
            x["price_usd"] if x["price_usd"] is not None else 10**9,
        ),
    )
    return {"selected_card": selected_card, "options": options[:limit]}
