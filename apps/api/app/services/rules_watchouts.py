from __future__ import annotations

from typing import Dict, List

from app.schemas.deck import CardEntry
from app.services.scryfall import CardDataService


def _complexity_flags(oracle_text: str) -> List[str]:
    txt = (oracle_text or "").lower()
    out: List[str] = []
    if "instead" in txt:
        out.append("Replacement effect")
    if "as long as" in txt:
        out.append("Continuous condition")
    if "if " in txt and "instead" in txt:
        out.append("Conditional replacement")
    if "at the beginning of" in txt or "whenever" in txt:
        out.append("Triggered timing")
    if "choose one" in txt or "choose two" in txt:
        out.append("Mode selection")
    if "additional cost" in txt or "as an additional cost" in txt:
        out.append("Additional casting costs")
    if "counter target" in txt:
        out.append("Stack interaction")
    if "cast from your graveyard" in txt or "flashback" in txt:
        out.append("Alternate zone casting")
    return out


def _rule_keywords(flags: List[str]) -> List[str]:
    mapping = {
        "Replacement effect": "replacement effect",
        "Continuous condition": "continuous effect layer",
        "Conditional replacement": "if instead replacement",
        "Triggered timing": "triggered ability timing",
        "Mode selection": "modal spells choose one",
        "Additional casting costs": "additional costs casting spell",
        "Stack interaction": "counter target spell",
        "Alternate zone casting": "cast from graveyard",
    }
    out = []
    for f in flags:
        if f in mapping:
            out.append(mapping[f])
    return out


def build_rules_watchouts(cards: List[CardEntry], commander: str | None) -> List[Dict]:
    svc = CardDataService()
    names = [c.name for c in cards if c.section in {"deck", "commander"}]
    card_map = svc.get_cards_by_name(names)
    rulings_by_oracle = svc.get_rulings_by_oracle_id(card_map)
    watchouts: List[Dict] = []

    ranked_cards = sorted(
        [c for c in cards if c.section in {"deck", "commander"}],
        key=lambda c: (
            -int("#Combo" in c.tags),
            -int("#Engine" in c.tags),
            -int("#Wincon" in c.tags),
            c.name != (commander or ""),
        ),
    )

    for c in ranked_cards[:20]:
        card = card_map.get(c.name, {})
        oracle_text = card.get("oracle_text") or ""
        flags = _complexity_flags(oracle_text)
        rulings = rulings_by_oracle.get(card.get("oracle_id"), [])
        if not flags and not rulings:
            continue
        top_rulings = []
        for r in rulings[:3]:
            if not isinstance(r, dict):
                continue
            top_rulings.append(
                {
                    "published_at": r.get("published_at"),
                    "comment": r.get("comment", ""),
                }
            )
        watchouts.append(
            {
                "card": c.name,
                "commander": c.name == (commander or ""),
                "complexity_flags": flags,
                "rule_queries": _rule_keywords(flags),
                "oracle_watchout": oracle_text[:260],
                "rulings": top_rulings,
                "scryfall_uri": card.get("scryfall_uri"),
            }
        )
    return watchouts
