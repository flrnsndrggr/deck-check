from __future__ import annotations

import math
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

from app.core.config import settings
from app.schemas.deck import CardEntry
from app.services.commander_utils import commander_names_from_cards

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
    "enchantments": ["enchantment", "aura", "constellation", "saga", "shrine", "background"],
    "spellslinger": ["instant", "sorcery", "noncreature", "magecraft", "prowess", "copy target spell"],
    "tokens": ["create", "token", "populate"],
    "reanimator": ["graveyard", "return target", "reanimate", "unearth"],
    "lands": ["landfall", "additional land", "search your library for a land"],
    "aristocrats": ["sacrifice", "dies", "drain", "whenever another creature"],
    "control": ["counter target", "destroy target", "exile target", "can't cast", "each opponent sacrifices"],
    "combo": ["you win the game", "untap", "extra turn", "copy target spell", "for each spell cast"],
    "tribal": ["chosen creature type", "creature type", "kindred", "shares a creature type"],
    "voltron": ["equipment", "aura attached", "enchanted creature", "commander damage"],
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
TYPE_SPLIT_RE = re.compile(r"\s+[—-]\s+")

SUPERTYPES = {"basic", "legendary", "ongoing", "snow", "world"}
CARD_TYPES = {
    "artifact",
    "battle",
    "creature",
    "enchantment",
    "instant",
    "kindred",
    "land",
    "planeswalker",
    "sorcery",
}


def _text(card: Dict) -> str:
    return f"{card.get('type_line','')} {card.get('oracle_text','')}".lower()


def _type_components(type_line: str) -> tuple[List[str], List[str], List[str]]:
    line = str(type_line or "").replace("—", " — ").strip().lower()
    parts = TYPE_SPLIT_RE.split(line, maxsplit=1)
    left = [token for token in re.split(r"\s+", parts[0]) if token]
    right = [token for token in re.split(r"\s+", parts[1]) if token] if len(parts) > 1 else []
    supertypes = [token for token in left if token in SUPERTYPES]
    card_types = [token for token in left if token in CARD_TYPES]
    subtypes = [token for token in right if token and token not in {"—"}]
    return supertypes, card_types, subtypes


def _display_type_label(token: str) -> str:
    return "-".join(part.capitalize() for part in token.split("-"))


def compute_type_theme_profile(cards: List[CardEntry], card_map: Dict[str, Dict]) -> Dict[str, object]:
    card_type_counts: Counter = Counter()
    supertype_counts: Counter = Counter()
    subtype_counts: Counter = Counter()
    creature_subtype_counts: Counter = Counter()
    artifact_subtype_counts: Counter = Counter()
    enchantment_subtype_counts: Counter = Counter()

    for entry in cards:
        if entry.section not in {"deck", "commander"}:
            continue
        payload = card_map.get(entry.name, {}) or {}
        supertypes, card_types, subtypes = _type_components(payload.get("type_line") or "")
        qty = max(1, int(entry.qty or 1))
        for token in supertypes:
            supertype_counts[token] += qty
        for token in card_types:
            card_type_counts[token] += qty
        for token in subtypes:
            subtype_counts[token] += qty
            if "creature" in card_types:
                creature_subtype_counts[token] += qty
            if "artifact" in card_types:
                artifact_subtype_counts[token] += qty
            if "enchantment" in card_types:
                enchantment_subtype_counts[token] += qty

    dominant_creature = creature_subtype_counts.most_common(1)
    dominant_creature_subtype = None
    if dominant_creature:
        subtype, count = dominant_creature[0]
        if count >= 6:
            dominant_creature_subtype = {"name": _display_type_label(subtype), "count": count}

    package_signals: List[str] = []
    if dominant_creature_subtype:
        package_signals.append(f"{dominant_creature_subtype['name']} is the main creature subtype package ({dominant_creature_subtype['count']} cards).")
    if artifact_subtype_counts.get("equipment", 0) >= 4:
        package_signals.append(f"Equipment density is meaningful ({artifact_subtype_counts['equipment']} cards), which is strong Voltron signal.")
    if enchantment_subtype_counts.get("aura", 0) >= 4:
        package_signals.append(f"Aura density is meaningful ({enchantment_subtype_counts['aura']} cards), which often supports Voltron or enchantress plans.")
    if enchantment_subtype_counts.get("shrine", 0) >= 3:
        package_signals.append(f"Shrine count is high enough to act as a dedicated subtype package ({enchantment_subtype_counts['shrine']} cards).")
    if enchantment_subtype_counts.get("background", 0) >= 1:
        package_signals.append("Background appears in the command package, which is a meaningful deck-construction signal.")

    return {
        "card_types": [{"name": _display_type_label(name), "count": count} for name, count in card_type_counts.most_common(6)],
        "supertypes": [{"name": _display_type_label(name), "count": count} for name, count in supertype_counts.most_common(4)],
        "subtypes": [{"name": _display_type_label(name), "count": count} for name, count in subtype_counts.most_common(8)],
        "creature_subtypes": [{"name": _display_type_label(name), "count": count} for name, count in creature_subtype_counts.most_common(6)],
        "dominant_creature_subtype": dominant_creature_subtype,
        "package_signals": package_signals,
    }


