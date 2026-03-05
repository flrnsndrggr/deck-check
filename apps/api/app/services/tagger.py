from __future__ import annotations

import math
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

from app.core.config import settings
from app.schemas.deck import CardEntry

# Universal taxonomy: broad functional tags + pace modifiers + archetype axes.
# This avoids replacing one ad-hoc list with another per-deck list.
DEFAULT_TAGS = [
    "#Land",
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
    "#CommanderSynergy",
    "#Enabler",
    "#Redundant",
    "#FlexSlot",
    "#PetCard",
    "#FastMana",
    "#Ritual",
    "#Dork",
    "#Rock",
    "#SpotRemoval",
    "#MassRemoval",
    "#StackInteraction",
    "#Tax",
    "#Artifacts",
    "#Enchantments",
    "#Tokens",
    "#Sacrifice",
    "#Spellslinger",
    "#Voltron",
    "#Reanimator",
    "#Storm",
    "#LandsMatter",
    "#Counters",
    "#Blink",
    "#Aristocrats",
    "#Control",
    "#ComboControl",
]

UNIVERSAL_TAG_GROUPS = {
    "core_function": [
        "#Land",
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
    ],
    "structure": ["#CommanderSynergy", "#Enabler", "#Redundant", "#FlexSlot", "#PetCard"],
    "pace_modifiers": ["#FastMana", "#Ritual", "#Dork", "#Rock", "#Tax"],
    "interaction_detail": ["#SpotRemoval", "#MassRemoval", "#StackInteraction"],
    "archetype_axes": [
        "#Artifacts",
        "#Enchantments",
        "#Tokens",
        "#Sacrifice",
        "#Spellslinger",
        "#Voltron",
        "#Reanimator",
        "#Storm",
        "#LandsMatter",
        "#Counters",
        "#Blink",
        "#Aristocrats",
        "#Control",
        "#ComboControl",
    ],
}

TAG_PARENT_RELATIONS = {
    "#FastMana": "#Ramp",
    "#Ritual": "#Ramp",
    "#Dork": "#Ramp",
    "#Rock": "#Ramp",
    "#SpotRemoval": "#Removal",
    "#MassRemoval": "#Boardwipe",
    "#StackInteraction": "#Counter",
    "#Tax": "#Stax",
}

ARCHETYPE_SIGNALS = {
    "artifacts": ["artifact", "treasure", "clue", "equipment", "construct"],
    "spellslinger": ["instant", "sorcery", "noncreature", "magecraft", "prowess", "copy target spell"],
    "tokens": ["create", "token", "populate"],
    "reanimator": ["graveyard", "return target", "reanimate", "unearth"],
    "lands": ["landfall", "additional land", "search your library for a land"],
    "aristocrats": ["sacrifice", "dies", "drain", "whenever another creature"],
    "control": ["counter target", "destroy target", "exile target", "can't cast", "each opponent sacrifices"],
    "combo": ["you win the game", "untap", "extra turn", "copy target spell", "for each spell cast"],
}

STOP_TOKENS = {
    "the",
    "and",
    "with",
    "your",
    "you",
    "each",
    "whenever",
    "beginning",
    "target",
    "from",
    "this",
    "that",
    "until",
    "turn",
    "card",
    "cards",
    "player",
    "players",
}

MANA_PAIR_RE = re.compile(r"add\s+\{[wubrgc]\}(?:\{[wubrgc]\})+", re.IGNORECASE)


def _text(card: Dict) -> str:
    return f"{card.get('type_line','')} {card.get('oracle_text','')}".lower()


def _add_tag(card: CardEntry, tag: str, confidence: float, reason: str):
    if tag not in card.tags:
        card.tags.append(tag)
    card.confidence[tag] = max(card.confidence.get(tag, 0.0), confidence)
    card.explanations[tag] = reason


def _mana_value(card: Dict) -> float:
    try:
        if card.get("mana_value") is not None:
            return float(card.get("mana_value"))
        return float(card.get("cmc") or 0.0)
    except Exception:
        return 0.0


