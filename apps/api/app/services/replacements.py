from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence, Set, Tuple

from app.schemas.deck import CardEntry
from app.services.commander_utils import combined_color_identity, commander_names_from_cards
from app.services.scryfall import CardDataService, QuerySpec
from app.services.tagger import compute_type_theme_profile

PROFILE_SCHEMA_VERSION = 1

MainType = Literal["artifact", "battle", "creature", "enchantment", "instant", "land", "planeswalker", "sorcery"]
ThemeMode = Literal["member", "payoff", "producer", "recursion", "tutor"]
AxisVerdict = Literal["better", "equal", "worse", "unknown"]
ReplacementFamily = Literal[
    "boardwipe",
    "counterspell",
    "draw",
    "engine",
    "mana-dork",
    "mana-land",
    "mana-rock",
    "protection",
    "recursion",
    "ritual",
    "spot-removal",
    "tutor",
    "unsupported",
]

MAIN_TYPES: Tuple[MainType, ...] = ("artifact", "battle", "creature", "enchantment", "instant", "land", "planeswalker", "sorcery")
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
ROLE_TO_THEME_COUNTS = {
    "#Artifacts": ("package:artifacts", 6),
    "#Enchantments": ("package:enchantments", 6),
}
THEME_TAG_TO_KEY = {
    "#EquipmentPackage": "package:equipment",
    "#AuraPackage": "package:aura",
    "#ShrinePackage": "package:shrine",
    "#BackgroundPackage": "package:background",
}
MAPPABLE_DECK_TAGS = set(FUNCTIONAL_ROLES) | set(ROLE_TO_THEME_COUNTS) | set(THEME_TAG_TO_KEY)
NUMBER_WORDS = {
    "a": 1,
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
}


@dataclass(frozen=True)
class ThemeParticipation:
    theme_key: str
    mode: ThemeMode
    evidence: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ManaCostProfile:
    mana_value: Optional[float]
    pip_counts: Dict[str, int]
    distinct_colors_required: int
    has_x: bool
    has_hybrid: bool
    has_phyrexian: bool
    has_alt_cost: bool


@dataclass(frozen=True)
class DeckContext:
    commander_names: Tuple[str, ...]
    commander_color_identity: Set[str]
    deck_names: Set[str]
    active_theme_keys: Set[str]
    active_theme_strengths: Dict[str, float]
    cached_in_deck_profiles: Dict[str, "CardProfile"] = field(default_factory=dict)
    theme_profile_version: str = "type-theme:v1"
    theme_profile_source: str = "compute_type_theme_profile"
    type_profile: Dict[str, Any]


