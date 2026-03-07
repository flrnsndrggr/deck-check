from __future__ import annotations

import math
import random
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Sequence, Set, Tuple

from app.schemas.deck import CardEntry
from app.services.commander_utils import (
    combined_color_identity,
    commander_display_name,
    has_choose_a_background,
    partner_mode,
)
from app.services.scryfall import CardDataService, QuerySpec
from app.services.tagger import TAG_PARENT_RELATIONS, apply_context_tags, compute_archetype_weights, intrinsic_tags
from app.services.validator import validate_deck

COLOR_TO_BASIC = {
    "W": "Plains",
    "U": "Island",
    "B": "Swamp",
    "R": "Mountain",
    "G": "Forest",
}

GENERIC_NONBASIC_LANDS = [
    "Command Tower",
    "Path of Ancestry",
    "Exotic Orchard",
    "Ash Barrens",
    "Terramorphic Expanse",
    "Evolving Wilds",
    "Myriad Landscape",
    "Opal Palace",
]

COLORLESS_NONBASIC_LANDS = [
    "War Room",
    "Bonders' Enclave",
    "Buried Ruin",
    "Scavenger Grounds",
    "Rogue's Passage",
    "Myriad Landscape",
    "Blast Zone",
    "Demolition Field",
]

STOPWORDS = {
    "the",
    "and",
    "your",
    "with",
    "from",
    "that",
    "this",
    "whenever",
    "beginning",
    "each",
    "card",
    "cards",
    "creature",
    "legendary",
    "commander",
}

CLASS_LIKE_SUBTYPES = {
    "advisor",
    "artificer",
    "assassin",
    "citizen",
    "cleric",
    "druid",
    "knight",
    "monk",
    "ninja",
    "noble",
    "pirate",
    "rogue",
    "samurai",
    "scout",
    "shaman",
    "soldier",
    "warlock",
    "warrior",
    "wizard",
    "human",
}

THEME_PATTERNS: Dict[str, Sequence[str]] = {
    "artifacts": ["artifact", "equipment", "treasure", "clue", "construct", "servo", "thopter"],
    "enchantments": ["enchantment", "aura", "background", "shrine", "saga", "constellation"],
    "spellslinger": ["instant", "sorcery", "magecraft", "prowess", "copy target spell", "whenever you cast an instant or sorcery"],
    "reanimator": ["graveyard", "return target", "reanimate", "flashback", "escape", "unearth"],
    "tokens": ["create", "token", "populate"],
    "aristocrats": ["sacrifice", "dies", "when another creature dies", "whenever another creature dies"],
    "counters": ["+1/+1 counter", "counter on", "proliferate"],
    "lifegain": ["gain life", "whenever you gain life", "lifelink"],
    "combat": ["attack", "attacks", "combat damage", "double strike", "flying", "menace", "trample"],
    "lands": ["landfall", "additional land", "search your library for a land"],
    "blink": ["exile", "return it to the battlefield"],
    "control": ["counter target", "destroy target", "exile target", "can't cast", "each opponent sacrifices"],
    "voltron": ["equipped creature", "enchanted creature", "commander damage"],
}

THEME_TO_PACKAGE = {
    "graveyard": "reanimator",
    "sacrifice": "aristocrats",
}

ARCHETYPE_TO_PACKAGE = {
    "artifacts": "artifacts",
    "enchantments": "enchantments",
    "spellslinger": "spellslinger",
    "tokens": "tokens",
    "reanimator": "reanimator",
    "lands": "lands",
    "aristocrats": "aristocrats",
    "control": "control",
    "combo": "spellslinger",
    "tribal": "typal",
    "voltron": "voltron",
}

ROLE_QUERY_LIBRARY: Dict[str, tuple[Sequence[str], int, str]] = {
    "interaction": (
        [
            'mv<=2 ((t:instant) or o:"prevent all combat damage" or o:"counter target" or o:"destroy target" or o:"exile target" or o:"phase out" or o:"hexproof" or o:"indestructible" or o:"flash") -t:land',
        ],
        160,
        "cmc",
    ),
    "ramp": (
        [
            '(o:"add {" or o:"search your library for a land" or o:"additional land") mv<=4 -t:land',
        ],
        180,
        "cmc",
    ),
    "draw": (
        [
            '(o:"draw" or o:"exile the top" or o:"search your library") mv<=5 -t:land',
        ],
        180,
        "cmc",
    ),
    "protection": (
        [
            '(o:"hexproof" or o:"indestructible" or o:"phase out" or o:"protection from" or o:"ward") mv<=4 -t:land',
        ],
        120,
        "cmc",
    ),
    "broad": (
        [
            "-t:land mv<=7",
        ],
        260,
        "name",
    ),
}

PACKAGE_LIBRARY: Dict[str, Dict[str, Any]] = {
    "artifacts": {
        "commander_signals": ["artifact", "equipment", "treasure", "clue", "construct", "thopter", "servo"],
        "required_axes": {"artifact_mass": 14, "artifact_payoff": 4},
        "preferred_axes": {"token_source": 2, "protection": 2},
        "compatible_secondary": ["tokens", "aristocrats", "blink", "control", "voltron"],
        "anti_synergy_tags": ["#GraveyardHate"],
        "queries": ['(t:artifact or o:"artifact") -t:land', 'o:"artifact creature token" -t:land'],
        "core_target": 16,
        "secondary_target": 7,
        "support_targets": {"artifact_mass": 14, "artifact_payoff": 4},
        "protection_target": 3,
        "land_count": 38,
        "curve_target": "mid",
        "staple_budget_delta": 1,
    },
    "enchantments": {
        "commander_signals": ["enchantment", "aura", "background", "shrine", "constellation", "saga"],
        "required_axes": {"enchantment_mass": 12, "enchantress_payoff": 3},
        "preferred_axes": {"protection": 3, "equipment_aura": 2},
        "compatible_secondary": ["voltron", "blink", "lifegain", "tokens", "control"],
        "anti_synergy_tags": ["#Artifacts"],
        "queries": ['(t:enchantment or o:"enchantment") -t:land', 'o:"constellation" -t:land'],
        "core_target": 14,
        "secondary_target": 6,
        "support_targets": {"enchantment_mass": 12, "enchantress_payoff": 3},
        "protection_target": 4,
        "land_count": 38,
        "curve_target": "mid",
        "staple_budget_delta": 0,
    },
    "spellslinger": {
        "commander_signals": ["instant", "sorcery", "magecraft", "prowess", "copy target spell", "noncreature"],
        "required_axes": {"spell_velocity": 14, "spellslinger_payoff": 3},
        "preferred_axes": {"protection": 2},
        "compatible_secondary": ["tokens", "control", "counters"],
        "anti_synergy_tags": ["#EquipmentPackage", "#AuraPackage"],
        "queries": ['(t:instant or t:sorcery) -t:land', 'o:"cast an instant or sorcery" -t:land'],
        "core_target": 15,
        "secondary_target": 7,
        "support_targets": {"spell_velocity": 14, "spellslinger_payoff": 3},
        "protection_target": 2,
        "land_count": 37,
        "curve_target": "low",
        "staple_budget_delta": 1,
    },
    "tokens": {
        "commander_signals": ["create", "token", "populate", "go wide"],
        "required_axes": {"token_source": 6, "go_wide_payoff": 3},
        "preferred_axes": {"protection": 3, "combat_pressure": 2},
        "compatible_secondary": ["aristocrats", "lifegain", "combat", "blink"],
        "anti_synergy_tags": ["#Boardwipe"],
        "queries": ['o:"create" o:"token" -t:land', 'o:"populate" -t:land'],
        "core_target": 13,
        "secondary_target": 6,
        "support_targets": {"token_source": 6, "go_wide_payoff": 3},
        "protection_target": 3,
        "land_count": 38,
        "curve_target": "mid",
        "staple_budget_delta": -1,
    },
    "aristocrats": {
        "commander_signals": ["sacrifice", "dies", "when another creature dies", "whenever another creature dies", "life and you gain"],
        "required_axes": {"fodder": 6, "sac_outlet": 3, "death_payoff": 3},
        "preferred_axes": {"recursion_spell": 3, "token_source": 3},
        "compatible_secondary": ["tokens", "reanimator", "artifacts"],
        "anti_synergy_tags": ["#GraveyardHate"],
        "queries": ['o:"sacrifice" -t:land', 'o:"dies" -t:land', 'o:"whenever another creature dies" -t:land'],
        "core_target": 15,
        "secondary_target": 7,
        "support_targets": {"fodder": 6, "sac_outlet": 3, "death_payoff": 3},
        "protection_target": 2,
        "land_count": 38,
        "curve_target": "mid",
        "staple_budget_delta": 0,
    },
    "reanimator": {
        "commander_signals": ["graveyard", "reanimate", "return target creature card from your graveyard", "mill", "discard"],
        "required_axes": {"graveyard_fuel": 4, "recursion_spell": 4},
        "preferred_axes": {"graveyard_fuel": 2},
        "compatible_secondary": ["aristocrats", "tokens", "control", "blink"],
        "anti_synergy_tags": ["#GraveyardHate"],
        "queries": ['o:"graveyard" -t:land', 'o:"return target creature card from your graveyard" -t:land', 'o:"mill" -t:land'],
        "core_target": 14,
        "secondary_target": 6,
        "support_targets": {"graveyard_fuel": 4, "recursion_spell": 4},
        "protection_target": 2,
        "land_count": 37,
        "curve_target": "high",
        "staple_budget_delta": 1,
    },
    "counters": {
        "commander_signals": ["+1/+1 counter", "counter on", "proliferate"],
        "required_axes": {"counter_engine": 6, "counter_payoff": 3},
        "preferred_axes": {"protection": 3, "combat_pressure": 2},
        "compatible_secondary": ["lifegain", "combat", "tokens", "spellslinger"],
        "anti_synergy_tags": [],
        "queries": ['o:"+1/+1 counter" -t:land', 'o:"proliferate" -t:land', 'o:"counter on" -t:land'],
        "core_target": 12,
        "secondary_target": 6,
        "support_targets": {"counter_engine": 6, "counter_payoff": 3},
        "protection_target": 3,
        "land_count": 38,
        "curve_target": "mid",
        "staple_budget_delta": 0,
    },
    "lifegain": {
        "commander_signals": ["gain life", "whenever you gain life", "lifelink"],
        "required_axes": {"lifegain_source": 6, "lifegain_payoff": 3},
        "preferred_axes": {"protection": 2},
        "compatible_secondary": ["tokens", "counters", "control", "combat"],
        "anti_synergy_tags": [],
        "queries": ['o:"gain life" -t:land', 'o:"whenever you gain life" -t:land', 'o:"lifelink" -t:land'],
        "core_target": 12,
        "secondary_target": 6,
        "support_targets": {"lifegain_source": 6, "lifegain_payoff": 3},
        "protection_target": 2,
        "land_count": 38,
        "curve_target": "mid",
        "staple_budget_delta": -1,
    },
    "combat": {
        "commander_signals": ["attack", "attacks", "combat damage", "double strike", "flying", "trample", "menace"],
        "required_axes": {"combat_pressure": 8, "evasion": 3},
        "preferred_axes": {"protection": 3},
        "compatible_secondary": ["tokens", "voltron", "lifegain", "counters"],
        "anti_synergy_tags": ["#Boardwipe"],
        "queries": ['o:"attacks" -t:land', 'o:"combat damage" -t:land', 'o:"double strike" -t:land'],
        "core_target": 12,
        "secondary_target": 6,
        "support_targets": {"combat_pressure": 8, "evasion": 3},
        "protection_target": 3,
        "land_count": 38,
        "curve_target": "mid",
        "staple_budget_delta": -1,
    },
    "lands": {
        "commander_signals": ["landfall", "additional land", "search your library for a land", "lands you control"],
        "required_axes": {"land_ramp": 6, "lands_payoff": 3},
        "preferred_axes": {"land_ramp": 2},
        "compatible_secondary": ["tokens", "control", "reanimator"],
        "anti_synergy_tags": ["#FastMana"],
        "queries": ['o:"landfall" -t:land', 'o:"search your library for a land" -t:land', 'o:"additional land" -t:land'],
        "core_target": 12,
        "secondary_target": 6,
        "support_targets": {"land_ramp": 6, "lands_payoff": 3},
        "protection_target": 2,
        "land_count": 39,
        "curve_target": "mid",
        "staple_budget_delta": 0,
    },
    "blink": {
        "commander_signals": ["exile", "return it to the battlefield", "enters the battlefield"],
        "required_axes": {"blink_piece": 4, "etb_target": 6},
        "preferred_axes": {"protection": 2, "token_source": 1},
        "compatible_secondary": ["tokens", "artifacts", "control", "lifegain"],
        "anti_synergy_tags": ["#MassRemoval"],
        "queries": ['o:"return it to the battlefield" o:"exile" -t:land', 'o:"enters the battlefield" t:creature -t:land'],
        "core_target": 12,
        "secondary_target": 6,
        "support_targets": {"blink_piece": 4, "etb_target": 6},
        "protection_target": 2,
        "land_count": 38,
        "curve_target": "mid",
        "staple_budget_delta": 0,
    },
    "control": {
        "commander_signals": ["counter target", "destroy target", "exile target", "can't cast", "each opponent sacrifices", "draw a card"],
        "required_axes": {"interaction": 12, "card_flow": 8},
        "preferred_axes": {"protection": 2, "interaction": 2},
        "compatible_secondary": ["spellslinger", "blink", "reanimator", "enchantments"],
        "anti_synergy_tags": ["#FastMana"],
        "queries": ['(o:"counter target" or o:"destroy target" or o:"exile target" or o:"each opponent sacrifices") -t:land', 'o:"can\'t cast" -t:land'],
        "core_target": 11,
        "secondary_target": 5,
        "support_targets": {"interaction": 12, "card_flow": 8},
        "protection_target": 2,
        "land_count": 38,
        "curve_target": "high",
        "staple_budget_delta": 1,
    },
    "voltron": {
        "commander_signals": ["equipped creature", "enchanted creature", "commander damage", "aura", "equipment"],
        "required_axes": {"equipment_aura": 6, "protection": 4, "evasion": 3},
        "preferred_axes": {"equipment_aura": 2},
        "compatible_secondary": ["combat", "enchantments", "artifacts", "lifegain"],
        "anti_synergy_tags": ["#Boardwipe"],
        "queries": ['(t:equipment or t:aura) -t:land', 'o:"equipped creature" -t:land', 'o:"enchanted creature" -t:land'],
        "core_target": 12,
        "secondary_target": 5,
        "support_targets": {"equipment_aura": 6, "protection": 4, "evasion": 3},
        "protection_target": 5,
        "land_count": 37,
        "curve_target": "low",
        "staple_budget_delta": 0,
    },
    "typal": {
        "commander_signals": ["creature type", "kindred", "shares a creature type"],
        "required_axes": {"typal_body": 12, "typal_payoff": 3},
        "preferred_axes": {"combat_pressure": 3, "protection": 2},
        "compatible_secondary": ["combat", "tokens", "artifacts", "enchantments", "counters"],
        "anti_synergy_tags": [],
        "queries": [],
        "core_target": 16,
        "secondary_target": 6,
        "support_targets": {"typal_body": 12, "typal_payoff": 3},
        "protection_target": 3,
        "land_count": 38,
        "curve_target": "mid",
        "staple_budget_delta": -1,
    },
}