def _is_permanent(type_line: str) -> bool:
    return any(t in type_line for t in ("creature", "artifact", "enchantment", "planeswalker", "battle", "land"))


def _adds_two_or_more_mana(txt: str) -> bool:
    return bool(MANA_PAIR_RE.search(txt))


def _normalise_relations(cards: List[CardEntry]) -> None:
    for c in cards:
        for child, parent in TAG_PARENT_RELATIONS.items():
            if child in c.tags and parent not in c.tags:
                _add_tag(c, parent, min(0.75, c.confidence.get(child, 0.6)), f"Derived parent role from {child}.")


def intrinsic_tags(entry: CardEntry, card: Dict):
    txt = _text(card)
    type_line = (card.get("type_line") or "").lower()
    mv = _mana_value(card)
    produces = card.get("produced_mana") or []
    is_permanent = _is_permanent(type_line)
    adds_multi = _adds_two_or_more_mana(txt)

    if "land" in type_line:
        _add_tag(entry, "#Land", 0.99, "Type line contains Land.")
        if len(produces) >= 2 or "any color" in txt:
            _add_tag(entry, "#Fixing", 0.85, "Produces multiple colors.")
        if adds_multi:
            _add_tag(entry, "#Ramp", 0.7, "Land taps for multiple mana.")
            _add_tag(entry, "#FastMana", 0.6, "Accelerates total mana from land slot.")

    if "artifact" in type_line and ("add {" in txt or "add one mana" in txt or "adds one mana" in txt):
        _add_tag(entry, "#Ramp", 0.86, "Artifact mana source.")
        _add_tag(entry, "#Rock", 0.95, "Artifact with mana ability.")
        if len(produces) >= 2 or "any color" in txt:
            _add_tag(entry, "#Fixing", 0.72, "Artifact helps fix colors.")
        if mv <= 1.0 or (mv <= 2.0 and adds_multi):
            _add_tag(entry, "#FastMana", 0.78, "Low-cost artifact acceleration.")

    if "creature" in type_line and "add {" in txt:
        _add_tag(entry, "#Ramp", 0.8, "Creature mana source.")
        _add_tag(entry, "#Dork", 0.95, "Creature with mana ability.")
        if len(produces) >= 2 or "any color" in txt:
            _add_tag(entry, "#Fixing", 0.68, "Creature contributes color fixing.")

    if any(t in type_line for t in ["instant", "sorcery"]) and "add {" in txt:
        _add_tag(entry, "#Ritual", 0.92, "One-shot spell mana burst.")
        _add_tag(entry, "#Ramp", 0.7, "Temporary mana acceleration.")
        if mv <= 2:
            _add_tag(entry, "#FastMana", 0.7, "Cheap ritual acceleration.")

    if "search your library" in txt:
        _add_tag(entry, "#Tutor", 0.95, "Search-your-library effect.")
        _add_tag(entry, "#Setup", 0.6, "Finds specific pieces.")

    if "draw" in txt or ("exile the top" in txt and "you may play" in txt):
        _add_tag(entry, "#Draw", 0.88, "Card advantage or impulse draw text.")

    if re.search(r"(destroy|exile|return)\s+target\s+(artifact|creature|enchantment|planeswalker|permanent|spell|nonland)", txt):
        _add_tag(entry, "#Removal", 0.9, "Targeted removal text.")
        _add_tag(entry, "#SpotRemoval", 0.85, "Single target interaction.")

    if re.search(r"(destroy|exile)\s+all|all\s+(creatures|artifacts|enchantments|nonland permanents)|each\s+(creature|opponent)\s+sacrifices", txt):
        _add_tag(entry, "#Boardwipe", 0.9, "Mass-removal wording detected.")
        _add_tag(entry, "#MassRemoval", 0.85, "Affects broad board state.")

    if "counter target" in txt:
        _add_tag(entry, "#Counter", 0.95, "Counterspell wording.")
        _add_tag(entry, "#StackInteraction", 0.95, "Interacts on stack.")

    if any(k in txt for k in ["hexproof", "indestructible", "phase out", "protection from", "ward", "can't be countered"]):
        _add_tag(entry, "#Protection", 0.85, "Protective keyword/effect text.")

    if ("return" in txt and "graveyard" in txt) or any(k in txt for k in ["reanimate", "flashback", "escape", "unearth"]):
        _add_tag(entry, "#Recursion", 0.85, "Returns or reuses cards from graveyard.")

    if any(k in txt for k in ["exile target card from a graveyard", "cards in graveyards can't", "if a card would be put into a graveyard, exile it instead"]):
        _add_tag(entry, "#GraveyardHate", 0.85, "Graveyard hate wording.")

    if "sacrifice" in txt:
        _add_tag(entry, "#Sacrifice", 0.65, "Sacrifice text present.")

    if "create" in txt and "token" in txt:
        _add_tag(entry, "#Tokens", 0.75, "Token creation text.")

    if "artifact" in type_line:
        _add_tag(entry, "#Artifacts", 0.6, "Artifact type alignment.")
    if "enchantment" in type_line:
        _add_tag(entry, "#Enchantments", 0.6, "Enchantment type alignment.")

    if is_permanent and ("at the beginning of" in txt or "whenever" in txt):
        _add_tag(entry, "#Engine", 0.6, "Permanent with repeatable trigger/value pattern.")
    if any(x in txt for x in ["you win the game", "each opponent loses", "extra combat", "combat damage to a player", "infinite"]):
        _add_tag(entry, "#Wincon", 0.78, "Win-closing text or deterministic finisher.")
        _add_tag(entry, "#Payoff", 0.65, "Reward-oriented card role.")
    if "search your library" in txt and any(k in txt for k in ["creature", "artifact", "instant", "sorcery", "enchantment", "land"]):
        _add_tag(entry, "#Tutor", 0.9, "Flexible tutor improves line consistency.")
    if any(k in txt for k in ["untap target", "untap all", "copy target spell", "extra turn", "cast this spell without paying"]):
        _add_tag(entry, "#Combo", 0.66, "Combo-enabling action pattern detected.")
    if any(k in txt for k in ["spells your opponents cast cost", "can't cast", "skip", "don't untap", "unless they pay"]):
        _add_tag(entry, "#Stax", 0.7, "Tax/lock language detected.")
    if "unless they pay" in txt or "spells cost" in txt:
        _add_tag(entry, "#Tax", 0.72, "Resource-tax wording detected.")
    if "#Draw" not in entry.tags and "#Tutor" not in entry.tags and mv <= 2 and not is_permanent:
        _add_tag(entry, "#Setup", 0.52, "Low-cost spell likely improves early sequencing.")