@dataclass(frozen=True)
class CardProfile:
    schema_version: int
    name: str
    oracle_id: str
    main_types: Tuple[MainType, ...]
    subtypes: Tuple[str, ...]
    color_identity: Set[str]
    mana_cost: ManaCostProfile
    normalized_roles: Set[str]
    replacement_family: ReplacementFamily
    comparison_class: Optional[str]
    comparison_data: Dict[str, Any]
    theme_participation: Tuple[ThemeParticipation, ...]
    comparable_utility_roles: Tuple[str, ...]
    strict_comparable: bool
    unsupported_reasons: Tuple[str, ...] = ()
    evidence: Dict[str, List[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class ReplacementContract:
    selected_profile: CardProfile
    exact_main_types: Tuple[MainType, ...]
    replacement_family: ReplacementFamily
    comparison_class: str
    selected_comparison_data: Dict[str, Any]
    required_roles: Set[str]
    required_theme_obligations: Tuple[ThemeParticipation, ...]
    budget_cap_usd: Optional[float]
    commander_color_identity: Set[str]
    exclude_names: Set[str]


@dataclass(frozen=True)
class CandidateQuerySpec:
    exact_main_types: Tuple[MainType, ...]
    replacement_family: ReplacementFamily
    comparison_class: str
    commander_color_identity: Set[str]
    exclude_names: Set[str]
    budget_cap_usd: Optional[float]
    theme_hints: Tuple[str, ...]
    scryfall_specs: Tuple[QuerySpec, ...]


@dataclass(frozen=True)
class AxisResult:
    axis: str
    status: AxisVerdict
    reason: str
    delta: float = 0.0


@dataclass(frozen=True)
class CandidateDecision:
    accepted: bool
    reasons: Tuple[str, ...]
    role_overlap: Tuple[str, ...]
    better_axes: Tuple[str, ...]
    ranking_key: Tuple[Any, ...]


def _to_float(value: Any) -> Optional[float]:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _card_text(card: Dict[str, Any]) -> str:
    return f"{card.get('type_line', '')}\n{card.get('oracle_text', '')}".strip().lower()


def _split_type_line(type_line: str) -> Tuple[Tuple[MainType, ...], Tuple[str, ...]]:
    left, _, right = str(type_line or "").partition(" — ")
    left_tokens = [token for token in re.split(r"\s+", left.lower().strip()) if token]
    right_tokens = [token for token in re.split(r"\s+", right.lower().strip()) if token]
    main_types = tuple(sorted(token for token in left_tokens if token in MAIN_TYPES))  # type: ignore[assignment]
    subtypes = tuple(sorted(token for token in right_tokens))
    return main_types, subtypes


def _collapsed_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _theme_key_from_tag(tag: str) -> Optional[str]:
    if tag in THEME_TAG_TO_KEY:
        return THEME_TAG_TO_KEY[tag]
    if tag.startswith("#") and tag.endswith("Typal") and len(tag) > len("#Typal"):
        return f"typal:{_collapsed_text(tag[1:-5])}"
    return None


def _active_themes(cards: Sequence[CardEntry], type_profile: Dict[str, Any]) -> Tuple[Set[str], Dict[str, float]]:
    active: Set[str] = set()
    strengths: Dict[str, float] = {}
    for tag in type_profile.get("deck_theme_tags") or []:
        key = _theme_key_from_tag(str(tag))
        if key:
            active.add(key)
            strengths[key] = max(strengths.get(key, 0.0), 1.0)

    dominant = type_profile.get("dominant_creature_subtype") or {}
    if isinstance(dominant, dict) and dominant.get("name"):
        dominant_key = f"typal:{_collapsed_text(str(dominant.get('name')))}"
        share = _to_float(dominant.get("share")) or 0.0
        count = float(dominant.get("count") or 0.0)
        if dominant_key in active:
            strengths[dominant_key] = max(strengths.get(dominant_key, 0.0), min(1.0, max(share, count / 10.0)))

    tag_counts: Counter[str] = Counter()
    for entry in cards:
        if entry.section not in {"deck", "commander"}:
            continue
        for tag in entry.tags:
            if tag in ROLE_TO_THEME_COUNTS:
                tag_counts[tag] += max(1, int(entry.qty or 1))

    for tag, (theme_key, threshold) in ROLE_TO_THEME_COUNTS.items():
        if tag_counts.get(tag, 0) >= threshold:
            active.add(theme_key)
            strengths[theme_key] = max(strengths.get(theme_key, 0.0), min(1.0, tag_counts[tag] / max(float(threshold), 1.0)))

    return active, strengths


def _normalize_color_identity(card: Dict[str, Any]) -> Set[str]:
    return {str(x).upper() for x in (card.get("color_identity") or []) if isinstance(x, str)}


def _mana_cost_profile(card: Dict[str, Any]) -> ManaCostProfile:
    mana_cost = str(card.get("mana_cost") or "")
    pips: Counter[str] = Counter()
    has_hybrid = False
    has_phyrexian = False
    has_x = False
    tokens = re.findall(r"\{([^}]+)\}", mana_cost)
    for token in tokens:
        token_upper = token.upper()
        if token_upper == "X":
            has_x = True
        if "/" in token_upper:
            has_hybrid = True
            if "P" in token_upper:
                has_phyrexian = True
        for color in ("W", "U", "B", "R", "G"):
            if color in token_upper:
                pips[color] += 1
    has_alt_cost = bool(
        re.search(
            r"\b(foretell|flashback|overload|madness|miracle|escape|evoke|prototype|adventure|alternate cost|without paying its mana cost)\b",
            _card_text(card),
        )
    )
    return ManaCostProfile(
        mana_value=_to_float(card.get("mana_value") if card.get("mana_value") is not None else card.get("cmc")),
        pip_counts=dict(pips),
        distinct_colors_required=len([color for color, count in pips.items() if count > 0]),
        has_x=has_x,
        has_hybrid=has_hybrid,
        has_phyrexian=has_phyrexian,
        has_alt_cost=has_alt_cost,
    )


def _candidate_roles(card: Dict[str, Any]) -> Set[str]:
    txt = _card_text(card)
    roles: Set[str] = set()
    if "add {" in txt or "add one mana" in txt or "add two mana" in txt or "add three mana" in txt:
        roles.add("#Ramp")
        if "any color" in txt or "chosen color" in txt:
            roles.add("#Fixing")
    if "draw " in txt:
        roles.add("#Draw")
    if "search your library" in txt:
        roles.add("#Tutor")
    if "destroy target" in txt or "exile target" in txt:
        roles.add("#Removal")
        roles.add("#SpotRemoval")
    if "counter target" in txt:
        roles.add("#Counter")
        roles.add("#StackInteraction")
    if "destroy all" in txt or "exile all" in txt:
        roles.add("#Boardwipe")
        roles.add("#MassRemoval")
    if "return target" in txt and "graveyard" in txt:
        roles.add("#Recursion")
    if "whenever" in txt or "at the beginning of" in txt:
        roles.add("#Engine")
    if "you win the game" in txt or "each opponent loses" in txt:
        roles.add("#Wincon")
    return roles


def _normalized_roles(card: Dict[str, Any], entry: CardEntry | None = None) -> Set[str]:
    roles = _candidate_roles(card)
    if entry is not None:
        roles |= {tag for tag in entry.tags if tag in FUNCTIONAL_ROLES}
    return roles


def _comparable_utility_roles(normalized_roles: Set[str], replacement_family: ReplacementFamily) -> Tuple[str, ...]:
    family_roles = {
        "mana-rock": {"#Ramp", "#Fixing"},
        "mana-land": {"#Ramp", "#Fixing"},
        "mana-dork": {"#Ramp", "#Fixing"},
        "ritual": {"#Ramp"},
        "counterspell": {"#Counter", "#StackInteraction"},
        "spot-removal": {"#Removal", "#SpotRemoval"},
        "draw": {"#Draw"},
        "tutor": {"#Tutor"},
        "recursion": {"#Recursion"},
        "protection": {"#Protection"},
        "boardwipe": {"#Boardwipe", "#MassRemoval"},
        "engine": {"#Engine"},
        "unsupported": set(),
    }
    return tuple(sorted(normalized_roles & family_roles.get(replacement_family, set())))


def _has_changeling(text: str) -> bool:
    return "changeling" in text or "is every creature type" in text


def _token_mentions_theme(text: str, theme_key: str) -> bool:
    if theme_key.startswith("typal:"):
        needle = theme_key.split(":", 1)[1]
        return needle in _collapsed_text(text)
    if theme_key == "package:equipment":
        return "equipment token" in text
    if theme_key == "package:aura":
        return "aura token" in text
    if theme_key == "package:shrine":
        return "shrine token" in text
    if theme_key == "package:background":
        return "background token" in text
    return False


def _meaningfully_covers_theme_domain(theme_key: str, text: str, main_types: Tuple[MainType, ...]) -> bool:
    if theme_key.startswith("typal:"):
        needle = theme_key.split(":", 1)[1]
        return needle in _collapsed_text(text) or ("creature" in text and "search your library" in text)
    if theme_key == "package:equipment":
        return "equipment" in text or ("artifact" in text and "search your library" in text)
    if theme_key in {"package:aura", "package:shrine", "package:background"}:
        if theme_key.split(":", 1)[1] in text:
            return True
        return "enchantment" in text and "search your library" in text
    if theme_key == "package:artifacts":
        return "artifact" in text
    if theme_key == "package:enchantments":
        return "enchantment" in text
    return False


def _oracle_theme_mode(theme_key: str, text: str, main_types: Tuple[MainType, ...], subtypes: Tuple[str, ...]) -> Optional[ThemeMode]:
    collapsed_subtypes = {_collapsed_text(token) for token in subtypes}
    if theme_key.startswith("typal:"):
        subtype_key = theme_key.split(":", 1)[1]
        if subtype_key in collapsed_subtypes or _has_changeling(text):
            return "member"
        if subtype_key and re.search(r"search your library", text) and _meaningfully_covers_theme_domain(theme_key, text, main_types):
            return "tutor"
        if subtype_key and "graveyard" in text and "return" in text and _meaningfully_covers_theme_domain(theme_key, text, main_types):
            return "recursion"
        if subtype_key and "create" in text and "token" in text and _token_mentions_theme(text, theme_key):
            return "producer"
        if subtype_key and subtype_key in _collapsed_text(text):
            return "payoff"
        return None

    if theme_key == "package:equipment":
        if "equipment" in collapsed_subtypes:
            return "member"
        if "search your library" in text and _meaningfully_covers_theme_domain(theme_key, text, main_types):
            return "tutor"
        if "graveyard" in text and "return" in text and _meaningfully_covers_theme_domain(theme_key, text, main_types):
            return "recursion"
        if "create" in text and _token_mentions_theme(text, theme_key):
            return "producer"
        if "equipment" in text or "equipped creature" in text:
            return "payoff"
        return None

    if theme_key == "package:aura":
        if "aura" in collapsed_subtypes:
            return "member"
        if "search your library" in text and _meaningfully_covers_theme_domain(theme_key, text, main_types):
            return "tutor"
        if "graveyard" in text and "return" in text and _meaningfully_covers_theme_domain(theme_key, text, main_types):
            return "recursion"
        if "create" in text and _token_mentions_theme(text, theme_key):
            return "producer"
        if "aura" in text or "enchanted creature" in text:
            return "payoff"
        return None

    if theme_key == "package:shrine":
        if "shrine" in collapsed_subtypes:
            return "member"
        if "search your library" in text and _meaningfully_covers_theme_domain(theme_key, text, main_types):
            return "tutor"
        if "graveyard" in text and "return" in text and _meaningfully_covers_theme_domain(theme_key, text, main_types):
            return "recursion"
        if "create" in text and _token_mentions_theme(text, theme_key):
            return "producer"
        if "shrine" in text:
            return "payoff"
        return None

    if theme_key == "package:background":
        if "background" in collapsed_subtypes:
            return "member"
        if "search your library" in text and _meaningfully_covers_theme_domain(theme_key, text, main_types):
            return "tutor"
        if "graveyard" in text and "return" in text and _meaningfully_covers_theme_domain(theme_key, text, main_types):
            return "recursion"
        if "background" in text:
            return "payoff"
        return None

    if theme_key == "package:artifacts":
        if "artifact" in main_types:
            return "member"
        if "search your library" in text and _meaningfully_covers_theme_domain(theme_key, text, main_types):
            return "tutor"
        if "graveyard" in text and "return" in text and _meaningfully_covers_theme_domain(theme_key, text, main_types):
            return "recursion"
        if "create" in text and _token_mentions_theme(text, theme_key):
            return "producer"
        if "artifact" in text:
            return "payoff"
        return None

    if theme_key == "package:enchantments":
        if "enchantment" in main_types:
            return "member"
        if "search your library" in text and _meaningfully_covers_theme_domain(theme_key, text, main_types):
            return "tutor"
        if "graveyard" in text and "return" in text and _meaningfully_covers_theme_domain(theme_key, text, main_types):
            return "recursion"
        if "create" in text and _token_mentions_theme(text, theme_key):
            return "producer"
        if "enchantment" in text:
            return "payoff"
        return None
    return None


def _theme_participation(card: Dict[str, Any], deck_context: DeckContext) -> Tuple[ThemeParticipation, ...]:
    text = _card_text(card)
    main_types, subtypes = _split_type_line(str(card.get("type_line") or ""))
    parts: List[ThemeParticipation] = []

    def add(theme_key: str, mode: ThemeMode, evidence: str) -> None:
        tp = ThemeParticipation(theme_key=theme_key, mode=mode, evidence=(evidence,))
        if tp not in parts:
            parts.append(tp)

    for theme_key in deck_context.active_theme_keys:
        mode = _oracle_theme_mode(theme_key, text, main_types, subtypes)
        if mode is not None:
            strength = deck_context.active_theme_strengths.get(theme_key)
            evidence = f"theme-engine:{mode}"
            if strength is not None:
                evidence = f"{evidence}:strength={strength:.3f}"
            add(theme_key, mode, evidence)
    return tuple(parts)


def _mana_output_amount(text: str) -> Optional[float]:
    symbol_matches = re.findall(r"add\s+((?:\{[^}]+\})+)", text)
    if symbol_matches:
        return float(max(len(re.findall(r"\{[^}]+\}", match)) for match in symbol_matches))
    if "add three mana" in text:
        return 3.0
    if "add two mana" in text:
        return 2.0
    if "add one mana" in text or "add one mana of" in text:
        return 1.0
    return None


def _mana_color_support(card: Dict[str, Any], commander_ci: Set[str], text: str) -> Optional[float]:
    produced = {str(x).upper() for x in (card.get("produced_mana") or []) if isinstance(x, str)}
    produced_colors = produced & {"W", "U", "B", "R", "G"}
    if not commander_ci:
        if "C" in produced or "{c}" in text or "colorless" in text or "add {c}" in text:
            return 2.0
        return 0.0

    if "any color" in text:
        return 4.0
    if "chosen color" in text:
        return 3.0 if len(commander_ci) == 1 else 2.5
    if len(commander_ci) == 1:
        return 3.0 if produced_colors & commander_ci else 0.0
    if produced_colors >= commander_ci and commander_ci:
        return 3.0
    if produced_colors & commander_ci:
        return 1.0 + (len(produced_colors & commander_ci) / max(len(commander_ci), 1))
    return 0.0


def _etb_tapped(text: str) -> bool:
    return bool(re.search(r"enters? tapped", text))


def _castability_burden(mana_cost: ManaCostProfile) -> float:
    colored_pips = sum(mana_cost.pip_counts.values())
    return float(mana_cost.distinct_colors_required) + (0.25 * float(colored_pips))


def _mana_line_prefix(text: str) -> str:
    match = re.search(r"([^\n.]*)\{t\}\s*:\s*add", text, re.IGNORECASE)
    return (match.group(1) or "").lower() if match else ""


def _activation_burden(text: str) -> float:
    prefix = _mana_line_prefix(text)
    if not prefix:
        return 0.0
    tokens = re.findall(r"\{([^}]+)\}", prefix)
    burden = 0.0
    for token in tokens:
        token = token.upper()
        if token == "T":
            continue
        if token.isdigit():
            burden += float(token)
        elif token in {"W", "U", "B", "R", "G", "C"}:
            burden += 1.0
        elif "/" in token:
            burden += 1.0
        else:
            burden += 0.5
    return burden


def _has_life_cost(text: str) -> bool:
    prefix = _mana_line_prefix(text)
    return "pay" in prefix and "life" in prefix


def _has_sacrifice_cost(text: str) -> bool:
    prefix = _mana_line_prefix(text)
    return "sacrifice" in prefix


def _summoning_delay(main_types: Tuple[MainType, ...], text: str) -> float:
    if "creature" not in main_types:
        return 0.0
    if "haste" in text or "as though it had haste" in text:
        return 0.0
    return 1.0


def _simple_draw_count(text: str) -> Optional[int]:
    if any(marker in text for marker in ("discard", "for each", "if ", "unless", "equal to", "target player", "this turn")):
        return None
    match = re.search(r"draw\s+(a|one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+cards?", text)
    if not match:
        return None
    raw = match.group(1)
    if raw.isdigit():
        return int(raw)
    return NUMBER_WORDS.get(raw)


def _returns_to_hand_tutor(text: str) -> bool:
    return "search your library" in text and "put it into your hand" in text


def _destroy_artifact_enchantment_scope(text: str) -> bool:
    return any(
        phrase in text
        for phrase in (
            "destroy target artifact or enchantment",
            "destroy target artifact, enchantment",
            "destroy target artifact or target enchantment",
        )
    )


def _resolve_replacement_class(
    card: Dict[str, Any],
    main_types: Tuple[MainType, ...],
    text: str,
    mana_cost: ManaCostProfile,
    deck_context: DeckContext,
) -> Tuple[ReplacementFamily, Optional[str], Dict[str, Any], List[str], List[str]]:
    replacement_family: ReplacementFamily = "unsupported"
    comparison_class: Optional[str] = None
    comparison_data: Dict[str, Any] = {}
    evidence: List[str] = []
    unsupported: List[str] = []
    type_sig = "+".join(main_types)

    if (
        "{t}" in text
        and _mana_output_amount(text) is not None
        and main_types
        and any(token in main_types for token in ("artifact", "creature", "land"))
    ):
        if any(marker in text for marker in ("activate only if", "spend this mana only", "only to cast", "among colors")):
            unsupported.append("Mana production is conditional or restricted.")
        else:
            replacement_family = "mana-rock" if "artifact" in main_types else ("mana-dork" if "creature" in main_types else "mana-land")
            comparison_class = f"mana:{type_sig}:repeatable"
            comparison_data = {
                "mana_value": mana_cost.mana_value,
                "output_amount": _mana_output_amount(text),
                "color_support": _mana_color_support(card, deck_context.commander_color_identity, text),
                "enters_tapped": _etb_tapped(text),
                "activation_burden": _activation_burden(text),
                "life_cost": 1.0 if _has_life_cost(text) else 0.0,
                "sacrifice_cost": 1.0 if _has_sacrifice_cost(text) else 0.0,
                "summoning_delay": _summoning_delay(main_types, text),
                "cast_color_burden": _castability_burden(mana_cost),
            }
            evidence.append("Repeatable mana source with supported output and tempo axes.")
            return replacement_family, comparison_class, comparison_data, evidence, unsupported

    if "counter target" in text and "unless" not in text and "pays" not in text and "activated ability" not in text:
        scope = None
        if "counter target noncreature spell" in text:
            scope = "noncreature"
        elif "counter target spell" in text:
            scope = "any"
        if scope is None:
            unsupported.append("Counterspell target scope is not supported.")
        else:
            replacement_family = "counterspell"
            comparison_class = f"counter:hard:{scope}"
            comparison_data = {
                "mana_value": mana_cost.mana_value,
                "scope_rank": 2 if scope == "any" else 1,
                "cast_color_burden": _castability_burden(mana_cost),
            }
            evidence.append("Hard counter with supported target scope.")
            return replacement_family, comparison_class, comparison_data, evidence, unsupported

    if any(token in main_types for token in ("instant", "sorcery")) and _destroy_artifact_enchantment_scope(text):
        if any(marker in text for marker in ("unless", "if ", "mana value", "power", "toughness")):
            unsupported.append("Removal text has conditional restrictions.")
        else:
            replacement_family = "spot-removal"
            comparison_class = "remove:spot:artifact-enchantment:destroy"
            comparison_data = {
                "mana_value": mana_cost.mana_value,
                "effect_rank": 1,
                "cast_color_burden": _castability_burden(mana_cost),
            }
            evidence.append("Simple artifact/enchantment removal spell with supported target domain.")
            return replacement_family, comparison_class, comparison_data, evidence, unsupported

    if any(token in main_types for token in ("instant", "sorcery")) and "destroy target creature" in text:
        if any(marker in text for marker in ("mana value", "power", "toughness", "tapped", "attacking", "blocking", "unless", "if ")):
            unsupported.append("Removal text has conditional restrictions.")
        else:
            replacement_family = "spot-removal"
            comparison_class = "remove:spot:creature:destroy"
            comparison_data = {
                "mana_value": mana_cost.mana_value,
                "effect_rank": 1,
                "cast_color_burden": _castability_burden(mana_cost),
            }
            evidence.append("Simple creature destruction spell with supported target domain.")
            return replacement_family, comparison_class, comparison_data, evidence, unsupported

    if any(token in main_types for token in ("instant", "sorcery")) and _returns_to_hand_tutor(text):
        if "artifact or enchantment" in text or "artifact, enchantment" in text:
            replacement_family = "tutor"
            comparison_class = "tutor:artifact-or-enchantment:to-hand"
            comparison_data = {
                "mana_value": mana_cost.mana_value,
                "destination_rank": 1,
                "cast_color_burden": _castability_burden(mana_cost),
            }
            evidence.append("Fixed artifact/enchantment tutor to hand.")
            return replacement_family, comparison_class, comparison_data, evidence, unsupported
        unsupported.append("Tutor domain is not in a supported strict-comparison class.")

    if any(token in main_types for token in ("instant", "sorcery")):
        draw_count = _simple_draw_count(text)
        if draw_count is not None:
            replacement_family = "draw"
            comparison_class = f"draw:{type_sig}:fixed"
            comparison_data = {
                "mana_value": mana_cost.mana_value,
                "cards_drawn": float(draw_count),
                "cast_color_burden": _castability_burden(mana_cost),
            }
            evidence.append("Fixed-count draw spell with supported mana and volume axes.")
            return replacement_family, comparison_class, comparison_data, evidence, unsupported

    unsupported.append("Card is not in a supported strict-comparison class.")
    return replacement_family, comparison_class, comparison_data, evidence, unsupported


def _profile_from_card(card: Dict[str, Any], deck_context: DeckContext, entry: CardEntry | None = None) -> CardProfile:
    text = _card_text(card)
    name = str(card.get("name") or "")
    main_types, subtypes = _split_type_line(str(card.get("type_line") or ""))
    mana_cost = _mana_cost_profile(card)
    normalized_roles = _normalized_roles(card, entry)
    theme_participation = _theme_participation(card, deck_context)
    evidence: Dict[str, List[str]] = {"oracle": [], "type-line": [], "deck-tag": [], "theme-engine": []}
    unsupported: List[str] = []
    evidence["type-line"].append(f"Normalized main types: {', '.join(main_types) or 'none'}.")
    if subtypes:
        evidence["type-line"].append(f"Normalized subtypes: {', '.join(subtypes)}.")

    replacement_family, comparison_class, comparison_data, oracle_items, oracle_unsupported = _resolve_replacement_class(
        card=card,
        main_types=main_types,
        text=text,
        mana_cost=mana_cost,
        deck_context=deck_context,
    )
    evidence["oracle"].extend(oracle_items)
    unsupported.extend(oracle_unsupported)

    if comparison_class is None:
        if not unsupported:
            unsupported.append("Card is not in a supported strict-comparison class.")
    if mana_cost.has_alt_cost and comparison_class is None:
        unsupported.append("Alternate-cost card text is not normalized for strict comparison.")

    if entry is not None:
        for tag in entry.tags:
            if tag in FUNCTIONAL_ROLES:
                evidence["deck-tag"].append(f"Normalized comparable role from {tag}.")
            elif tag in MAPPABLE_DECK_TAGS or (tag.startswith("#") and tag.endswith("Typal")):
                evidence["deck-tag"].append(f"Mapped deck tag {tag} into shared theme schema.")
            else:
                unsupported.append(f"Deck tag {tag} cannot be mapped into the shared strict-comparison schema.")

    for theme in theme_participation:
        for item in theme.evidence:
            evidence["theme-engine"].append(f"{theme.theme_key}:{theme.mode}:{item}")

    return CardProfile(
        schema_version=PROFILE_SCHEMA_VERSION,
        name=name,
        oracle_id=str(card.get("oracle_id") or ""),
        main_types=main_types,
        subtypes=subtypes,
        color_identity=_normalize_color_identity(card),
        mana_cost=mana_cost,
        normalized_roles=normalized_roles,
        replacement_family=replacement_family,
        comparison_class=comparison_class,
        comparison_data=comparison_data,
        theme_participation=theme_participation,
        comparable_utility_roles=_comparable_utility_roles(normalized_roles, replacement_family),
        strict_comparable=not unsupported,
        unsupported_reasons=tuple(unsupported),
        evidence=evidence,
    )


def _build_deck_context(cards: Sequence[CardEntry], card_map: Dict[str, Dict[str, Any]], commander_names: Sequence[str]) -> DeckContext:
    type_profile = compute_type_theme_profile(list(cards), card_map)
    active_theme_keys, active_theme_strengths = _active_themes(cards, type_profile)
    return DeckContext(
        commander_names=tuple(commander_names),
        commander_color_identity=set(combined_color_identity(card_map, list(commander_names))),
        deck_names={entry.name for entry in cards if entry.section in {"deck", "commander"}},
        active_theme_keys=active_theme_keys,
        active_theme_strengths=active_theme_strengths,
        type_profile=type_profile,
    )


def _selected_theme_obligations(profile: CardProfile, deck_context: DeckContext) -> Tuple[ThemeParticipation, ...]:
    obligations = [
        theme
        for theme in profile.theme_participation
        if theme.theme_key in deck_context.active_theme_keys
    ]
    unique: List[ThemeParticipation] = []
    for theme in obligations:
        if theme not in unique:
            unique.append(theme)
    return tuple(unique)


def _build_contract(profile: CardProfile, deck_context: DeckContext, budget_cap_usd: Optional[float] = None) -> Optional[ReplacementContract]:
    if not profile.strict_comparable or not profile.replacement_family or not profile.comparison_class:
        return None
    return ReplacementContract(
        selected_profile=profile,
        exact_main_types=profile.main_types,
        replacement_family=profile.replacement_family,
        comparison_class=profile.comparison_class,
        selected_comparison_data=dict(profile.comparison_data),
        required_roles=set(profile.comparable_utility_roles),
        required_theme_obligations=_selected_theme_obligations(profile, deck_context),
        budget_cap_usd=budget_cap_usd,
        commander_color_identity=deck_context.commander_color_identity,
        exclude_names=set(deck_context.deck_names),
    )


def _theme_recall_hints(contract: ReplacementContract) -> Tuple[str, ...]:
    hints = []
    for theme in contract.required_theme_obligations:
        if theme.theme_key not in hints:
            hints.append(theme.theme_key)
    return tuple(hints)


def _theme_query_specs(contract: ReplacementContract, type_filters: str, mv_cap: int) -> Tuple[QuerySpec, ...]:
    specs: List[QuerySpec] = []
    for theme_key in _theme_recall_hints(contract):
        if theme_key.startswith("typal:"):
            subtype = theme_key.split(":", 1)[1]
            if subtype:
                specs.append(
                    QuerySpec(
                        label=f"theme:{theme_key}",
                        query=f"{type_filters} (t:{subtype} or o:'{subtype}') mv<={max(0, mv_cap)}",
                        limit=120,
                        order="name",
                    )
                )
        elif theme_key == "package:equipment":
            specs.append(QuerySpec(label="theme:equipment", query=f"{type_filters} (t:equipment or o:'equipped creature' or o:'equipment') mv<={max(0, mv_cap)}", limit=120, order="name"))
        elif theme_key == "package:aura":
            specs.append(QuerySpec(label="theme:aura", query=f"{type_filters} (t:aura or o:'enchanted creature' or o:'aura') mv<={max(0, mv_cap)}", limit=120, order="name"))
        elif theme_key == "package:shrine":
            specs.append(QuerySpec(label="theme:shrine", query=f"{type_filters} (t:shrine or o:'shrine') mv<={max(0, mv_cap)}", limit=120, order="name"))
        elif theme_key == "package:background":
            specs.append(QuerySpec(label="theme:background", query=f"{type_filters} (t:background or o:'background') mv<={max(0, mv_cap)}", limit=120, order="name"))
    return tuple(specs)


def _candidate_query_specs(contract: ReplacementContract) -> Tuple[QuerySpec, ...]:
    type_filters = " ".join(f"t:{token}" for token in contract.exact_main_types)
    mv_cap = int(contract.selected_profile.mana_cost.mana_value) if isinstance(contract.selected_profile.mana_cost.mana_value, (int, float)) else 6
    theme_specs = _theme_query_specs(contract, type_filters, mv_cap)
    if contract.replacement_family in {"mana-rock", "mana-dork", "mana-land"}:
        return (
            QuerySpec(label="family:mana", query=f"{type_filters} o:'{{T}}: add' mv<={max(0, mv_cap)}", limit=180, order="name"),
            *theme_specs,
        )
    if contract.replacement_family == "counterspell":
        return (
            QuerySpec(label="family:counter", query=f"{type_filters} o:'counter target spell' mv<={max(0, mv_cap)}", limit=150, order="name"),
            QuerySpec(label="family:counter-wide", query=f"{type_filters} o:'counter target noncreature spell' mv<={max(0, mv_cap)}", limit=120, order="name"),
            *theme_specs,
        )
    if contract.replacement_family == "spot-removal":
        if contract.comparison_class == "remove:spot:artifact-enchantment:destroy":
            return (
                QuerySpec(
                    label="family:removal-artifact-enchantment",
                    query=f"{type_filters} o:'destroy target artifact or enchantment' mv<={max(0, mv_cap)}",
                    limit=150,
                    order="name",
                ),
                *theme_specs,
            )
        return (
            QuerySpec(
                label="family:removal-creature",
                query=f"{type_filters} o:'destroy target creature' mv<={max(0, mv_cap)}",
                limit=150,
                order="name",
            ),
            *theme_specs,
        )
    if contract.replacement_family == "draw":
        return (
            QuerySpec(label="family:draw", query=f"{type_filters} o:'draw' mv<={max(0, mv_cap)}", limit=150, order="name"),
            *theme_specs,
        )
    if contract.replacement_family == "tutor":
        return (
            QuerySpec(
                label="family:tutor-artifact-enchantment",
                query=f"{type_filters} o:'search your library' o:'artifact or enchantment' o:'put it into your hand' mv<={max(0, mv_cap)}",
                limit=150,
                order="name",
            ),
            *theme_specs,
        )
    return ()


def _build_candidate_query_plan(contract: ReplacementContract) -> CandidateQuerySpec:
    return CandidateQuerySpec(
        exact_main_types=contract.exact_main_types,
        replacement_family=contract.replacement_family,
        comparison_class=contract.comparison_class,
        commander_color_identity=set(contract.commander_color_identity),
        exclude_names=set(contract.exclude_names) | {contract.selected_profile.name},
        budget_cap_usd=contract.budget_cap_usd,
        theme_hints=_theme_recall_hints(contract),
        scryfall_specs=_candidate_query_specs(contract),
    )


def _preserves_themes(candidate: CardProfile, contract: ReplacementContract) -> Tuple[bool, List[str]]:
    if not contract.required_theme_obligations:
        return True, []
    candidate_pairs = {(row.theme_key, row.mode) for row in candidate.theme_participation}
    missing: List[str] = []
    for requirement in contract.required_theme_obligations:
        if (requirement.theme_key, requirement.mode) not in candidate_pairs:
            missing.append(f"{requirement.theme_key}:{requirement.mode}")
    return not missing, missing


ROLE_SUBSUMPTION: Dict[str, Set[str]] = {
    "#Counter": {"#Counter", "#StackInteraction"},
    "#StackInteraction": {"#StackInteraction"},
    "#Removal": {"#Removal", "#SpotRemoval"},
    "#SpotRemoval": {"#SpotRemoval"},
    "#Boardwipe": {"#Boardwipe", "#MassRemoval"},
    "#MassRemoval": {"#MassRemoval"},
    "#Ramp": {"#Ramp", "#Fixing"},
    "#Fixing": {"#Fixing"},
    "#Tutor": {"#Tutor"},
    "#Draw": {"#Draw"},
    "#Recursion": {"#Recursion"},
}


def _role_is_covered(required_role: str, candidate_roles: Set[str]) -> bool:
    covered_by = ROLE_SUBSUMPTION.get(required_role, {required_role})
    return bool(candidate_roles & covered_by)


def _roles_preserved(candidate: CardProfile, contract: ReplacementContract) -> bool:
    candidate_roles = set(candidate.comparable_utility_roles)
    return all(_role_is_covered(role, candidate_roles) for role in contract.required_roles)


COMPARISON_CLASS_SUBSUMPTION: Dict[str, Set[str]] = {
    "counter:hard:noncreature": {"counter:hard:any"},
}


def _comparison_class_supported(selected_class: str, candidate_class: Optional[str]) -> bool:
    if candidate_class is None:
        return False
    if candidate_class == selected_class:
        return True
    return candidate_class in COMPARISON_CLASS_SUBSUMPTION.get(selected_class, set())


def _passes_basic_candidate_filters(candidate_card: Dict[str, Any], candidate_name: str, query_plan: CandidateQuerySpec) -> Tuple[bool, Optional[str]]:
    if not candidate_name or candidate_name in query_plan.exclude_names:
        return False, "Candidate is excluded from recall."

    legalities = candidate_card.get("legalities") or {}
    if legalities and str(legalities.get("commander") or "").lower() not in {"", "legal"}:
        return False, "Candidate is not Commander legal."

    games = {str(x).lower() for x in (candidate_card.get("games") or []) if isinstance(x, str)}
    if games and "paper" not in games:
        return False, "Candidate is not available in paper."

    price = _to_float((candidate_card.get("prices") or {}).get("usd"))
    if query_plan.budget_cap_usd is not None and (price is None or price > query_plan.budget_cap_usd):
        return False, "Candidate is over budget or missing price under budget constraint."

    return True, None


def _evaluate_axis_higher_better(axis: str, selected_value: Any, candidate_value: Any, reason_better: str, reason_equal: str, reason_worse: str) -> AxisResult:
    if selected_value is None or candidate_value is None:
        return AxisResult(axis=axis, status="unknown", reason=f"{axis} could not be compared.")
    if candidate_value > selected_value:
        return AxisResult(axis=axis, status="better", reason=reason_better, delta=float(candidate_value) - float(selected_value))
    if candidate_value == selected_value:
        return AxisResult(axis=axis, status="equal", reason=reason_equal)
    return AxisResult(axis=axis, status="worse", reason=reason_worse, delta=float(candidate_value) - float(selected_value))


def _evaluate_axis_lower_better(axis: str, selected_value: Any, candidate_value: Any, reason_better: str, reason_equal: str, reason_worse: str) -> AxisResult:
    if selected_value is None or candidate_value is None:
        return AxisResult(axis=axis, status="unknown", reason=f"{axis} could not be compared.")
    if candidate_value < selected_value:
        return AxisResult(axis=axis, status="better", reason=reason_better, delta=float(selected_value) - float(candidate_value))
    if candidate_value == selected_value:
        return AxisResult(axis=axis, status="equal", reason=reason_equal)
    return AxisResult(axis=axis, status="worse", reason=reason_worse, delta=float(selected_value) - float(candidate_value))


def _evaluate_mana_candidate(candidate: CardProfile, contract: ReplacementContract) -> List[AxisResult]:
    selected = contract.selected_profile
    return [
        _evaluate_axis_lower_better(
            "mana_value",
            selected.comparison_data.get("mana_value"),
            candidate.comparison_data.get("mana_value"),
            f"Lower mana value ({candidate.mana_cost.mana_value:.0f} vs {selected.mana_cost.mana_value:.0f}).",
            "Same mana value.",
            "Higher mana value.",
        ),
        _evaluate_axis_higher_better(
            "output_amount",
            selected.comparison_data.get("output_amount"),
            candidate.comparison_data.get("output_amount"),
            f"Produces more mana per activation ({candidate.comparison_data.get('output_amount'):.0f} vs {selected.comparison_data.get('output_amount'):.0f}).",
            "Produces the same mana per activation.",
            "Produces less mana per activation.",
        ),
        _evaluate_axis_higher_better(
            "color_support",
            selected.comparison_data.get("color_support"),
            candidate.comparison_data.get("color_support"),
            "Improves color coverage for the commander's identity.",
            "Matches the same color coverage.",
            "Weakens color coverage for the commander's identity.",
        ),
        _evaluate_axis_lower_better(
            "enters_tapped",
            1.0 if selected.comparison_data.get("enters_tapped") else 0.0,
            1.0 if candidate.comparison_data.get("enters_tapped") else 0.0,
            "Avoids the enters-tapped tempo loss.",
            "Same enters-tapped tempo profile.",
            "Adds an enters-tapped tempo loss.",
        ),
        _evaluate_axis_lower_better(
            "activation_burden",
            selected.comparison_data.get("activation_burden"),
            candidate.comparison_data.get("activation_burden"),
            "Has a lower activation burden.",
            "Same activation burden.",
            "Adds activation burden.",
        ),
        _evaluate_axis_lower_better(
            "life_cost",
            selected.comparison_data.get("life_cost"),
            candidate.comparison_data.get("life_cost"),
            "Avoids life payment.",
            "Same life-payment profile.",
            "Adds life payment.",
        ),
        _evaluate_axis_lower_better(
            "sacrifice_cost",
            selected.comparison_data.get("sacrifice_cost"),
            candidate.comparison_data.get("sacrifice_cost"),
            "Avoids sacrifice requirements.",
            "Same sacrifice-cost profile.",
            "Adds sacrifice requirements.",
        ),
        _evaluate_axis_lower_better(
            "summoning_delay",
            selected.comparison_data.get("summoning_delay"),
            candidate.comparison_data.get("summoning_delay"),
            "Becomes usable immediately more often.",
            "Same summoning-delay profile.",
            "Adds summoning delay.",
        ),
        _evaluate_axis_lower_better(
            "cast_color_burden",
            selected.comparison_data.get("cast_color_burden"),
            candidate.comparison_data.get("cast_color_burden"),
            "Easier to cast in color terms.",
            "Same color-cast burden.",
            "Harder to cast in color terms.",
        ),
    ]


def _evaluate_counter_candidate(candidate: CardProfile, contract: ReplacementContract) -> List[AxisResult]:
    selected = contract.selected_profile
    return [
        _evaluate_axis_lower_better(
            "mana_value",
            selected.comparison_data.get("mana_value"),
            candidate.comparison_data.get("mana_value"),
            f"Lower mana value ({candidate.mana_cost.mana_value:.0f} vs {selected.mana_cost.mana_value:.0f}).",
            "Same mana value.",
            "Higher mana value.",
        ),
        _evaluate_axis_higher_better(
            "scope_rank",
            selected.comparison_data.get("scope_rank"),
            candidate.comparison_data.get("scope_rank"),
            "Covers a wider spell target range.",
            "Matches the same spell target range.",
            "Covers a narrower spell target range.",
        ),
        _evaluate_axis_lower_better(
            "cast_color_burden",
            selected.comparison_data.get("cast_color_burden"),
            candidate.comparison_data.get("cast_color_burden"),
            "Easier to cast in color terms.",
            "Same color-cast burden.",
            "Harder to cast in color terms.",
        ),
    ]


def _evaluate_removal_candidate(candidate: CardProfile, contract: ReplacementContract) -> List[AxisResult]:
    selected = contract.selected_profile
    return [
        _evaluate_axis_lower_better(
            "mana_value",
            selected.comparison_data.get("mana_value"),
            candidate.comparison_data.get("mana_value"),
            f"Lower mana value ({candidate.mana_cost.mana_value:.0f} vs {selected.mana_cost.mana_value:.0f}).",
            "Same mana value.",
            "Higher mana value.",
        ),
        _evaluate_axis_higher_better(
            "effect_rank",
            selected.comparison_data.get("effect_rank"),
            candidate.comparison_data.get("effect_rank"),
            "Uses a stronger removal mode.",
            "Matches the same removal mode.",
            "Uses a weaker removal mode.",
        ),
        _evaluate_axis_lower_better(
            "cast_color_burden",
            selected.comparison_data.get("cast_color_burden"),
            candidate.comparison_data.get("cast_color_burden"),
            "Easier to cast in color terms.",
            "Same color-cast burden.",
            "Harder to cast in color terms.",
        ),
    ]


def _evaluate_draw_candidate(candidate: CardProfile, contract: ReplacementContract) -> List[AxisResult]:
    selected = contract.selected_profile
    return [
        _evaluate_axis_lower_better(
            "mana_value",
            selected.comparison_data.get("mana_value"),
            candidate.comparison_data.get("mana_value"),
            f"Lower mana value ({candidate.mana_cost.mana_value:.0f} vs {selected.mana_cost.mana_value:.0f}).",
            "Same mana value.",
            "Higher mana value.",
        ),
        _evaluate_axis_higher_better(
            "cards_drawn",
            selected.comparison_data.get("cards_drawn"),
            candidate.comparison_data.get("cards_drawn"),
            f"Draws more cards ({candidate.comparison_data.get('cards_drawn'):.0f} vs {selected.comparison_data.get('cards_drawn'):.0f}).",
            "Draws the same number of cards.",
            "Draws fewer cards.",
        ),
        _evaluate_axis_lower_better(
            "cast_color_burden",
            selected.comparison_data.get("cast_color_burden"),
            candidate.comparison_data.get("cast_color_burden"),
            "Easier to cast in color terms.",
            "Same color-cast burden.",
            "Harder to cast in color terms.",
        ),
    ]


def _evaluate_tutor_candidate(candidate: CardProfile, contract: ReplacementContract) -> List[AxisResult]:
    selected = contract.selected_profile
    return [
        _evaluate_axis_lower_better(
            "mana_value",
            selected.comparison_data.get("mana_value"),
            candidate.comparison_data.get("mana_value"),
            f"Lower mana value ({candidate.mana_cost.mana_value:.0f} vs {selected.mana_cost.mana_value:.0f}).",
            "Same mana value.",
            "Higher mana value.",
        ),
        _evaluate_axis_lower_better(
            "cast_color_burden",
            selected.comparison_data.get("cast_color_burden"),
            candidate.comparison_data.get("cast_color_burden"),
            "Easier to cast in color terms.",
            "Same color-cast burden.",
            "Harder to cast in color terms.",
        ),
    ]


COMPARATOR_REGISTRY = {
    "mana:artifact:repeatable": _evaluate_mana_candidate,
    "mana:land:repeatable": _evaluate_mana_candidate,
    "mana:creature:repeatable": _evaluate_mana_candidate,
    "counter:hard:any": _evaluate_counter_candidate,
    "counter:hard:noncreature": _evaluate_counter_candidate,
    "remove:spot:creature:destroy": _evaluate_removal_candidate,
    "remove:spot:artifact-enchantment:destroy": _evaluate_removal_candidate,
    "tutor:artifact-or-enchantment:to-hand": _evaluate_tutor_candidate,
    "draw:instant:fixed": _evaluate_draw_candidate,
    "draw:sorcery:fixed": _evaluate_draw_candidate,
}


def _evaluate_candidate(candidate: CardProfile, contract: ReplacementContract) -> CandidateDecision:
    if not candidate.strict_comparable:
        return CandidateDecision(False, tuple(candidate.unsupported_reasons), tuple(), tuple(), ())
    if candidate.main_types != contract.exact_main_types:
        return CandidateDecision(False, ("Exact main card type is not preserved.",), tuple(), tuple(), ())
    themes_ok, missing_themes = _preserves_themes(candidate, contract)
    if not themes_ok:
        return CandidateDecision(False, tuple(f"Missing active theme obligation: {item}." for item in missing_themes), tuple(), tuple(), ())
    if candidate.replacement_family != contract.replacement_family:
        return CandidateDecision(False, ("Core replacement family does not match the selected card.",), tuple(), tuple(), ())
    if not _comparison_class_supported(contract.comparison_class, candidate.comparison_class):
        return CandidateDecision(False, ("Strict comparison class does not match the selected card.",), tuple(), tuple(), ())
    if contract.required_roles and not _roles_preserved(candidate, contract):
        return CandidateDecision(False, ("Comparable utility role coverage is not preserved.",), tuple(), tuple(), ())

    comparator = COMPARATOR_REGISTRY.get(contract.comparison_class)
    if comparator is None:
        return CandidateDecision(False, ("Selected card family is not supported by the strict evaluator.",), tuple(), tuple(), ())
    axes = comparator(candidate, contract)

    if any(axis.status == "unknown" for axis in axes):
        return CandidateDecision(False, tuple(axis.reason for axis in axes if axis.status == "unknown"), tuple(), tuple(), ())
    if any(axis.status == "worse" for axis in axes):
        return CandidateDecision(False, tuple(axis.reason for axis in axes if axis.status == "worse"), tuple(), tuple(), ())

    better_axes = [axis for axis in axes if axis.status == "better"]
    if not better_axes:
        return CandidateDecision(False, ("Candidate is only equal, not strictly better.",), tuple(), tuple(), ())

    role_overlap = tuple(sorted(contract.required_roles & set(candidate.comparable_utility_roles)))
    reasons = [axis.reason for axis in better_axes]
    proof_bits = [f"Better on {', '.join(axis.axis for axis in better_axes)}."]
    if contract.required_theme_obligations:
        theme_summary = ", ".join(f"{theme.theme_key}:{theme.mode}" for theme in contract.required_theme_obligations)
        reasons.append("Preserves the selected card's active deck-theme contribution.")
        proof_bits.append(f"Preserves active theme obligations: {theme_summary}.")
    if role_overlap:
        reasons.append(f"Matches role(s): {', '.join(role_overlap)}.")
        proof_bits.append(f"Preserves comparable roles: {', '.join(role_overlap)}.")

    priority_weights = {
        "mana_value": 6,
        "output_amount": 5,
        "color_support": 5,
        "scope_rank": 5,
        "effect_rank": 5,
        "cards_drawn": 5,
        "enters_tapped": 4,
        "activation_burden": 4,
        "cast_color_burden": 4,
        "destination_rank": 4,
        "life_cost": 3,
        "sacrifice_cost": 3,
        "summoning_delay": 3,
    }
    sorted_better = sorted(better_axes, key=lambda axis: (-priority_weights.get(axis.axis, 1), -axis.delta, axis.axis))
    ranking_key = (
        -len(sorted_better),
        tuple(-priority_weights.get(axis.axis, 1) for axis in sorted_better),
        tuple(-round(axis.delta, 3) for axis in sorted_better),
        -len(set(candidate.comparable_utility_roles) - contract.required_roles),
    )
    return CandidateDecision(True, tuple(reasons), role_overlap, tuple(axis.axis for axis in sorted_better), ranking_key + tuple(proof_bits))


def _rank_survivors(options: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        options,
        key=lambda row: (
            row.get("_ranking_key") or (),
            -(len(row.get("role_overlap") or [])),
            row.get("price_usd") is None,
            row.get("price_usd") if row.get("price_usd") is not None else 10**9,
            row.get("popularity_pct") if row.get("popularity_pct") is not None else 10**9,
            row.get("card", ""),
        ),
    )


def strictly_better_replacements(
    cards: List[CardEntry],
    selected_card: str,
    commander: str | None = None,
    budget_max_usd: float | None = None,
    limit: int = 6,
    explain: bool = False,
) -> Dict[str, Any]:
    svc = CardDataService()
    deck_cards = [c for c in cards if c.section in {"deck", "commander"}]
    selected_entry = next((c for c in deck_cards if c.name == selected_card), None)
    if selected_entry is None:
        return {"schema_version": 1, "selected_card": selected_card, "options": [], "no_result_reasons": ["Selected card is not in the deck."]}

    commander_names = commander_names_from_cards(cards, fallback_commander=commander)
    lookup_names = list({selected_card, *commander_names, *(entry.name for entry in deck_cards)})
    card_map = svc.get_cards_by_name(lookup_names)
    selected_data = card_map.get(selected_card)
    if not selected_data:
        return {"schema_version": 1, "selected_card": selected_card, "options": [], "no_result_reasons": ["Selected card data could not be loaded."]}

    deck_context = _build_deck_context(deck_cards, card_map, commander_names)
    selected_profile = _profile_from_card(selected_data, deck_context, entry=selected_entry)
    contract = _build_contract(selected_profile, deck_context, budget_cap_usd=budget_max_usd)
    if contract is None:
        payload = {
            "schema_version": 1,
            "selected_card": selected_card,
            "options": [],
            "no_result_reasons": ["Selected card is not strict-comparable."],
        }
        if explain:
            payload["selected_profile"] = _selected_profile_summary(selected_profile, contract=None)
        return payload
    query_plan = _build_candidate_query_plan(contract)
    if not query_plan.scryfall_specs:
        payload = {
            "schema_version": 1,
            "selected_card": selected_card,
            "options": [],
            "no_result_reasons": ["No candidate recall plan is available for this strict comparison class."],
        }
        if explain:
            payload["selected_profile"] = _selected_profile_summary(selected_profile, contract=contract)
        return payload

    commander_ci = "".join(sorted(deck_context.commander_color_identity))
    candidates = svc.search_union(query_plan.scryfall_specs, commander_ci)
    options: List[Dict[str, Any]] = []
    rejected_counts = {"budget": 0, "theme": 0, "type": 0, "strict": 0, "basic": 0}
    rejected_examples: List[Dict[str, Any]] = []
    seen_names: Set[str] = set()
    for candidate_card in candidates:
        candidate_name = str(candidate_card.get("name") or "")
        passes_basic, reject_reason = _passes_basic_candidate_filters(candidate_card, candidate_name, query_plan)
        if not passes_basic or candidate_name in seen_names:
            if reject_reason:
                rejected_counts["basic"] += 1
            continue
        price = _to_float((candidate_card.get("prices") or {}).get("usd"))

        candidate_profile = _profile_from_card(candidate_card, deck_context)
        decision = _evaluate_candidate(candidate_profile, contract)
        if not decision.accepted:
            reasons_text = " ".join(decision.reasons).lower()
            if "budget" in reasons_text or "price" in reasons_text:
                rejected_counts["budget"] += 1
            elif "theme obligation" in reasons_text:
                rejected_counts["theme"] += 1
            elif "main card type" in reasons_text:
                rejected_counts["type"] += 1
            else:
                rejected_counts["strict"] += 1
            if explain and len(rejected_examples) < 5:
                rejected_examples.append({"name": candidate_name, "reasons": list(decision.reasons)})
            continue

        display = svc.card_display(candidate_card)
        options.append(
            {
                "card": candidate_name,
                "reasons": list(decision.reasons),
                "better_axes": list(decision.better_axes),
                "proof_summary": _proof_summary(contract, decision),
                "price_usd": price,
                "role_overlap": list(decision.role_overlap),
                "mana_value": candidate_profile.mana_cost.mana_value,
                "selected_mana_value": selected_profile.mana_cost.mana_value,
                "popularity_pct": candidate_card.get("popularity_pct"),
                "_ranking_key": decision.ranking_key,
                "scryfall_uri": candidate_card.get("scryfall_uri") or display.get("scryfall_uri"),
                "cardmarket_url": display.get("cardmarket_url"),
            }
        )
        seen_names.add(candidate_name)

    ranked = _rank_survivors(options)[:limit]
    for row in ranked:
        row.pop("_ranking_key", None)

    payload: Dict[str, Any] = {"schema_version": 1, "selected_card": selected_card, "options": ranked}
    if not ranked:
        payload["no_result_reasons"] = _no_result_reasons(contract, rejected_counts, candidates)
    if explain:
        payload["selected_profile"] = _selected_profile_summary(selected_profile, contract=contract)
        payload["rejected_candidates"] = rejected_examples
    return payload


def _selected_profile_summary(profile: CardProfile, contract: Optional[ReplacementContract]) -> Dict[str, Any]:
    return {
        "main_types": list(profile.main_types),
        "replacement_family": profile.replacement_family,
        "comparison_class": profile.comparison_class,
        "theme_obligations": [
            {"theme_key": theme.theme_key, "mode": theme.mode}
            for theme in (contract.required_theme_obligations if contract is not None else ())
        ],
        "strict_comparable": profile.strict_comparable,
        "unsupported_reasons": list(profile.unsupported_reasons),
    }


def _proof_summary(contract: ReplacementContract, decision: CandidateDecision) -> str:
    bits = [f"Strictly better on {', '.join(decision.better_axes)}."]
    if contract.required_theme_obligations:
        bits.append("Active deck-theme obligations preserved.")
    if decision.role_overlap:
        bits.append(f"Comparable roles preserved: {', '.join(decision.role_overlap)}.")
    return " ".join(bits)


def _no_result_reasons(contract: ReplacementContract, rejected_counts: Dict[str, int], candidates: Sequence[Dict[str, Any]]) -> List[str]:
    reasons: List[str] = []
    if not candidates:
        reasons.append("No recall candidates were found for the selected card's strict family.")
        return reasons
    if rejected_counts["basic"] == len(candidates):
        reasons.append("All candidates failed basic legality, deck, or budget filters.")
    if rejected_counts["type"] > 0:
        reasons.append("No candidates survived exact main-type preservation.")
    if rejected_counts["theme"] > 0:
        reasons.append("No candidates preserved the selected card's active deck-theme obligations.")
    if rejected_counts["strict"] > 0:
        reasons.append("No candidates survived strict comparison without worse or unknown axes.")
    if rejected_counts["budget"] > 0:
        reasons.append("All otherwise-eligible candidates were over budget or lacked known prices.")
    return reasons or ["No candidates survived strict evaluation."]


def _evaluate_candidate_relaxed(candidate: CardProfile, contract: ReplacementContract) -> CandidateDecision:
    if not candidate.strict_comparable:
        return CandidateDecision(False, tuple(candidate.unsupported_reasons), tuple(), tuple(), ())
    if candidate.main_types != contract.exact_main_types:
        return CandidateDecision(False, ("Exact main card type is not preserved.",), tuple(), tuple(), ())
    if candidate.replacement_family != contract.replacement_family:
        return CandidateDecision(False, ("Core replacement family does not match the selected card.",), tuple(), tuple(), ())
    if not _comparison_class_supported(contract.comparison_class, candidate.comparison_class):
        return CandidateDecision(False, ("Strict comparison class does not match the selected card.",), tuple(), tuple(), ())

    comparator = COMPARATOR_REGISTRY.get(contract.comparison_class)
    if comparator is None:
        return CandidateDecision(False, ("Selected card family is not supported by the relaxed shadow evaluator.",), tuple(), tuple(), ())
    axes = comparator(candidate, contract)

    if any(axis.status == "worse" for axis in axes):
        return CandidateDecision(False, tuple(axis.reason for axis in axes if axis.status == "worse"), tuple(), tuple(), ())

    better_axes = [axis for axis in axes if axis.status == "better"]
    if not better_axes:
        return CandidateDecision(False, ("Candidate is only equal, not strictly better.",), tuple(), tuple(), ())

    reasons = [axis.reason for axis in better_axes]
    ranking_key = tuple(axis.axis for axis in better_axes)
    return CandidateDecision(True, tuple(reasons), tuple(), tuple(axis.axis for axis in better_axes), ranking_key)


def strict_replacement_shadow_report(
    cards: List[CardEntry],
    selected_card: str,
    commander: str | None = None,
    budget_max_usd: float | None = None,
    limit: int = 10,
) -> Dict[str, Any]:
    svc = CardDataService()
    deck_cards = [c for c in cards if c.section in {"deck", "commander"}]
    selected_entry = next((c for c in deck_cards if c.name == selected_card), None)
    if selected_entry is None:
        return {
            "selected_card": selected_card,
            "error": "Selected card is not in the deck.",
            "strict": {"options": []},
            "legacy_relaxed": {"options": []},
        }

    commander_names = commander_names_from_cards(cards, fallback_commander=commander)
    lookup_names = list({selected_card, *commander_names, *(entry.name for entry in deck_cards)})
    card_map = svc.get_cards_by_name(lookup_names)
    selected_data = card_map.get(selected_card)
    if not selected_data:
        return {
            "selected_card": selected_card,
            "error": "Selected card data could not be loaded.",
            "strict": {"options": []},
            "legacy_relaxed": {"options": []},
        }

    deck_context = _build_deck_context(deck_cards, card_map, commander_names)
    selected_profile = _profile_from_card(selected_data, deck_context, entry=selected_entry)
    contract = _build_contract(selected_profile, deck_context, budget_cap_usd=budget_max_usd)
    strict_payload = strictly_better_replacements(
        cards=cards,
        selected_card=selected_card,
        commander=commander,
        budget_max_usd=budget_max_usd,
        limit=limit,
        explain=True,
    )
    if contract is None:
        return {
            "selected_card": selected_card,
            "strict": strict_payload,
            "legacy_relaxed": {"options": []},
            "old_pass_new_fail": [],
            "new_pass_old_fail": [],
            "dominant_rejection_reasons": [],
            "shadow_mode": "relaxed-family-proof-v1",
        }

    query_plan = _build_candidate_query_plan(contract)
    commander_ci = "".join(sorted(deck_context.commander_color_identity))
    candidates = svc.search_union(query_plan.scryfall_specs, commander_ci)
    relaxed_options: List[Dict[str, Any]] = []
    relaxed_reasons: Counter[str] = Counter()
    seen_names: Set[str] = set()
    for candidate_card in candidates:
        candidate_name = str(candidate_card.get("name") or "")
        passes_basic, reject_reason = _passes_basic_candidate_filters(candidate_card, candidate_name, query_plan)
        if not passes_basic or candidate_name in seen_names:
            if reject_reason:
                relaxed_reasons[reject_reason] += 1
            continue
        candidate_profile = _profile_from_card(candidate_card, deck_context)
        decision = _evaluate_candidate_relaxed(candidate_profile, contract)
        if not decision.accepted:
            for reason in decision.reasons:
                relaxed_reasons[reason] += 1
            continue
        relaxed_options.append({"card": candidate_name, "better_axes": list(decision.better_axes), "reasons": list(decision.reasons)})
        seen_names.add(candidate_name)

    strict_names = {row["card"] for row in strict_payload.get("options") or []}
    relaxed_names = {row["card"] for row in relaxed_options}
    strict_rejected = Counter()
    for row in strict_payload.get("rejected_candidates") or []:
        for reason in row.get("reasons") or []:
            strict_rejected[reason] += 1
    return {
        "selected_card": selected_card,
        "shadow_mode": "relaxed-family-proof-v1",
        "strict": strict_payload,
        "legacy_relaxed": {"options": relaxed_options[:limit]},
        "old_pass_new_fail": sorted(relaxed_names - strict_names),
        "new_pass_old_fail": sorted(strict_names - relaxed_names),
        "dominant_rejection_reasons": [
            {"reason": reason, "count": count}
            for reason, count in strict_rejected.most_common(10)
        ],
        "relaxed_rejection_reasons": [
            {"reason": reason, "count": count}
            for reason, count in relaxed_reasons.most_common(10)
        ],
    }