def _apply_type_profile_to_scores(scores: Dict[str, float], type_profile: Dict[str, object]) -> None:
    card_types = {str(row.get("name", "")).lower(): float(row.get("count", 0)) for row in type_profile.get("card_types", []) or []}
    subtypes = {str(row.get("name", "")).lower(): float(row.get("count", 0)) for row in type_profile.get("subtypes", []) or []}
    creature_subtypes = {str(row.get("name", "")).lower(): float(row.get("count", 0)) for row in type_profile.get("creature_subtypes", []) or []}

    scores["artifacts"] += card_types.get("artifact", 0.0) * 1.6 + subtypes.get("equipment", 0.0) * 2.1 + subtypes.get("construct", 0.0) * 0.8
    scores["enchantments"] += card_types.get("enchantment", 0.0) * 1.6 + subtypes.get("aura", 0.0) * 2.0 + subtypes.get("shrine", 0.0) * 2.4 + subtypes.get("saga", 0.0) * 1.4 + subtypes.get("background", 0.0) * 1.3
    scores["spellslinger"] += (card_types.get("instant", 0.0) + card_types.get("sorcery", 0.0)) * 1.35 + creature_subtypes.get("wizard", 0.0) * 0.45
    scores["voltron"] += subtypes.get("equipment", 0.0) * 1.9 + subtypes.get("aura", 0.0) * 1.7
    if type_profile.get("dominant_creature_subtype"):
        dominant = type_profile["dominant_creature_subtype"]
        scores["tribal"] += float(dominant.get("count", 0)) * 2.3


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


def compute_archetype_weights(
    cards: List[CardEntry],
    card_map: Dict[str, Dict],
    commanders: List[str] | str | None = None,
    commander: str | None = None,
) -> Dict[str, float]:
    fallback_commander = commander if commander is not None else commanders
    commander_names = commanders if isinstance(commanders, list) else commander_names_from_cards(cards, fallback_commander=fallback_commander)
    type_profile = compute_type_theme_profile(cards, card_map)
    corpus = []
    for c in cards:
        if c.section not in {"deck", "commander"}:
            continue
        card = card_map.get(c.name, {})
        corpus.append(_text(card))
    for commander in commander_names:
        if commander in card_map:
            corpus.append(_text(card_map[commander]) * 2)

    joined = " ".join(corpus)
    tokens = _tokenize(joined)
    freq = Counter(tokens)

    scores = {}
    for arch, signals in ARCHETYPE_SIGNALS.items():
        score = sum(_signal_score(joined, freq, s) for s in signals)
        scores[arch] = score
    _apply_type_profile_to_scores(scores, type_profile)

    total = sum(scores.values())
    if total <= 0:
        return {k: 0.0 for k in ARCHETYPE_SIGNALS}
    return {k: round(v / total, 3) for k, v in scores.items()}


def _commander_key_tokens(commander_txt: str) -> set[str]:
    toks = set(_tokenize(commander_txt))
    return {t for t in toks if len(t) >= 4 and t not in STOP_TOKENS}


def apply_context_tags(cards: List[CardEntry], card_map: Dict[str, Dict], archetypes: Dict[str, float], commanders: List[str] | str | None):
    commander_names = commanders if isinstance(commanders, list) else commander_names_from_cards(cards, fallback_commander=commanders)
    commander_txt = " ".join(_text(card_map.get(name, {})) for name in commander_names)
    key_tokens = _commander_key_tokens(commander_txt)
    has_commander = bool(commander_names)

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


def tag_cards(
    cards: List[CardEntry],
    card_map: Dict[str, Dict],
    commanders: List[str] | str | None = None,
    use_global_prefix: bool = True,
    commander: str | None = None,
) -> Tuple[List[CardEntry], Dict[str, float], List[str]]:
    overrides = _load_role_overrides()
    for c in cards:
        c.tags = []
        c.confidence = {}
        c.explanations = {}
        intrinsic_tags(c, card_map.get(c.name, {}))
        for ov_tag, ov_reason in (overrides.get(c.name, {}) or {}).items():
            _add_tag(c, ov_tag, 0.99, f"Override: {ov_reason}")

    commander_context = commander if commander is not None and commanders is None else commanders
    archetypes = compute_archetype_weights(cards, card_map, commander_context)
    apply_context_tags(cards, card_map, archetypes, commander_context)
    _normalise_relations(cards)

    lines = []
    prefix = "#!" if use_global_prefix else "#"
    for c in cards:
        tag_tokens = [f"{prefix}{t[1:]}" for t in sorted(set(c.tags))]
        lines.append(f"{c.qty} {c.name}" + (" " + " ".join(tag_tokens) if tag_tokens else ""))
    return cards, archetypes, lines