def _load_role_overrides() -> Dict[str, Dict]:
    p = Path(settings.rules_cache_dir) / "role_overrides.json"
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text())
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _tokenize(txt: str) -> List[str]:
    return re.findall(r"[a-zA-Z]{3,}", txt.lower())


def _signal_score(joined: str, freq: Counter, signal: str) -> float:
    if " " in signal:
        return float(joined.count(signal))
    return float(freq[signal])


def compute_archetype_weights(cards: List[CardEntry], card_map: Dict[str, Dict], commander: str | None) -> Dict[str, float]:
    corpus = []
    for c in cards:
        if c.section not in {"deck", "commander"}:
            continue
        card = card_map.get(c.name, {})
        corpus.append(_text(card))
    if commander and commander in card_map:
        corpus.append(_text(card_map[commander]) * 2)

    joined = " ".join(corpus)
    tokens = _tokenize(joined)
    freq = Counter(tokens)

    scores = {}
    for arch, signals in ARCHETYPE_SIGNALS.items():
        score = sum(_signal_score(joined, freq, s) for s in signals)
        scores[arch] = score

    total = sum(scores.values())
    if total <= 0:
        return {k: 0.0 for k in ARCHETYPE_SIGNALS}
    return {k: round(v / total, 3) for k, v in scores.items()}