BASE_COVERAGE_TARGETS = {
    "role:ramp": (9.5, 12.5),
    "role:draw": (8.0, 11.0),
    "role:interaction": (10.0, 14.0),
    "role:protection": (2.0, 4.0),
    "role:recursion": (1.0, 3.0),
    "role:wipe": (1.5, 3.0),
    "finisher": (3, 5),
    "role:tutor": (0.0, 2.0),
    "bridge": (4.0, 6.0),
}

EFFECT_FAMILY_LIMITS = {
    "fast_mana": 3,
    "mana_rock": 6,
    "mana_dork": 4,
    "ritual": 3,
    "spot_removal": 4,
    "counterspell": 4,
    "boardwipe": 3,
    "fog": 3,
    "draw_spell": 5,
    "draw_engine": 4,
    "tutor": 3,
    "token_source": 6,
    "blink_piece": 5,
    "protection": 5,
    "generic_value": 8,
}


@dataclass
class CommanderPlan:
    primary_package: str
    secondary_packages: List[str]
    confidence: float
    needs: List[str]
    avoid_tags: List[str]
    staple_budget: int
    protection_target: int
    land_count: int
    curve_target: str
    coverage_targets: Dict[str, tuple[int, int]]
    support_targets: Dict[str, int]
    novelty_weight: float
    speed_tier: str
    subtype_anchor: str | None = None
    commander_archetypes: Dict[str, float] = field(default_factory=dict)


@dataclass
class DeckContext:
    commander_cards: List[Dict[str, Any]]
    commander_names: List[str]
    color_identity: str
    commander_profile: Dict[str, Any]
    plan: CommanderPlan
    bracket: int


@dataclass
class TaggedCandidate:
    card: Dict[str, Any]
    entry: CardEntry
    matched_queries: Set[str]
    roles: Set[str]
    packages: Set[str]
    provides: Set[str]
    needs: Set[str]
    coverage: Dict[str, float]
    effect_family: str
    base_score: float
    popularity_rank: int | None


@dataclass
class GeneratedDeck:
    cards: List[CardEntry]
    selected: List[TaggedCandidate]
    interaction_count: int
    score: float
    metrics: Dict[str, Any]
    draft_seed: int | None = None


def _text(card: Dict) -> str:
    return f"{card.get('type_line', '')} {card.get('oracle_text', '')}".lower()


def _type_line(card: Dict) -> str:
    return str(card.get("type_line") or "").lower()


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-zA-Z]{4,}", text.lower()) if token not in STOPWORDS}


def _mana_value(card: Dict) -> float:
    try:
        return float(card.get("mana_value") or card.get("cmc") or 0.0)
    except Exception:
        return 0.0


def _is_fog(card: Dict) -> bool:
    txt = _text(card)
    return "prevent all combat damage" in txt or "prevent all damage that would be dealt by attacking" in txt


def _count_pips(cards: Sequence[Dict], commander_cards: Sequence[Dict], colors: Sequence[str]) -> Counter:
    counts: Counter = Counter({color: 1 for color in colors})
    mana_texts = [str(card.get("mana_cost") or "") for card in commander_cards]
    mana_texts.extend(str(card.get("mana_cost") or "") for card in cards)
    for mana_cost in mana_texts:
        for color in colors:
            counts[color] += mana_cost.count(f"{{{color}}}")
    return counts


def _safe_name(value: str | None) -> str:
    return str(value or "").strip()


def _as_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except Exception:
        return None


def _package_label(package: str, subtype_anchor: str | None = None) -> str:
    if package == "typal" and subtype_anchor:
        return f"{subtype_anchor} typal"
    return package.replace("_", " ").title()


def _commander_tag_bonus(package: str, commander_tags: Set[str]) -> float:
    mapping = {
        "artifacts": {"#Artifacts"},
        "enchantments": {"#Enchantments"},
        "spellslinger": {"#Spellslinger"},
        "tokens": {"#Tokens"},
        "aristocrats": {"#Aristocrats", "#Sacrifice"},
        "reanimator": {"#Reanimator", "#Recursion"},
        "counters": {"#Counters"},
        "lifegain": {"#Protection"},
        "combat": {"#Wincon", "#Payoff"},
        "lands": {"#LandsMatter"},
        "blink": {"#Blink"},
        "control": {"#Control", "#Counter", "#Removal"},
        "voltron": {"#Voltron", "#Protection"},
        "typal": {"#CommanderSynergy"},
    }
    return float(len(mapping.get(package, set()) & commander_tags)) * 1.7


def _fallback_color_package(color_identity: str) -> str:
    colors = set(color_identity or "")
    if {"U", "R"} <= colors:
        return "spellslinger"
    if {"B", "G"} <= colors:
        return "reanimator"
    if {"W", "G"} <= colors:
        return "tokens"
    if {"W", "U"} <= colors:
        return "blink"
    if {"U", "B"} <= colors:
        return "control"
    if colors == {"G"}:
        return "lands"
    if colors == {"R"}:
        return "combat"
    if colors == {"W"}:
        return "combat"
    if colors == {"B"}:
        return "aristocrats"
    if colors == {"U"}:
        return "control"
    return "combat"


PAYOFF_AXES = {
    "artifact_payoff",
    "enchantress_payoff",
    "spellslinger_payoff",
    "go_wide_payoff",
    "death_payoff",
    "counter_payoff",
    "lifegain_payoff",
    "lands_payoff",
    "typal_payoff",
}


def _is_payoff_axis(package: str, axis: str) -> bool:
    if axis in PAYOFF_AXES:
        return True
    if package in {"combat", "voltron"} and axis in {"combat_pressure", "evasion"}:
        return True
    return False


def _is_role_coverage_key(key: str) -> bool:
    return key.startswith("role:")


def _is_package_coverage_key(key: str) -> bool:
    return key.startswith("pkg:")


