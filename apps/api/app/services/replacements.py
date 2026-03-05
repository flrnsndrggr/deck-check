from __future__ import annotations

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


def _candidate_roles(card: Dict) -> Set[str]:
    txt = f"{card.get('type_line', '')} {card.get('oracle_text', '')}".lower()
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
    selected_cmc = selected_data.get("cmc")
    selected_rank = selected_data.get("edhrec_rank")
    selected_roles = set(selected_entry.tags) & FUNCTIONAL_ROLES
    if not selected_roles:
        selected_roles = _candidate_roles(selected_data)
    if not selected_roles:
        selected_roles = {"#Utility"}

    commander_ci = "".join(card_map.get(commander or "", {}).get("color_identity") or [])

    # Query candidates from all relevant roles.
    role_queries = [ROLE_QUERIES.get(r) for r in selected_roles if ROLE_QUERIES.get(r)]
    if not role_queries:
        role_queries = ["mv<=5"]

    options: List[Dict] = []
    seen_names = set()
    for q in role_queries[:3]:
        candidates = svc.search_candidates(q, commander_ci, limit=16)
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

            cand_roles = _candidate_roles(cand)
            role_overlap = sorted(selected_roles & cand_roles)
            if not role_overlap and "#Utility" not in selected_roles:
                continue

            cand_cmc = cand.get("cmc")
            cand_rank = cand.get("edhrec_rank")
            better_mana = False
            if isinstance(selected_cmc, (int, float)) and isinstance(cand_cmc, (int, float)):
                better_mana = cand_cmc < selected_cmc
                if cand_cmc > selected_cmc:
                    continue
            better_rank = False
            if isinstance(selected_rank, int) and isinstance(cand_rank, int):
                better_rank = cand_rank < selected_rank

            if not (better_mana or better_rank):
                continue

            reasons = []
            if better_mana:
                reasons.append(f"Lower mana value ({cand_cmc} vs {selected_cmc}).")
            if better_rank:
                reasons.append(f"Better EDHREC rank ({cand_rank} vs {selected_rank}).")
            if role_overlap:
                reasons.append(f"Matches role(s): {', '.join(role_overlap)}.")

            display = svc.card_display(cand)
            options.append(
                {
                    "card": name,
                    "reasons": reasons,
                    "price_usd": price,
                    "role_overlap": role_overlap,
                    "mana_value": cand_cmc,
                    "selected_mana_value": selected_cmc,
                    "scryfall_uri": cand.get("scryfall_uri") or display.get("scryfall_uri"),
                    "cardmarket_url": display.get("cardmarket_url"),
                }
            )
            seen_names.add(name)

    options.sort(
        key=lambda x: (
            x["price_usd"] is None,
            x["price_usd"] if x["price_usd"] is not None else 10**9,
            len(x.get("role_overlap") or []),
        ),
        reverse=False,
    )
    return {"selected_card": selected_card, "options": options[:limit]}