def _commander_key_tokens(commander_txt: str) -> set[str]:
    toks = set(_tokenize(commander_txt))
    return {t for t in toks if len(t) >= 4 and t not in STOP_TOKENS}


def apply_context_tags(cards: List[CardEntry], card_map: Dict[str, Dict], archetypes: Dict[str, float], commander: str | None):
    commander_txt = _text(card_map.get(commander, {})) if commander else ""
    key_tokens = _commander_key_tokens(commander_txt)
    has_commander = bool(commander and commander.strip())

    top_arch = sorted(archetypes.items(), key=lambda kv: kv[1], reverse=True)[:3]
    top_arch_names = {k for k, v in top_arch if v > 0.12}

    for c in cards:
        card_txt = _text(card_map.get(c.name, {}))
        card_tokens = {t for t in _tokenize(card_txt) if len(t) >= 4 and t not in STOP_TOKENS}
        if key_tokens and len(key_tokens & card_tokens) >= 2:
            _add_tag(c, "#CommanderSynergy", 0.72, "Shares key commander text tokens.")

        if has_commander and "artifacts" in top_arch_names and "artifact" in card_txt:
            _add_tag(c, "#CommanderSynergy", 0.67, "Matches dominant artifacts plan.")
        if has_commander and "spellslinger" in top_arch_names and ("instant" in card_txt or "sorcery" in card_txt):
            _add_tag(c, "#Spellslinger", 0.75, "Fits spellslinger profile.")
        if has_commander and "tokens" in top_arch_names and "token" in card_txt:
            _add_tag(c, "#CommanderSynergy", 0.68, "Supports token-centric plan.")
        if "reanimator" in top_arch_names and "graveyard" in card_txt:
            _add_tag(c, "#Reanimator", 0.72, "Supports graveyard recursion gameplan.")
        if "aristocrats" in top_arch_names and "sacrifice" in card_txt:
            _add_tag(c, "#Aristocrats", 0.72, "Supports sacrifice-drain axis.")
        if "control" in top_arch_names and any(x in card_txt for x in ["counter target", "destroy target", "exile target"]):
            _add_tag(c, "#Control", 0.68, "Supports control interaction axis.")
        if "combo" in top_arch_names and any(x in card_txt for x in ["untap", "copy target spell", "you win the game"]):
            _add_tag(c, "#ComboControl", 0.61, "Supports combo-oriented control/combo line.")

        if "#Engine" not in c.tags and "#Payoff" not in c.tags:
            # Deterministic fallback: permanents with recurring text are engines; one-shot spells are payoffs/setup.
            if "creature" in card_txt or "artifact" in card_txt or "enchantment" in card_txt:
                if "whenever" in card_txt or "at the beginning" in card_txt:
                    _add_tag(c, "#Engine", 0.55, "Permanent with recurring trigger text.")
                else:
                    _add_tag(c, "#Payoff", 0.45, "Permanent likely converts resources into board value.")
            else:
                _add_tag(c, "#Setup", 0.45, "Non-permanent support spell.")


def tag_cards(cards: List[CardEntry], card_map: Dict[str, Dict], commander: str | None, use_global_prefix: bool = True) -> Tuple[List[CardEntry], Dict[str, float], List[str]]:
    overrides = _load_role_overrides()
    for c in cards:
        c.tags = []
        c.confidence = {}
        c.explanations = {}
        intrinsic_tags(c, card_map.get(c.name, {}))
        for ov_tag, ov_reason in (overrides.get(c.name, {}) or {}).items():
            _add_tag(c, ov_tag, 0.99, f"Override: {ov_reason}")

    archetypes = compute_archetype_weights(cards, card_map, commander)
    apply_context_tags(cards, card_map, archetypes, commander)
    _normalise_relations(cards)

    lines = []
    prefix = "#!" if use_global_prefix else "#"
    for c in cards:
        tag_tokens = [f"{prefix}{t[1:]}" for t in sorted(set(c.tags))]
        lines.append(f"{c.qty} {c.name}" + (" " + " ".join(tag_tokens) if tag_tokens else ""))
    return cards, archetypes, lines