class RandomDeckService:
    def __init__(self, rng: random.Random | None = None, card_service: CardDataService | None = None):
        self.rng = rng or random.Random()
        self.card_service = card_service or CardDataService()

    def _random_commander(self) -> Dict:
        query = "game:paper legal:commander t:legendary t:creature -is:funny"
        return self.card_service.fetch_random_card(query)

    def _commander_profile(self, commander_cards: Sequence[Dict]) -> Dict[str, Any]:
        text = " ".join(_text(card) for card in commander_cards)
        raw_subtypes: Counter = Counter()
        for commander in commander_cards:
            type_line = _type_line(commander)
            subtype_text = type_line.split("—", 1)[1] if "—" in type_line else type_line.split("-", 1)[1] if "-" in type_line else ""
            for token in re.split(r"\s+", subtype_text):
                clean = token.strip()
                if clean:
                    raw_subtypes[clean] += 1

        subtype_anchor = None
        for subtype, count in raw_subtypes.most_common():
            if subtype in CLASS_LIKE_SUBTYPES:
                continue
            if count > 1 or subtype in text:
                subtype_anchor = subtype
                break

        themes = {theme for theme, patterns in THEME_PATTERNS.items() if any(pattern in text for pattern in patterns)}
        return {
            "text": text,
            "tokens": _tokens(text),
            "subtypes": set(raw_subtypes.keys()),
            "subtype_anchor": subtype_anchor.capitalize() if subtype_anchor else None,
            "themes": themes,
        }

    def _entry_with_tags(self, name: str, section: str = "deck") -> CardEntry:
        return CardEntry(qty=1, name=name, section=section, tags=[], confidence={}, explanations={})

    def _fetch_named_card(self, name: str) -> Dict | None:
        exact = _safe_name(name)
        if not exact:
            return None
        probes = [str(name or "").strip(), exact]
        seen: Set[str] = set()
        for probe in probes:
            probe = str(probe or "").strip()
            if not probe or probe in seen:
                continue
            seen.add(probe)
            fetched = self.card_service.get_cards_by_name([probe])
            if fetched:
                return fetched.get(probe) or fetched.get(_safe_name(probe)) or next(iter(fetched.values()), None)
        return None

    def _partner_with_target_name(self, primary_commander: Dict) -> str | None:
        oracle = str(primary_commander.get("oracle_text") or "")
        for line in oracle.splitlines():
            match = re.search(r"partner with ([^(.\n]+)", line, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def _candidate_team_score(self, primary: Dict, secondary: Dict) -> float:
        if not primary or not secondary:
            return -999.0
        primary_name = _safe_name(primary.get("name"))
        secondary_name = _safe_name(secondary.get("name"))
        if not primary_name or not secondary_name or primary_name == secondary_name:
            return -999.0
        profile = self._commander_profile([primary, secondary])
        commander_map = {primary_name: primary, secondary_name: secondary}
        commander_entries = [self._entry_with_tags(primary_name, "commander"), self._entry_with_tags(secondary_name, "commander")]
        archetypes = compute_archetype_weights(commander_entries, commander_map, [primary_name, secondary_name])
        overlap = len(_tokens(_text(primary)) & _tokens(_text(secondary)))
        top_arch = sorted(archetypes.values(), reverse=True)[:2]
        focus = sum(top_arch)
        color_spread = len(combined_color_identity(commander_map, [primary_name, secondary_name]))
        subtype_bonus = 0.0
        primary_profile = self._commander_profile([primary])
        secondary_profile = self._commander_profile([secondary])
        if primary_profile.get("subtype_anchor") and primary_profile.get("subtype_anchor") == secondary_profile.get("subtype_anchor"):
            subtype_bonus += 2.4
        if primary_profile.get("themes") and secondary_profile.get("themes"):
            subtype_bonus += len(set(primary_profile["themes"]) & set(secondary_profile["themes"])) * 1.7
        return overlap * 0.7 + focus * 12.0 + subtype_bonus - max(0, color_spread - 3) * 0.3

    def _search_pair_candidates(self, query: str, limit: int = 120) -> List[Dict[str, Any]]:
        return self.card_service.search_candidates(query, None, limit=limit, order="name", direction="asc")

    def _random_partner_commander(self, primary_card: Dict) -> Dict | None:
        primary_name = _safe_name(primary_card.get("name"))
        candidates = self._search_pair_candidates('t:legendary t:creature o:"Partner (" -o:"Partner with" -is:funny', limit=96)
        ranked = []
        for card in candidates:
            if _safe_name(card.get("name")).lower() == primary_name.lower():
                continue
            ranked.append((self._candidate_team_score(primary_card, card), card))
        return self._pick_rank_band(ranked, window=8)

    def _random_background(self, primary_card: Dict) -> Dict | None:
        candidates = self._search_pair_candidates("t:background -is:funny", limit=72)
        ranked = [(self._candidate_team_score(primary_card, card), card) for card in candidates]
        return self._pick_rank_band(ranked, window=8)

    def _secondary_commander(self, primary_commander: Dict) -> Dict | None:
        mode, value = partner_mode(primary_commander)
        if mode == "partner_with" and value:
            raw_name = self._partner_with_target_name(primary_commander) or value
            return self._fetch_named_card(raw_name)
        if mode == "partner":
            return self._random_partner_commander(primary_commander)
        if has_choose_a_background(primary_commander):
            return self._random_background(primary_commander)
        return None

    def _infer_plan(self, commander_cards: Sequence[Dict], bracket: int) -> CommanderPlan:
        commander_names = [_safe_name(card.get("name")) for card in commander_cards if _safe_name(card.get("name"))]
        commander_map = {name: card for name, card in zip(commander_names, commander_cards)}
        commander_entries = [self._entry_with_tags(name, "commander") for name in commander_names]
        for entry in commander_entries:
            intrinsic_tags(entry, commander_map.get(entry.name, {}))
        commander_tags = {tag for entry in commander_entries for tag in entry.tags}
        profile = self._commander_profile(commander_cards)
        archetypes = compute_archetype_weights(commander_entries, commander_map, commander_names)
        scores: Dict[str, float] = {}
        commander_text = profile["text"]
        for package, spec in PACKAGE_LIBRARY.items():
            score = 0.0
            signal_hits = 0
            for signal in spec.get("commander_signals", []):
                hits = commander_text.count(signal)
                if hits:
                    signal_hits += hits
                    score += hits * 2.1
            for theme in profile["themes"]:
                mapped = THEME_TO_PACKAGE.get(theme, theme)
                if mapped == package:
                    score += 4.2
            score += _commander_tag_bonus(package, commander_tags)
            for archetype, weight in archetypes.items():
                mapped = ARCHETYPE_TO_PACKAGE.get(archetype)
                if mapped == package:
                    score += weight * 8.0
            if package == "typal" and profile.get("subtype_anchor"):
                subtype_token = str(profile.get("subtype_anchor") or "").lower()
                score += 7.2
                if subtype_token and any(term in commander_text for term in (subtype_token, f"{subtype_token} creatures", "creature type", "chosen type", "kindred")):
                    score += 4.4
            if package == "blink" and "exile" in commander_text and "return it to the battlefield" in commander_text:
                score += 6.0
            if package == "aristocrats" and any(term in commander_text for term in ("whenever another creature dies", "whenever you sacrifice", "sacrifice another creature")):
                score += 4.5
            if package == "voltron" and "combat" in profile["themes"]:
                score += 1.2
            scores[package] = score

        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        top_score = ranked[0][1] if ranked else 0.0
        second_score = ranked[1][1] if len(ranked) > 1 else -999.0
        low_confidence = top_score < 4.5
        if low_confidence and profile.get("subtype_anchor"):
            primary_package = "typal"
            primary_score = max(top_score, 4.8)
        elif low_confidence:
            primary_package = _fallback_color_package("".join(combined_color_identity(commander_map, commander_names)))
            primary_score = max(top_score, 4.1)
        elif top_score - second_score >= 2.0:
            primary_package = ranked[0][0]
            primary_score = top_score
        else:
            top_band = [(package, score) for package, score in ranked if score >= max(3.5, top_score * 0.72)]
            weights = [max(0.2, score) for _package, score in top_band]
            primary_package = self.rng.choices([package for package, _score in top_band], weights=weights, k=1)[0]
            primary_score = dict(top_band)[primary_package]

        primary_spec = PACKAGE_LIBRARY[primary_package]
        secondary_candidates = []
        compatible = set(primary_spec.get("compatible_secondary", []))
        primary_anti = set(primary_spec.get("anti_synergy_tags", []))
        for package, score in ranked:
            if package == primary_package:
                continue
            if compatible and package not in compatible:
                continue
            if score < max(2.6, primary_score * 0.38):
                continue
            secondary_spec = PACKAGE_LIBRARY[package]
            if primary_anti & set(secondary_spec.get("anti_synergy_tags", [])):
                continue
            compatibility_bonus = 1.0 if primary_package in secondary_spec.get("compatible_secondary", []) else 0.0
            secondary_candidates.append((score + compatibility_bonus, package))
        secondary_candidates.sort(reverse=True)
        secondary_packages = [package for _score, package in secondary_candidates[:2]]

        coverage_targets = {key: tuple(value) for key, value in BASE_COVERAGE_TARGETS.items()}
        coverage_targets["role:protection"] = (
            max(coverage_targets["role:protection"][0], float(max(1, int(primary_spec.get("protection_target", 2)) - 1))),
            max(coverage_targets["role:protection"][1], float(int(primary_spec.get("protection_target", 2)) + 1)),
        )
        support_targets = dict(primary_spec.get("required_axes", {}))
        for axis, target in primary_spec.get("preferred_axes", {}).items():
            support_targets[axis] = max(support_targets.get(axis, 0), target)
        for package in secondary_packages:
            spec = PACKAGE_LIBRARY[package]
            for axis, target in spec.get("required_axes", {}).items():
                support_targets[axis] = max(support_targets.get(axis, 0), max(2, int(target * 0.6)))
            for axis, target in spec.get("preferred_axes", {}).items():
                support_targets[axis] = max(support_targets.get(axis, 0), max(1, int(target * 0.5)))

        if primary_package == "control":
            coverage_targets["role:interaction"] = (13.0, 17.0)
            coverage_targets["role:wipe"] = (2.0, 4.0)
            coverage_targets["role:draw"] = (9.0, 12.0)
        elif primary_package == "voltron":
            coverage_targets["role:interaction"] = (9.0, 13.0)
            coverage_targets["finisher"] = (2, 4)
        elif primary_package == "spellslinger":
            coverage_targets["role:draw"] = (10.0, 14.0)
            coverage_targets["role:tutor"] = (1.0, float(4 if bracket >= 4 else 2))
        elif primary_package == "aristocrats":
            coverage_targets["role:recursion"] = (3.0, 6.0)
            coverage_targets["finisher"] = (4, 6)
        elif primary_package == "tokens":
            coverage_targets["finisher"] = (4, 6)
        elif primary_package == "reanimator":
            coverage_targets["role:recursion"] = (4.0, 6.0)
            coverage_targets["role:tutor"] = (1.0, float(3 if bracket >= 3 else 2))
        elif primary_package == "artifacts":
            coverage_targets["role:ramp"] = (10.0, 13.0)
        elif primary_package == "lands":
            coverage_targets["role:ramp"] = (10.0, 14.0)
        elif primary_package == "typal":
            coverage_targets["finisher"] = (4, 6)

        primary_required_axes = primary_spec.get("required_axes", {})
        primary_enablers = [axis for axis in primary_required_axes if not _is_payoff_axis(primary_package, axis)]
        primary_payoffs = [axis for axis in primary_required_axes if _is_payoff_axis(primary_package, axis)]
        coverage_targets["pkg:primary_enabler"] = (
            float(max(4, sum(primary_required_axes.get(axis, 0) for axis in primary_enablers) or max(4, int(primary_spec.get("core_target", 12) * 0.55)))),
            float(max(5, sum(primary_required_axes.get(axis, 0) for axis in primary_enablers) + 2 if primary_enablers else int(primary_spec.get("core_target", 12) * 0.7))),
        )
        coverage_targets["pkg:primary_payoff"] = (
            float(max(2, sum(primary_required_axes.get(axis, 0) for axis in primary_payoffs) or max(2, int(primary_spec.get("core_target", 12) * 0.25)))),
            float(max(3, (sum(primary_required_axes.get(axis, 0) for axis in primary_payoffs) or max(2, int(primary_spec.get("core_target", 12) * 0.25))) + 2)),
        )
        for package in secondary_packages:
            spec = PACKAGE_LIBRARY[package]
            required_axes = spec.get("required_axes", {})
            enablers = [axis for axis in required_axes if not _is_payoff_axis(package, axis)]
            payoffs = [axis for axis in required_axes if _is_payoff_axis(package, axis)]
            enabler_floor = max(2, int(round((sum(required_axes.get(axis, 0) for axis in enablers) or spec.get("secondary_target", 6)) * 0.55)))
            payoff_floor = max(1, int(round((sum(required_axes.get(axis, 0) for axis in payoffs) or max(2, spec.get("secondary_target", 6) * 0.35)) * 0.65)))
            coverage_targets["pkg:secondary_enabler"] = (
                float(max(coverage_targets.get("pkg:secondary_enabler", (0.0, 0.0))[0], enabler_floor)),
                float(max(coverage_targets.get("pkg:secondary_enabler", (0.0, 0.0))[1], enabler_floor + 2)),
            )
            coverage_targets["pkg:secondary_payoff"] = (
                float(max(coverage_targets.get("pkg:secondary_payoff", (0.0, 0.0))[0], payoff_floor)),
                float(max(coverage_targets.get("pkg:secondary_payoff", (0.0, 0.0))[1], payoff_floor + 2)),
            )

        secondary_specs = [PACKAGE_LIBRARY[package] for package in secondary_packages]
        avoid_tags = list(
            dict.fromkeys(
                list(primary_spec.get("anti_synergy_tags", []))
                + [tag for spec in secondary_specs for tag in spec.get("anti_synergy_tags", [])]
            )
        )
        confidence = round(min(0.95, primary_score / max(6.0, sum(score for _package, score in ranked[:3]) or 1.0)), 3)
        if low_confidence:
            confidence = min(confidence, 0.42 if not profile.get("subtype_anchor") else 0.52)

        staple_budget_by_bracket = {1: 3, 2: 5, 3: 7, 4: 10, 5: 13}
        novelty_by_bracket = {1: 1.8, 2: 1.5, 3: 1.2, 4: 0.8, 5: 0.55}
        speed_tier = "casual" if bracket <= 2 else "balanced" if bracket == 3 else "optimized"
        protection_target = max([int(primary_spec.get("protection_target", 2)), *[int(spec.get("protection_target", 2)) for spec in secondary_specs]])
        land_count = max(int(primary_spec.get("land_count", 38)), *[int(spec.get("land_count", 38)) for spec in secondary_specs]) if secondary_specs else int(primary_spec.get("land_count", 38))
        curve_target = str(primary_spec.get("curve_target", "mid"))
        needs = list(dict.fromkeys(list(primary_spec.get("required_axes", {}).keys()) + list(primary_spec.get("preferred_axes", {}).keys())))

        return CommanderPlan(
            primary_package=primary_package,
            secondary_packages=secondary_packages,
            confidence=confidence,
            needs=needs,
            avoid_tags=avoid_tags,
            staple_budget=max(1, staple_budget_by_bracket.get(bracket, 7) + int(primary_spec.get("staple_budget_delta", 0))),
            protection_target=protection_target,
            land_count=land_count,
            curve_target=curve_target,
            coverage_targets=coverage_targets,
            support_targets=support_targets,
            novelty_weight=novelty_by_bracket.get(bracket, 1.2),
            speed_tier=speed_tier,
            subtype_anchor=profile.get("subtype_anchor"),
            commander_archetypes=archetypes,
        )

    def _build_context(self, commander_cards: Sequence[Dict], bracket: int) -> DeckContext:
        commander_names = [_safe_name(card.get("name")) for card in commander_cards if _safe_name(card.get("name"))]
        commander_map = {name: card for name, card in zip(commander_names, commander_cards)}
        color_identity = "".join(combined_color_identity(commander_map, commander_names))
        profile = self._commander_profile(commander_cards)
        plan = self._infer_plan(commander_cards, bracket)
        return DeckContext(
            commander_cards=list(commander_cards),
            commander_names=commander_names,
            color_identity=color_identity,
            commander_profile=profile,
            plan=plan,
            bracket=bracket,
        )

    def _format_package_query(self, package: str, subtype_anchor: str | None) -> Sequence[str]:
        if package != "typal":
            return PACKAGE_LIBRARY.get(package, {}).get("queries", [])
        if not subtype_anchor:
            return []
        subtype = subtype_anchor.lower()
        return [f"t:{subtype} -t:land", f'o:"{subtype}" -t:land']

    def _fetch_candidate_pool(self, context: DeckContext) -> Dict[str, Dict[str, Any]]:
        query_specs: List[QuerySpec] = []
        commander_names = set(context.commander_names)

        for role_name, (queries, limit, order) in ROLE_QUERY_LIBRARY.items():
            for idx, query in enumerate(queries):
                query_specs.append(
                    QuerySpec(
                        label=f"role:{role_name}:{idx}",
                        query=query,
                        limit=limit,
                        order=order,
                        direction="asc",
                    )
                )

        packages = [context.plan.primary_package, *context.plan.secondary_packages]
        for package in packages:
            for idx, query in enumerate(self._format_package_query(package, context.plan.subtype_anchor)):
                query_specs.append(
                    QuerySpec(
                        label=f"pkg:{package}:{idx}",
                        query=query,
                        limit=220 if package == context.plan.primary_package else 180,
                        order="name",
                        direction="asc",
                    )
                )

        for idx, commander in enumerate(context.commander_cards):
            tokens = sorted(_tokens(_text(commander)))
            if not tokens:
                continue
            query_tokens = [token for token in tokens if len(token) >= 5][:4]
            if query_tokens:
                query_specs.append(
                    QuerySpec(
                        label=f"cmdr:text:{idx}",
                        query=" ".join(f'o:\"{token}\"' for token in query_tokens) + " -t:land",
                        limit=180,
                        order="name",
                        direction="asc",
                    )
                )
        if context.plan.subtype_anchor:
            subtype = context.plan.subtype_anchor.lower()
            query_specs.append(
                QuerySpec(
                    label="pkg:typal_anchor",
                    query=f"t:{subtype} -t:land",
                    limit=200,
                    order="name",
                    direction="asc",
                )
            )

        pool: Dict[str, Dict[str, Any]] = {}
        for card in self.card_service.search_union(query_specs, context.color_identity):
            name = _safe_name(card.get("name"))
            if not name or name in commander_names or "land" in _type_line(card):
                continue
            pool.setdefault(name, card)
        return pool

    def _candidate_roles(self, card: Dict, entry: CardEntry) -> Set[str]:
        tags = set(entry.tags)
        txt = _text(card)
        type_line = _type_line(card)
        roles: Set[str] = set()
        if "#Ramp" in tags or "{t}: add" in txt or "create a treasure token" in txt or "search your library for a land" in txt:
            roles.add("ramp")
        if "#Draw" in tags or "#Tutor" in tags or "draw " in txt or "surveil" in txt or "discover" in txt:
            roles.add("draw")
        if (
            {"#Removal", "#Counter", "#Boardwipe", "#Protection"} & tags
            or _is_fog(card)
            or "counter target" in txt
            or "destroy target" in txt
            or "exile target" in txt
            or "return target" in txt and "to its owner's hand" in txt
            or "each opponent sacrifices" in txt
        ):
            roles.add("interaction")
        if "#Protection" in tags or any(term in txt for term in ["hexproof", "indestructible", "ward", "phase out", "protection from", "can't be the target"]):
            roles.add("protection")
        if "#Recursion" in tags or any(term in txt for term in ["return target", "from your graveyard", "reanimate"]):
            roles.add("recursion")
        if "#Boardwipe" in tags or "destroy all" in txt or "exile all" in txt or "each creature gets -x/-x" in txt:
            roles.add("boardwipe")
        if "#Tutor" in tags or "search your library" in txt:
            roles.add("tutor")
        if "#Wincon" in tags or "#Combo" in tags or "#Payoff" in tags:
            roles.add("finisher")
        if "#Engine" in tags or "#Setup" in tags or "whenever" in txt or ("artifact" in type_line and "{t}: add" in txt):
            roles.add("setup")
        return roles

    def _candidate_packages(self, card: Dict, entry: CardEntry, context: DeckContext) -> Set[str]:
        tags = set(entry.tags)
        txt = _text(card)
        type_line = _type_line(card)
        packages: Set[str] = set()
        if "#Artifacts" in tags or "artifact" in type_line:
            packages.add("artifacts")
        if "#Enchantments" in tags or "enchantment" in type_line:
            packages.add("enchantments")
        if "#Tokens" in tags or ("create" in txt and "token" in txt):
            packages.add("tokens")
        if "#Sacrifice" in tags or "#Aristocrats" in tags or "dies" in txt:
            packages.add("aristocrats")
        if "#Recursion" in tags and "graveyard" in txt or any(term in txt for term in ["graveyard", "reanimate", "return target creature card from your graveyard"]):
            packages.add("reanimator")
        if "instant" in type_line or "sorcery" in type_line or "#Spellslinger" in tags:
            packages.add("spellslinger")
        if any(term in txt for term in ["+1/+1 counter", "counter on", "proliferate"]):
            packages.add("counters")
        if any(term in txt for term in ["gain life", "whenever you gain life", "lifelink"]):
            packages.add("lifegain")
        if any(term in txt for term in ["landfall", "additional land", "search your library for a land"]):
            packages.add("lands")
        if "exile" in txt and ("return it to the battlefield" in txt or "then return that card to the battlefield" in txt):
            packages.add("blink")
        elif context.plan.primary_package == "blink" and "enters the battlefield" in txt and "creature" in type_line:
            packages.add("blink")
        if {"#Counter", "#Removal", "#Boardwipe", "#Stax"} & tags:
            packages.add("control")
        if {"#Voltron"} & tags or "equipment" in type_line or "aura" in type_line or any(term in txt for term in ["equipped creature", "enchanted creature", "commander damage"]):
            packages.add("voltron")
        if any(term in txt for term in ["attacks", "combat damage", "double strike", "trample", "flying"]):
            packages.add("combat")
        if context.plan.subtype_anchor and context.plan.subtype_anchor.lower() in type_line:
            packages.add("typal")
        return packages

    def _candidate_support_axes(self, card: Dict, entry: CardEntry, context: DeckContext) -> tuple[Set[str], Set[str]]:
        txt = _text(card)
        type_line = _type_line(card)
        tags = set(entry.tags)
        provides: Set[str] = set()
        needs: Set[str] = set()
        role_set = self._candidate_roles(card, entry)

        if "interaction" in role_set:
            provides.add("interaction")
        if "draw" in role_set:
            provides.add("card_flow")

        if "#Tokens" in tags or ("create" in txt and "token" in txt):
            provides.update({"token_source", "fodder"})
        if re.search(r"sacrifice\s+(another|a)\s+creature", txt) or re.search(r"sacrifice[^.]*:", txt):
            provides.add("sac_outlet")
        if "dies" in txt and any(term in txt for term in ["each opponent loses", "opponent loses", "gain 1 life", "drain"]):
            provides.add("death_payoff")
        if "#Recursion" in tags:
            provides.add("recursion_spell")
        if any(term in txt for term in ["mill", "surveil", "discard a card"]):
            provides.add("graveyard_fuel")
        if "enters the battlefield" in txt and "creature" in type_line:
            provides.add("etb_target")
        if "exile" in txt and "return it to the battlefield" in txt:
            provides.add("blink_piece")
            needs.add("etb_target")
        if "#Artifacts" in tags or "artifact" in type_line:
            provides.add("artifact_mass")
        if "#Artifacts" in tags and any(term in txt for term in ["artifacts you control", "cast an artifact spell", "whenever an artifact"]):
            provides.add("artifact_payoff")
        if "#Enchantments" in tags or "enchantment" in type_line:
            provides.add("enchantment_mass")
        if any(term in txt for term in ["whenever you cast an enchantment spell", "constellation", "draw a card whenever you cast an enchantment"]):
            provides.add("enchantress_payoff")
        if "instant" in type_line or "sorcery" in type_line:
            provides.add("spell_velocity")
        if any(term in txt for term in ["magecraft", "whenever you cast an instant or sorcery", "copy target spell"]):
            provides.add("spellslinger_payoff")
            needs.add("spell_velocity")
        if any(term in txt for term in ["+1/+1 counter", "counter on", "proliferate"]):
            provides.add("counter_engine")
        if any(term in txt for term in ["whenever one or more +1/+1 counters", "for each counter on", "when a counter is put"]):
            provides.add("counter_payoff")
            needs.add("counter_engine")
        if any(term in txt for term in ["gain life", "lifelink"]):
            provides.add("lifegain_source")
        if "whenever you gain life" in txt:
            provides.add("lifegain_payoff")
            needs.add("lifegain_source")
        if any(term in txt for term in ["search your library for a land", "additional land", "landfall"]):
            provides.add("land_ramp")
        if any(term in txt for term in ["landfall", "whenever a land enters", "lands you control"]):
            provides.add("lands_payoff")
        if {"#Protection"} & tags or any(term in txt for term in ["hexproof", "indestructible", "phase out", "ward", "protection from"]):
            provides.add("protection")
        if "equipment" in type_line or "aura" in type_line:
            provides.add("equipment_aura")
        if any(term in txt for term in ["flying", "menace", "trample", "unblockable", "skulk", "fear", "double strike"]):
            provides.add("evasion")
        if any(term in txt for term in ["attacks", "combat damage", "extra combat"]):
            provides.add("combat_pressure")
        if context.plan.subtype_anchor and context.plan.subtype_anchor.lower() in type_line:
            provides.add("typal_body")
        if context.plan.subtype_anchor and any(term in txt for term in [context.plan.subtype_anchor.lower(), "creature type", "chosen type", "kindred"]):
            provides.add("typal_payoff")
        if "sacrifice" in txt and "token" not in txt:
            needs.add("fodder")
        if "whenever another creature dies" in txt or "whenever you sacrifice" in txt:
            needs.update({"fodder", "sac_outlet"})
        if any(term in txt for term in ["return target creature card from your graveyard", "reanimate", "escape", "flashback"]):
            needs.add("graveyard_fuel")
        if "proliferate" in txt:
            needs.add("counter_engine")
        return provides, needs

    def _candidate_coverage(
        self,
        card: Dict,
        entry: CardEntry,
        context: DeckContext,
        roles: Set[str],
        packages: Set[str],
        provides: Set[str],
    ) -> Dict[str, float]:
        txt = _text(card)
        tags = set(entry.tags)
        coverage: Dict[str, float] = {}

        if "ramp" in roles:
            ramp_value = 1.0
            if "#Ritual" in tags:
                ramp_value = 0.7
            elif "treasure" in txt or "create a treasure" in txt:
                ramp_value = 0.6
            coverage["role:ramp"] = max(coverage.get("role:ramp", 0.0), ramp_value)
        if "draw" in roles:
            draw_value = 1.0
            if "#Engine" in tags and "#Draw" in tags:
                draw_value = 0.9
            coverage["role:draw"] = max(coverage.get("role:draw", 0.0), draw_value)
        if "interaction" in roles:
            coverage["role:interaction"] = max(coverage.get("role:interaction", 0.0), 1.0)
        if "protection" in roles:
            coverage["role:protection"] = max(coverage.get("role:protection", 0.0), 1.0)
        if "recursion" in roles:
            coverage["role:recursion"] = max(coverage.get("role:recursion", 0.0), 1.0)
        if "boardwipe" in roles:
            coverage["role:wipe"] = max(coverage.get("role:wipe", 0.0), 1.0)
        if "tutor" in roles:
            coverage["role:tutor"] = max(coverage.get("role:tutor", 0.0), 1.0)
        if "finisher" in roles:
            coverage["finisher"] = max(coverage.get("finisher", 0.0), 1.0)

        primary_axes = self._package_axis_targets(context.plan.primary_package, secondary=False)
        primary_enabler_axes = {axis for axis in primary_axes if not _is_payoff_axis(context.plan.primary_package, axis)}
        primary_payoff_axes = {axis for axis in primary_axes if _is_payoff_axis(context.plan.primary_package, axis)}
        primary_enabler_hits = len(primary_enabler_axes & provides)
        primary_payoff_hits = len(primary_payoff_axes & provides)
        if context.plan.primary_package in packages and primary_enabler_hits:
            coverage["pkg:primary_enabler"] = min(1.2, 0.8 + 0.2 * (primary_enabler_hits - 1))
        if context.plan.primary_package in packages and primary_payoff_hits:
            coverage["pkg:primary_payoff"] = min(1.1, 0.8 + 0.15 * (primary_payoff_hits - 1))

        secondary_enabler = 0.0
        secondary_payoff = 0.0
        for package in context.plan.secondary_packages:
            if package not in packages:
                continue
            axes = self._package_axis_targets(package, secondary=True)
            enabler_axes = {axis for axis in axes if not _is_payoff_axis(package, axis)}
            payoff_axes = {axis for axis in axes if _is_payoff_axis(package, axis)}
            if enabler_axes & provides:
                secondary_enabler = max(secondary_enabler, min(1.0, 0.75 + 0.15 * (len(enabler_axes & provides) - 1)))
            if payoff_axes & provides:
                secondary_payoff = max(secondary_payoff, min(1.0, 0.75 + 0.15 * (len(payoff_axes & provides) - 1)))
        if secondary_enabler:
            coverage["pkg:secondary_enabler"] = secondary_enabler
        if secondary_payoff:
            coverage["pkg:secondary_payoff"] = secondary_payoff

        generic_shell_keys = {
            key
            for key, value in coverage.items()
            if key.startswith("role:") or key == "finisher"
            if value > 0
        }
        package_keys = {
            key
            for key in ("pkg:primary_enabler", "pkg:primary_payoff", "pkg:secondary_enabler", "pkg:secondary_payoff")
            if coverage.get(key, 0) > 0
        }
        if generic_shell_keys and package_keys:
            coverage["bridge"] = 1.0
        elif len(generic_shell_keys) >= 2:
            coverage["bridge"] = 0.7

        return coverage

    def _effect_family(self, card: Dict, entry: CardEntry, context: DeckContext) -> str:
        tags = set(entry.tags)
        if "#FastMana" in tags:
            return "fast_mana"
        if "#Rock" in tags:
            return "mana_rock"
        if "#Dork" in tags:
            return "mana_dork"
        if "#Ritual" in tags:
            return "ritual"
        if _is_fog(card):
            return "fog"
        if "#Boardwipe" in tags:
            return "boardwipe"
        if "#Counter" in tags:
            return "counterspell"
        if "#Removal" in tags:
            return "spot_removal"
        if "#Tutor" in tags:
            return "tutor"
        if "#Draw" in tags and "#Engine" in tags:
            return "draw_engine"
        if "#Draw" in tags:
            return "draw_spell"
        if "#Tokens" in tags:
            return "token_source"
        if "#Protection" in tags:
            return "protection"
        if "blink" in self._candidate_packages(card, entry, context):
            return "blink_piece"
        if context.plan.primary_package in self._candidate_packages(card, entry, context):
            return f"{context.plan.primary_package}_core"
        return "generic_value"

    def _candidate_synergy_score(self, card: Dict, entry: CardEntry, context: DeckContext) -> float:
        txt = _text(card)
        card_tokens = _tokens(txt)
        type_line = _type_line(card)
        score = 0.0
        score += min(4, len(card_tokens & set(context.commander_profile["tokens"]))) * 0.9
        if context.plan.subtype_anchor and context.plan.subtype_anchor.lower() in type_line:
            score += 2.8
        if "#CommanderSynergy" in entry.tags:
            score += 2.4
        if context.plan.primary_package in self._candidate_packages(card, entry, context):
            score += 2.0
        for package in context.plan.secondary_packages:
            if package in self._candidate_packages(card, entry, context):
                score += 0.9
        if "#Engine" in entry.tags:
            score += 0.6
        if "#Payoff" in entry.tags:
            score += 0.4
        mv = _mana_value(card)
        if mv >= 7:
            score -= 1.5
        elif mv >= 5:
            score -= 0.5
        return score

    def _tag_candidate_pool(self, context: DeckContext, pool_map: Dict[str, Dict[str, Any]]) -> List[TaggedCandidate]:
        commander_map = {name: card for name, card in zip(context.commander_names, context.commander_cards)}
        card_map = {**commander_map, **pool_map}
        candidate_entries = [self._entry_with_tags(name) for name in pool_map]
        commander_entries = [self._entry_with_tags(name, "commander") for name in context.commander_names]

        for entry in [*commander_entries, *candidate_entries]:
            intrinsic_tags(entry, card_map.get(entry.name, {}))

        commander_archetypes = compute_archetype_weights(commander_entries, card_map, context.commander_names)
        apply_context_tags(candidate_entries, card_map, commander_archetypes, context.commander_names)
        compiled: List[TaggedCandidate] = []
        for entry in candidate_entries:
            for child, parent in TAG_PARENT_RELATIONS.items():
                if child in entry.tags and parent not in entry.tags:
                    entry.tags.append(parent)
            entry.tags = sorted(set(entry.tags))
            card = card_map[entry.name]
            roles = self._candidate_roles(card, entry)
            packages = self._candidate_packages(card, entry, context)
            provides, needs = self._candidate_support_axes(card, entry, context)
            coverage = self._candidate_coverage(card, entry, context, roles, packages, provides)
            compiled.append(
                TaggedCandidate(
                    card=card,
                    entry=entry,
                    matched_queries=set(card.get("matched_queries") or []),
                    roles=roles,
                    packages=packages,
                    provides=provides,
                    needs=needs,
                    coverage=coverage,
                    effect_family=self._effect_family(card, entry, context),
                    base_score=self._candidate_synergy_score(card, entry, context),
                    popularity_rank=_as_int(card.get("edhrec_rank")),
                )
            )
        return compiled

    def _coverage_counts(self, selected: Sequence[TaggedCandidate]) -> Counter:
        counts: Counter = Counter()
        for candidate in selected:
            for key, value in candidate.coverage.items():
                counts[key] += value
        return counts

    def _package_counts(self, selected: Sequence[TaggedCandidate]) -> Counter:
        counts: Counter = Counter()
        for candidate in selected:
            for package in candidate.packages:
                counts[package] += 1
        return counts

    def _support_counts(self, selected: Sequence[TaggedCandidate]) -> Counter:
        counts: Counter = Counter()
        for candidate in selected:
            for axis in candidate.provides:
                counts[axis] += 1
        return counts

    def _family_counts(self, selected: Sequence[TaggedCandidate]) -> Counter:
        return Counter(candidate.effect_family for candidate in selected)

    def _package_axis_targets(self, package: str, *, secondary: bool = False) -> Dict[str, int]:
        required_axes = {
            axis: max(1, int(target))
            for axis, target in PACKAGE_LIBRARY.get(package, {}).get("required_axes", {}).items()
            if target
        }
        if not secondary:
            return required_axes
        return {
            axis: max(1, int(round(target * 0.65)))
            for axis, target in required_axes.items()
        }

    def _package_completion_state(
        self,
        selected: Sequence[TaggedCandidate],
        package: str,
        *,
        secondary: bool = False,
    ) -> tuple[float, str | None, Dict[str, Dict[str, float]]]:
        targets = self._package_axis_targets(package, secondary=secondary)
        if not targets:
            return 1.0, None, {}
        support_counts = self._support_counts(selected)
        axis_state: Dict[str, Dict[str, float]] = {}
        weakest_axis: str | None = None
        weakest_ratio = 999.0
        weakest_target = 0
        weakest_current = 0
        for axis, target in targets.items():
            current = support_counts.get(axis, 0)
            ratio = current / max(target, 1)
            axis_state[axis] = {
                "current": float(current),
                "target": float(target),
                "ratio": ratio,
            }
            if (
                weakest_axis is None
                or ratio < weakest_ratio
                or (ratio == weakest_ratio and target - current > weakest_target - weakest_current)
            ):
                weakest_axis = axis
                weakest_ratio = ratio
                weakest_target = target
                weakest_current = current
        completion = min(item["ratio"] for item in axis_state.values()) if axis_state else 1.0
        return completion, weakest_axis, axis_state

    def _package_completion_snapshot(self, context: DeckContext, selected: Sequence[TaggedCandidate]) -> Dict[str, Any]:
        primary_completion, primary_weakest, primary_axes = self._package_completion_state(
            selected,
            context.plan.primary_package,
            secondary=False,
        )
        secondary_rows: Dict[str, Any] = {}
        for package in context.plan.secondary_packages:
            completion, weakest_axis, axis_state = self._package_completion_state(
                selected,
                package,
                secondary=True,
            )
            secondary_rows[package] = {
                "completion": round(completion, 3),
                "weakest_axis": weakest_axis,
                "axes": axis_state,
            }
        return {
            "primary": {
                "package": context.plan.primary_package,
                "completion": round(primary_completion, 3),
                "weakest_axis": primary_weakest,
                "axes": primary_axes,
            },
            "secondary": secondary_rows,
        }

    def _staple_penalty(self, candidate: TaggedCandidate, context: DeckContext, package_counts: Counter, support_counts: Counter) -> float:
        popularity_pct = candidate.card.get("popularity_pct")
        if popularity_pct is None:
            rank = candidate.popularity_rank
            if not rank:
                return 0.0
            popularity_pct = max(0.0, min(1.0, 1.0 - ((rank - 1) / 5000)))
        if popularity_pct <= 0:
            return 0.0
        plan_critical = (
            context.plan.primary_package in candidate.packages
            or bool(set(context.plan.secondary_packages) & candidate.packages)
            or "#CommanderSynergy" in candidate.entry.tags
            or any(support_counts.get(axis, 0) < target <= support_counts.get(axis, 0) + 1 for axis, target in context.plan.support_targets.items() if axis in candidate.provides)
        )
        if popularity_pct <= (0.82 if not plan_critical else 0.58):
            return 0.0
        base = ((popularity_pct - (0.82 if not plan_critical else 0.58)) / max(0.18, 1.0 - (0.82 if not plan_critical else 0.58))) * context.plan.novelty_weight * (1.9 if not plan_critical else 0.5)
        if context.bracket <= 2 and ("#FastMana" in candidate.entry.tags or "#Tutor" in candidate.entry.tags):
            base += 1.8
        if context.bracket <= 3 and "#Combo" in candidate.entry.tags and context.plan.primary_package not in {"spellslinger", "reanimator", "aristocrats"}:
            base += 0.8
        return base

    def _candidate_popularity_pct(self, candidate: TaggedCandidate) -> float:
        popularity_pct = candidate.card.get("popularity_pct")
        if popularity_pct is not None:
            try:
                return float(popularity_pct)
            except Exception:
                return 0.0
        rank = candidate.popularity_rank
        if not rank:
            return 0.0
        return max(0.0, min(1.0, 1.0 - ((rank - 1) / 5000)))

    def _is_generic_role_player(self, candidate: TaggedCandidate, context: DeckContext) -> bool:
        plan_critical = (
            context.plan.primary_package in candidate.packages
            or bool(set(context.plan.secondary_packages) & candidate.packages)
            or "#CommanderSynergy" in candidate.entry.tags
            or candidate.coverage.get("pkg:primary_enabler", 0.0) > 0
            or candidate.coverage.get("pkg:primary_payoff", 0.0) > 0
            or candidate.coverage.get("pkg:secondary_enabler", 0.0) > 0
            or candidate.coverage.get("pkg:secondary_payoff", 0.0) > 0
            or candidate.coverage.get("bridge", 0.0) > 0
        )
        return not plan_critical and any(_is_role_coverage_key(key) for key in candidate.coverage)

    def _selected_staple_count(self, selected: Sequence[TaggedCandidate], context: DeckContext) -> int:
        return sum(
            1
            for row in selected
            if self._candidate_popularity_pct(row) > 0.85 and self._is_generic_role_player(row, context)
        )

    def _candidate_pick_components(
        self,
        candidate: TaggedCandidate,
        context: DeckContext,
        selected: Sequence[TaggedCandidate],
        coverage: Counter,
        package_counts: Counter,
        support_counts: Counter,
        family_counts: Counter,
    ) -> Dict[str, float]:
        tags = set(candidate.entry.tags)
        mv = _mana_value(candidate.card)
        family_count = family_counts[candidate.effect_family]
        family_limit = EFFECT_FAMILY_LIMITS.get(candidate.effect_family, 99)
        popularity_pct = self._candidate_popularity_pct(candidate)
        generic_role_player = self._is_generic_role_player(candidate, context)
        selected_staples = self._selected_staple_count(selected, context)
        role_keys = {key for key, value in candidate.coverage.items() if _is_role_coverage_key(key) and value > 0}
        package_keys = {key for key, value in candidate.coverage.items() if _is_package_coverage_key(key) and value > 0}

        plan_fit = min(
            3.0,
            (1.4 if context.plan.primary_package in candidate.packages else 0.0)
            + min(1.0, len(set(context.plan.secondary_packages) & candidate.packages) * 0.5)
            + (0.8 if "#CommanderSynergy" in tags else 0.0)
            + (0.45 if context.plan.subtype_anchor and context.plan.subtype_anchor.lower() in _type_line(candidate.card) else 0.0)
            + min(0.65, max(0.0, candidate.base_score) / 6.0),
        )

        uncovered_need_score = 0.0
        for key, (floor, _ceiling) in context.plan.coverage_targets.items():
            deficit = max(0.0, float(floor) - float(coverage.get(key, 0.0)))
            contribution = candidate.coverage.get(key, 0.0)
            if deficit > 0 and contribution > 0:
                uncovered_need_score += min(contribution, deficit)
        for axis, target in context.plan.support_targets.items():
            deficit = max(0, int(target) - int(support_counts.get(axis, 0)))
            if deficit > 0 and axis in candidate.provides:
                uncovered_need_score += min(1.0, deficit / max(float(target), 1.0))
        uncovered_need_score = min(3.0, uncovered_need_score)

        bridge_bonus = 0.0
        if candidate.coverage.get("bridge", 0.0) > 0:
            bridge_bonus = min(1.5, candidate.coverage.get("bridge", 0.0) + (0.2 if role_keys and package_keys else 0.0))

        coverage_dimensions = sum(1 for value in candidate.coverage.values() if value > 0)
        role_compression_bonus = min(1.5, max(0, coverage_dimensions - 1) * 0.4)

        diversity_bonus = 0.0
        if family_count == 0:
            diversity_bonus += 1.0
        elif family_count < family_limit:
            diversity_bonus += max(0.0, 0.8 - (family_count / max(family_limit, 1)) * 0.4)
        if len(candidate.matched_queries) >= 2:
            diversity_bonus += 0.2
        diversity_bonus = min(1.3, diversity_bonus)

        novelty_bonus = min(1.4, max(0.0, 1.0 - popularity_pct) * context.plan.novelty_weight)

        staple_penalty = 0.0
        if generic_role_player and popularity_pct > 0.85:
            staple_penalty += 1.1 + (popularity_pct - 0.85) * 4.5
        if generic_role_player and popularity_pct > 0.95:
            staple_penalty += 1.8 + (popularity_pct - 0.95) * 8.0
        if selected_staples >= context.plan.staple_budget and generic_role_player and popularity_pct > 0.75:
            staple_penalty += 1.0 + max(0, selected_staples - context.plan.staple_budget) * 0.35

        dependency_penalty = 0.0
        for axis in candidate.needs:
            target = max(1, context.plan.support_targets.get(axis, 1))
            if support_counts.get(axis, 0) < target:
                dependency_penalty += 0.95 + max(0, target - support_counts.get(axis, 0)) * 0.25

        tension_penalty = 0.0
        if set(context.plan.avoid_tags) & tags:
            tension_penalty += 1.25 * len(set(context.plan.avoid_tags) & tags)
        off_plan = not (
            context.plan.primary_package in candidate.packages
            or bool(set(context.plan.secondary_packages) & candidate.packages)
            or candidate.coverage.get("bridge", 0.0) > 0
        )
        if off_plan and generic_role_player:
            tension_penalty += 0.65
        if candidate.effect_family == "boardwipe" and context.plan.primary_package in {"tokens", "combat", "voltron", "blink"}:
            tension_penalty += 0.85

        redundancy_penalty = 0.0
        if family_count >= family_limit:
            redundancy_penalty += 1.0 + (family_count - family_limit + 1) * 0.8
        saturated_keys = 0
        useful_keys = 0
        for key, contribution in candidate.coverage.items():
            if contribution <= 0:
                continue
            useful_keys += 1
            _floor, ceiling = context.plan.coverage_targets.get(key, (0.0, 99.0))
            if coverage.get(key, 0.0) >= ceiling:
                saturated_keys += 1
        if useful_keys and saturated_keys == useful_keys and not package_keys:
            redundancy_penalty += 0.9

        curve_penalty = 0.0
        high_curve = sum(1 for row in selected if _mana_value(row.card) >= 5)
        if context.plan.curve_target == "low":
            if mv >= 5:
                curve_penalty += 1.4 + max(0.0, mv - 5.0) * 0.25
            elif mv >= 4:
                curve_penalty += 0.55
        elif context.plan.curve_target == "mid":
            if mv >= 7:
                curve_penalty += 1.2 + (mv - 7.0) * 0.2
            elif mv >= 5 and high_curve >= 8:
                curve_penalty += 0.85
        else:
            if mv >= 8 and high_curve >= 10:
                curve_penalty += 0.75

        return {
            "plan_fit": plan_fit,
            "uncovered_need_score": uncovered_need_score,
            "bridge_bonus": bridge_bonus,
            "role_compression_bonus": role_compression_bonus,
            "diversity_bonus": diversity_bonus,
            "novelty_bonus": novelty_bonus,
            "staple_penalty": staple_penalty,
            "dependency_penalty": dependency_penalty,
            "tension_penalty": tension_penalty,
            "redundancy_penalty": redundancy_penalty,
            "curve_penalty": curve_penalty,
        }

    def _candidate_pick_score(
        self,
        candidate: TaggedCandidate,
        context: DeckContext,
        selected: Sequence[TaggedCandidate],
        coverage: Counter,
        package_counts: Counter,
        support_counts: Counter,
        family_counts: Counter,
    ) -> float:
        components = self._candidate_pick_components(
            candidate,
            context,
            selected,
            coverage,
            package_counts,
            support_counts,
            family_counts,
        )
        return (
            3.0 * components["plan_fit"]
            + 2.4 * components["uncovered_need_score"]
            + 1.6 * components["bridge_bonus"]
            + 1.2 * components["role_compression_bonus"]
            + 1.0 * components["diversity_bonus"]
            + 0.8 * components["novelty_bonus"]
            - components["staple_penalty"]
            - components["dependency_penalty"]
            - components["tension_penalty"]
            - components["redundancy_penalty"]
            - components["curve_penalty"]
        )

    def _candidate_package_core_score(
        self,
        candidate: TaggedCandidate,
        context: DeckContext,
        selected: Sequence[TaggedCandidate],
        package: str,
        weakest_axis: str | None,
        axis_targets: Dict[str, int],
        *,
        secondary: bool = False,
    ) -> float:
        coverage = self._coverage_counts(selected)
        package_counts = self._package_counts(selected)
        support_counts = self._support_counts(selected)
        family_counts = self._family_counts(selected)

        score = self._candidate_pick_score(
            candidate,
            context,
            selected,
            coverage,
            package_counts,
            support_counts,
            family_counts,
        )
        if package not in candidate.packages:
            score -= 2.0
        else:
            score += 2.4 if not secondary else 1.4
        if weakest_axis and weakest_axis in candidate.provides:
            deficit = max(0, axis_targets.get(weakest_axis, 0) - support_counts.get(weakest_axis, 0))
            score += 7.5 + deficit * 0.8
        elif weakest_axis:
            score -= 1.2
        for axis, target in axis_targets.items():
            if axis == weakest_axis:
                continue
            if axis in candidate.provides and support_counts.get(axis, 0) < target:
                score += 2.1 + (target - support_counts.get(axis, 0)) * 0.22
        if any(axis in candidate.needs and support_counts.get(axis, 0) < axis_targets.get(axis, 1) for axis in axis_targets):
            score -= 0.9
        return score

    def _pick_rank_band(self, ranked: Sequence[tuple[float, Any]], window: int = 6) -> Any | None:
        scored = [row for row in ranked if row[0] > -900]
        if not scored:
            return None
        scored = sorted(scored, key=lambda row: row[0], reverse=True)
        band = scored[: min(window, len(scored))]
        best = band[0][0]
        near = [row for row in band if row[0] >= best - 1.5]
        pool = near or band
        floor = min(row[0] for row in pool)
        weights = [max(0.1, row[0] - floor + 0.2) for row in pool]
        return self.rng.choices([row[1] for row in pool], weights=weights, k=1)[0]

    def _pick_candidate(
        self,
        candidates: Sequence[TaggedCandidate],
        selected_names: Set[str],
        context: DeckContext,
        selected: Sequence[TaggedCandidate],
        must_roles: Set[str] | None = None,
        must_package: str | None = None,
        must_support: str | None = None,
        must_coverage_key: str | None = None,
    ) -> TaggedCandidate | None:
        coverage = self._coverage_counts(selected)
        package_counts = self._package_counts(selected)
        support_counts = self._support_counts(selected)
        family_counts = self._family_counts(selected)

        ranked: List[tuple[float, TaggedCandidate]] = []
        for candidate in candidates:
            if candidate.entry.name in selected_names:
                continue
            if must_roles and not (must_roles & candidate.roles):
                continue
            if must_package and must_package not in candidate.packages:
                continue
            if must_support and must_support not in candidate.provides:
                continue
            if must_coverage_key and candidate.coverage.get(must_coverage_key, 0.0) <= 0:
                continue
            ranked.append(
                (
                    self._candidate_pick_score(candidate, context, selected, coverage, package_counts, support_counts, family_counts),
                    candidate,
                )
            )
        return self._pick_rank_band(ranked, window=8)

    def _pick_package_core_candidate(
        self,
        candidates: Sequence[TaggedCandidate],
        selected_names: Set[str],
        context: DeckContext,
        selected: Sequence[TaggedCandidate],
        package: str,
        *,
        secondary: bool = False,
    ) -> TaggedCandidate | None:
        axis_targets = self._package_axis_targets(package, secondary=secondary)
        _completion, weakest_axis, _axis_state = self._package_completion_state(
            selected,
            package,
            secondary=secondary,
        )
        ranked: List[tuple[float, TaggedCandidate]] = []
        for candidate in candidates:
            if candidate.entry.name in selected_names:
                continue
            if package not in candidate.packages:
                continue
            if weakest_axis and weakest_axis not in candidate.provides:
                if not any(
                    axis in candidate.provides and self._support_counts(selected).get(axis, 0) < target
                    for axis, target in axis_targets.items()
                ):
                    continue
            ranked.append(
                (
                    self._candidate_package_core_score(
                        candidate,
                        context,
                        selected,
                        package,
                        weakest_axis,
                        axis_targets,
                        secondary=secondary,
                    ),
                    candidate,
                )
            )
        return self._pick_rank_band(ranked, window=8)

    def _retention_score(self, candidate: TaggedCandidate, context: DeckContext, selected: Sequence[TaggedCandidate]) -> float:
        coverage = self._coverage_counts(selected)
        support_counts = self._support_counts(selected)
        score = candidate.base_score
        if context.plan.primary_package in candidate.packages:
            score += 5.0
        if set(context.plan.secondary_packages) & candidate.packages:
            score += 2.2
        for role, (floor, _) in context.plan.coverage_targets.items():
            if candidate.coverage.get(role, 0.0) > 0 and coverage[role] <= floor:
                score += 2.6 * candidate.coverage.get(role, 0.0)
        for axis, target in context.plan.support_targets.items():
            if axis in candidate.provides and support_counts[axis] <= target:
                score += 2.0
        if "#CommanderSynergy" in candidate.entry.tags:
            score += 1.8
        return score

    def _repair_deck(
        self,
        context: DeckContext,
        candidates: Sequence[TaggedCandidate],
        selected: List[TaggedCandidate],
        spell_target: int,
    ) -> List[TaggedCandidate]:
        selected_names = {row.entry.name for row in selected}
        coverage = self._coverage_counts(selected)
        support_counts = self._support_counts(selected)

        def try_swap(
            must_roles: Set[str] | None = None,
            must_support: str | None = None,
            must_package: str | None = None,
            must_coverage_key: str | None = None,
        ) -> bool:
            replacement = self._pick_candidate(
                candidates,
                selected_names,
                context,
                selected,
                must_roles=must_roles,
                must_package=must_package,
                must_support=must_support,
                must_coverage_key=must_coverage_key,
            )
            if replacement is None:
                return False
            removable = sorted(selected, key=lambda row: self._retention_score(row, context, selected))
            for current in removable:
                if context.plan.primary_package in current.packages and must_package != context.plan.primary_package:
                    continue
                if must_roles and (must_roles & current.roles):
                    continue
                if must_support and must_support in current.provides:
                    continue
                if must_coverage_key and current.coverage.get(must_coverage_key, 0.0) > 0:
                    continue
                selected.remove(current)
                selected.append(replacement)
                selected_names.remove(current.entry.name)
                selected_names.add(replacement.entry.name)
                return True
            return False

        for role, (floor, _) in context.plan.coverage_targets.items():
            while coverage[role] < floor:
                if len(selected) < spell_target:
                    pick = self._pick_candidate(candidates, selected_names, context, selected, must_coverage_key=role)
                    if pick is None:
                        break
                    selected.append(pick)
                    selected_names.add(pick.entry.name)
                elif not try_swap(must_coverage_key=role):
                    break
                coverage = self._coverage_counts(selected)

        for axis, target in context.plan.support_targets.items():
            while support_counts[axis] < target:
                if len(selected) < spell_target:
                    pick = self._pick_candidate(candidates, selected_names, context, selected, must_support=axis)
                    if pick is None:
                        break
                    selected.append(pick)
                    selected_names.add(pick.entry.name)
                elif not try_swap(must_support=axis):
                    break
                support_counts = self._support_counts(selected)

        def interaction_total() -> float:
            return coverage.get("role:interaction", 0.0)

        while interaction_total() < 10.0:
            if len(selected) < spell_target:
                pick = self._pick_candidate(candidates, selected_names, context, selected, must_coverage_key="role:interaction")
                if pick is None:
                    break
                selected.append(pick)
                selected_names.add(pick.entry.name)
            elif not try_swap(must_coverage_key="role:interaction"):
                break
            coverage = self._coverage_counts(selected)

        return selected[:spell_target]

    def _score_generated_deck(self, context: DeckContext, selected: Sequence[TaggedCandidate]) -> tuple[float, Dict[str, Any]]:
        coverage = self._coverage_counts(selected)
        package_counts = self._package_counts(selected)
        support_counts = self._support_counts(selected)
        family_counts = self._family_counts(selected)
        five_plus = sum(1 for row in selected if _mana_value(row.card) >= 5)
        package_completion = self._package_completion_snapshot(context, selected)
        shell_ratios = []
        shell_weights = []
        for key, (floor, _ceiling) in context.plan.coverage_targets.items():
            if floor <= 0:
                continue
            shell_ratios.append(min(1.0, float(coverage.get(key, 0.0)) / float(floor)))
            shell_weights.append(1.3 if key.startswith("role:") else 1.0)
        shell_score = (
            sum(ratio * weight for ratio, weight in zip(shell_ratios, shell_weights)) / max(sum(shell_weights), 1.0)
            if shell_ratios
            else 1.0
        )

        candidate_plan_terms = []
        bridge_count = 0
        for candidate in selected:
            term = 0.0
            if context.plan.primary_package in candidate.packages:
                term += 0.5
            if set(context.plan.secondary_packages) & candidate.packages:
                term += 0.2
            if "#CommanderSynergy" in candidate.entry.tags:
                term += 0.2
            if candidate.coverage.get("bridge", 0.0) > 0:
                bridge_count += 1
                term += 0.2
            candidate_plan_terms.append(min(1.0, term))
        cohesion_score = sum(candidate_plan_terms) / max(1, len(candidate_plan_terms))

        secondary_completion = [
            row.get("completion", 0.0)
            for row in package_completion.get("secondary", {}).values()
        ]
        package_completion_score = (
            package_completion["primary"]["completion"] * 0.72
            + (sum(secondary_completion) / max(1, len(secondary_completion))) * 0.28
            if secondary_completion
            else package_completion["primary"]["completion"]
        )

        over_limit_families = 0.0
        for family, count in family_counts.items():
            limit = EFFECT_FAMILY_LIMITS.get(family, 99)
            if count > limit:
                over_limit_families += count - limit
        family_variety = min(1.0, len(family_counts) / 11.0)
        diversity_score = max(0.0, min(1.0, family_variety - over_limit_families * 0.04 + min(bridge_count, 6) * 0.03))

        popularity_values = [self._candidate_popularity_pct(candidate) for candidate in selected]
        novelty_score = (
            sum(max(0.0, 1.0 - pct) for pct in popularity_values) / max(1, len(popularity_values))
            if popularity_values
            else 0.6
        )

        unsupported_dependency_score = 0.0
        for axis, target in context.plan.support_targets.items():
            if support_counts.get(axis, 0) < target:
                unsupported_dependency_score += (target - support_counts.get(axis, 0)) * 0.8
        for candidate in selected:
            for axis in candidate.needs:
                if support_counts.get(axis, 0) < max(1, context.plan.support_targets.get(axis, 1)):
                    unsupported_dependency_score += 0.35

        tension_score = 0.0
        for candidate in selected:
            candidate_tags = set(candidate.entry.tags)
            if set(context.plan.avoid_tags) & candidate_tags:
                tension_score += 0.4 * len(set(context.plan.avoid_tags) & candidate_tags)
            off_plan = not (
                context.plan.primary_package in candidate.packages
                or bool(set(context.plan.secondary_packages) & candidate.packages)
                or candidate.coverage.get("bridge", 0.0) > 0
            )
            if off_plan and self._is_generic_role_player(candidate, context):
                tension_score += 0.2

        selected_staples = self._selected_staple_count(selected, context)
        staple_overload_penalty = max(0, selected_staples - context.plan.staple_budget) * 1.2
        staple_overload_penalty += sum(
            0.45
            for candidate in selected
            if self._candidate_popularity_pct(candidate) > 0.95 and self._is_generic_role_player(candidate, context)
        )

        deck_score = (
            4.0 * shell_score
            + 3.0 * cohesion_score
            + 2.5 * package_completion_score
            + 1.5 * diversity_score
            + 1.0 * novelty_score
            - unsupported_dependency_score
            - tension_score
            - staple_overload_penalty
        )
        metrics = {
            "primary_package": context.plan.primary_package,
            "secondary_packages": list(context.plan.secondary_packages),
            "plan_confidence": context.plan.confidence,
            "package_completion": package_completion,
            "needs": list(context.plan.needs),
            "avoid_tags": list(context.plan.avoid_tags),
            "protection_target": context.plan.protection_target,
            "land_count": context.plan.land_count,
            "curve_target": context.plan.curve_target,
            "coverage": {key: round(value, 2) for key, value in coverage.items()},
            "package_counts": dict(package_counts),
            "support_counts": dict(support_counts),
            "shell_score": round(shell_score, 3),
            "cohesion_score": round(cohesion_score, 3),
            "package_completion_score": round(package_completion_score, 3),
            "diversity_score": round(diversity_score, 3),
            "novelty_score": round(novelty_score, 3),
            "unsupported_dependency_score": round(unsupported_dependency_score, 3),
            "tension_score": round(tension_score, 3),
            "staple_overload_penalty": round(staple_overload_penalty, 3),
            "generic_staples": selected_staples,
            "five_plus_spells": five_plus,
            "bridge_count": bridge_count,
            "deck_score": round(deck_score, 3),
        }
        return deck_score, metrics

    def _draft_candidate_deck(self, context: DeckContext, candidates: Sequence[TaggedCandidate]) -> GeneratedDeck:
        spell_target = 100 - context.plan.land_count - len(context.commander_names)
        selected: List[TaggedCandidate] = []
        selected_names: Set[str] = set()

        def add_candidate(candidate: TaggedCandidate | None):
            if candidate is None:
                return
            if candidate.entry.name in selected_names:
                return
            if len(selected) >= spell_target:
                return
            selected.append(candidate)
            selected_names.add(candidate.entry.name)

        primary_target = PACKAGE_LIBRARY.get(context.plan.primary_package, {}).get("core_target", 12)
        while len(selected) < spell_target:
            completion, _weakest_axis, _axis_state = self._package_completion_state(
                selected,
                context.plan.primary_package,
                secondary=False,
            )
            if completion >= 1.0 and sum(1 for row in selected if context.plan.primary_package in row.packages) >= max(4, int(primary_target * 0.55)):
                break
            pick = self._pick_package_core_candidate(
                candidates,
                selected_names,
                context,
                selected,
                context.plan.primary_package,
                secondary=False,
            )
            if pick is None:
                pick = self._pick_candidate(candidates, selected_names, context, selected, must_package=context.plan.primary_package)
            if pick is None:
                break
            add_candidate(pick)

        for package in context.plan.secondary_packages:
            secondary_target = PACKAGE_LIBRARY.get(package, {}).get("secondary_target", 6)
            secondary_floor = max(2, int(round(secondary_target * 0.65)))
            while len(selected) < spell_target:
                completion, _weakest_axis, _axis_state = self._package_completion_state(
                    selected,
                    package,
                    secondary=True,
                )
                if completion >= 1.0 and sum(1 for row in selected if package in row.packages) >= secondary_floor:
                    break
                pick = self._pick_package_core_candidate(
                    candidates,
                    selected_names,
                    context,
                    selected,
                    package,
                    secondary=True,
                )
                if pick is None:
                    pick = self._pick_candidate(candidates, selected_names, context, selected, must_package=package)
                if pick is None:
                    break
                add_candidate(pick)

        for role, (floor, _) in context.plan.coverage_targets.items():
            while self._coverage_counts(selected)[role] < floor and len(selected) < spell_target:
                pick = self._pick_candidate(candidates, selected_names, context, selected, must_coverage_key=role)
                if pick is None:
                    break
                add_candidate(pick)

        for axis, target in context.plan.support_targets.items():
            while self._support_counts(selected)[axis] < target and len(selected) < spell_target:
                pick = self._pick_candidate(candidates, selected_names, context, selected, must_support=axis)
                if pick is None:
                    break
                add_candidate(pick)

        while len(selected) < spell_target:
            pick = self._pick_candidate(candidates, selected_names, context, selected)
            if pick is None:
                break
            add_candidate(pick)

        selected = self._repair_deck(context, candidates, selected, spell_target)
        score, metrics = self._score_generated_deck(context, selected)
        interaction_count = sum(1 for row in selected if "interaction" in row.roles)
        commander_entries = [CardEntry(qty=1, name=name, section="commander") for name in context.commander_names]
        land_entries = self._build_mana_base(context, [row.card for row in selected])
        cards = [*commander_entries, *land_entries, *[row.entry for row in selected[:spell_target]]]
        return GeneratedDeck(cards=cards, selected=list(selected[:spell_target]), interaction_count=interaction_count, score=score, metrics=metrics)

    def _generate_candidate_decks(
        self,
        context: DeckContext,
        candidates: Sequence[TaggedCandidate],
        *,
        count: int = 24,
    ) -> List[GeneratedDeck]:
        drafted: List[GeneratedDeck] = []
        seen_signatures: Set[tuple[str, ...]] = set()
        for _idx in range(count):
            draft_seed = self.rng.randrange(1, 2**31 - 1)
            draft_service = RandomDeckService(random.Random(draft_seed), self.card_service)
            generated = draft_service._draft_candidate_deck(context, candidates)
            generated.draft_seed = draft_seed
            signature = tuple(sorted(entry.name for entry in generated.cards if entry.section == "deck"))
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            drafted.append(generated)
        drafted.sort(key=lambda row: row.score, reverse=True)
        return drafted

    def _select_final_deck(self, drafted: Sequence[GeneratedDeck]) -> GeneratedDeck | None:
        if not drafted:
            return None
        ranked = sorted(drafted, key=lambda row: row.score, reverse=True)
        best = ranked[0].score
        top_group = [row for row in ranked if row.score >= best - 0.5][:4]
        pool = top_group or ranked[:1]
        temperature = 0.33
        weights = [math.exp((row.score - best) / max(temperature, 0.05)) for row in pool]
        return self.rng.choices(pool, weights=weights, k=1)[0]

    def _nonbasic_land_names(self, colors: Sequence[str]) -> List[str]:
        if not colors:
            return COLORLESS_NONBASIC_LANDS[:8]
        return GENERIC_NONBASIC_LANDS[:8]

    def _basic_land_entries(self, colors: Sequence[str], selected_nonlands: Sequence[Dict], commander_cards: Sequence[Dict], total_basics: int) -> List[CardEntry]:
        if total_basics <= 0:
            return []
        if not colors:
            return [CardEntry(qty=total_basics, name="Wastes", section="deck")]

        pip_counts = _count_pips(selected_nonlands, commander_cards, colors)
        total_weight = sum(max(1, pip_counts[color]) for color in colors)
        allocations = {color: max(1, round(total_basics * max(1, pip_counts[color]) / total_weight)) for color in colors}
        current_total = sum(allocations.values())
        order = sorted(colors, key=lambda color: pip_counts[color], reverse=True)
        while current_total > total_basics:
            for color in order:
                if allocations[color] > 1 and current_total > total_basics:
                    allocations[color] -= 1
                    current_total -= 1
        while current_total < total_basics:
            for color in order:
                if current_total < total_basics:
                    allocations[color] += 1
                    current_total += 1
        return [CardEntry(qty=allocations[color], name=COLOR_TO_BASIC[color], section="deck") for color in colors if allocations[color] > 0]

    def _build_mana_base(self, context: DeckContext, selected_nonlands: Sequence[Dict]) -> List[CardEntry]:
        commander_map = {name: card for name, card in zip(context.commander_names, context.commander_cards)}
        commander_colors = combined_color_identity(commander_map, context.commander_names)
        nonbasic_names = self._nonbasic_land_names(commander_colors)
        nonbasic_land_entries = [CardEntry(qty=1, name=name, section="deck") for name in nonbasic_names[: context.plan.land_count]]
        basic_land_entries = self._basic_land_entries(
            commander_colors,
            selected_nonlands,
            context.commander_cards,
            total_basics=context.plan.land_count - len(nonbasic_land_entries),
        )
        return [*nonbasic_land_entries, *basic_land_entries]

    def _to_decklist_text(self, cards: Sequence[CardEntry]) -> str:
        commander_lines = [f"{entry.qty} {entry.name}" for entry in cards if entry.section == "commander"]
        deck_entries = [entry for entry in cards if entry.section == "deck"]

        def sort_key(entry: CardEntry) -> tuple[int, str]:
            if entry.name in COLOR_TO_BASIC.values() or entry.name == "Wastes":
                return (0, entry.name)
            return (1, entry.name)

        deck_lines = [f"{entry.qty} {entry.name}" for entry in sorted(deck_entries, key=sort_key)]
        return "Commander\n" + "\n".join(commander_lines) + "\nDeck\n" + "\n".join(deck_lines)

    def _warnings_for_deck(self, context: DeckContext, generated: GeneratedDeck, validator_warnings: Sequence[str]) -> List[str]:
        warnings = list(validator_warnings)
        package_line = _package_label(context.plan.primary_package, context.plan.subtype_anchor)
        secondary_line = ", ".join(_package_label(package, context.plan.subtype_anchor if package == "typal" else None) for package in context.plan.secondary_packages)
        warnings.append(
            f"Generated around {package_line}"
            + (f" with {secondary_line} support." if secondary_line else ".")
        )
        warnings.append(
            f"Plan confidence: {round(context.plan.confidence * 100)}%. Targets {context.plan.land_count} lands, {context.plan.protection_target} protection pieces, and a {context.plan.curve_target} curve."
        )
        coverage = generated.metrics.get("coverage", {})
        warnings.append(
            f"Coverage shell: {coverage.get('role:ramp', 0)} ramp, {coverage.get('role:draw', 0)} draw, {coverage.get('role:interaction', 0)} interaction, {coverage.get('bridge', 0)} bridge."
        )
        warnings.append(
            f"Deck score {generated.metrics.get('deck_score', round(generated.score, 2))} from shell {generated.metrics.get('shell_score', 0)}, cohesion {generated.metrics.get('cohesion_score', 0)}, and package completion {generated.metrics.get('package_completion_score', 0)}."
        )
        return warnings

    def generate(self, bracket: int = 3) -> Dict[str, object]:
        last_errors: List[str] = []
        for _ in range(8):
            commander_card = self._random_commander()
            secondary = self._secondary_commander(commander_card)
            commander_cards = [commander_card, secondary] if secondary else [commander_card]
            context = self._build_context(commander_cards, bracket)
            if context.plan.confidence < 0.34 and not context.plan.subtype_anchor:
                last_errors = [f"Commander plan confidence was too low for {commander_display_name(context.commander_names)}."]
                continue
            pool_map = self._fetch_candidate_pool(context)
            candidates = self._tag_candidate_pool(context, pool_map)
            if not candidates:
                last_errors = [f"Could not fetch candidate pool for {_safe_name(commander_card.get('name')) or 'selected commander'}."]
                continue

            drafted = self._generate_candidate_decks(context, candidates, count=24)
            generated = self._select_final_deck(drafted)
            if generated is None:
                last_errors = [f"Could not draft a candidate deck for {commander_display_name(context.commander_names)}."]
                continue

            names = [entry.name for entry in generated.cards]
            fetched_map = self.card_service.get_cards_by_name(names)
            card_map = {**{name: card for name, card in zip(context.commander_names, context.commander_cards)}, **fetched_map}
            errors, validator_warnings, _ = validate_deck(generated.cards, commander_display_name(context.commander_names), card_map, bracket)
            if errors:
                last_errors = errors
                continue
            if generated.interaction_count < 10:
                last_errors = [f"Could not satisfy cheap interaction floor for {commander_display_name(context.commander_names)}."]
                continue
            return {
                "decklist_text": self._to_decklist_text(generated.cards),
                "commander": commander_display_name(context.commander_names) or context.commander_names[0],
                "commanders": context.commander_names,
                "color_identity": combined_color_identity(card_map, context.commander_names),
                "interaction_count": generated.interaction_count,
                "warnings": self._warnings_for_deck(context, generated, validator_warnings),
                "generator_metrics": {
                    "candidate_count": len(drafted),
                    "selected_seed": generated.draft_seed,
                    "selected_metrics": generated.metrics,
                    "top_group_scores": [round(deck.score, 3) for deck in drafted[:6]],
                },
            }
        raise RuntimeError(last_errors[0] if last_errors else "Could not generate a legal random deck.")
