from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Literal

CoverageClass = Literal["executable", "evaluative-only", "unsupported"]

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
    "twenty": 20,
    "x": 4,
}

_MAIN_TYPES = ("artifact", "battle", "creature", "enchantment", "instant", "land", "planeswalker", "sorcery")
_TOKEN_RE = re.compile(
    r"create (x|a|an|\d+|one|two|three|four|five|six|seven|eight|nine|ten|twenty)? ?(?:tapped and attacking )?(?:legendary )?(?:(\d+)\/(\d+))?",
    re.IGNORECASE,
)
_DRAW_RE = re.compile(r"draw (a|an|one|two|three|four|five|six|seven|eight|nine|ten|\d+) cards?", re.IGNORECASE)
_DAMAGE_RE = re.compile(
    r"(?:deals?|deal) (x|\d+|one|two|three|four|five|six|seven|eight|nine|ten) damage to (each opponent|target opponent|target player|any target|each player)",
    re.IGNORECASE,
)
_LOSE_LIFE_RE = re.compile(
    r"(each opponent|target opponent|target player|each player) loses (x|\d+|one|two|three|four|five|six|seven|eight|nine|ten) life",
    re.IGNORECASE,
)
_MILL_RE = re.compile(
    r"(each opponent|target opponent|target player|each player) mills? (x|\d+|one|two|three|four|five|six|seven|eight|nine|ten)",
    re.IGNORECASE,
)
_UPKEEP_WIN_RE = re.compile(
    r"at the beginning of your upkeep, if you have (\d+) or more life, you win the game",
    re.IGNORECASE,
)
_CONTROL_WIN_RE = re.compile(
    r"if you control (twenty|\d+) or more (artifacts|creatures)",
    re.IGNORECASE,
)
_COUNTER_WIN_RE = re.compile(
    r"if .* has (twenty|\d+) or more .* counters? on it, you win the game",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class StaticEffect:
    kind: str
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ActionTemplate:
    kind: str
    cost: int = 0
    roles: tuple[str, ...] = ()
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TriggerTemplate:
    window: str
    kind: str
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AltWinRule:
    window: str
    metric: str
    comparator: str
    threshold: float
    zone_scope: str = "self"


class OutcomeTier(str, Enum):
    HARD_WIN = "hard_win"
    MODEL_WIN = "model_win"
    DOMINANT = "dominant"
    NONE = "none"


@dataclass(frozen=True)
class Winline:
    kind: str
    requirements: tuple[str, ...] = ()
    support: tuple[str, ...] = ()
    sink_requirements: tuple[str, ...] = ()
    horizon_class: str = "soon"


@dataclass(frozen=True)
class OutcomeResult:
    tier: OutcomeTier
    wincon: str | None = None
    reason: str | None = None
    lock_established: bool = False
    lock_plus_clock: bool = False


@dataclass(frozen=True)
class DeckFingerprint:
    primary_plan: str
    secondary_plan: str | None = None
    commander_role: str = "value"
    speed_tier: str = "optimized"
    prefers_focus_fire: bool = True
    protection_density: float = 0.0
    resource_profile: tuple[str, ...] = ()
    conversion_profile: tuple[str, ...] = ()
    wipe_recovery: float = 0.0
    support_confidence: float = 0.0


@dataclass(frozen=True)
class CoverageSummary:
    executable: tuple[str, ...] = ()
    evaluative_only: tuple[str, ...] = ()
    unsupported: tuple[str, ...] = ()
    support_score: float = 0.0


@dataclass(frozen=True)
class CardExec:
    name: str
    oracle_id: str | None
    statics: tuple[StaticEffect, ...]
    cast_modes: tuple[ActionTemplate, ...]
    activated: tuple[ActionTemplate, ...]
    triggers: Dict[str, tuple[TriggerTemplate, ...]]
    alt_win_rules: tuple[AltWinRule, ...]
    combo_roles: tuple[str, ...]
    coverage: CoverageClass
    coverage_summary: CoverageSummary
    tags: tuple[str, ...] = ()
    strategic_weight: float = 1.0
    coverage_notes: tuple[str, ...] = ()


def _to_number(token: str | None) -> float:
    if token is None:
        return 0.0
    text = str(token).strip().lower()
    if not text:
        return 0.0
    if text.isdigit():
        return float(int(text))
    return float(_NUM_WORDS.get(text, 0))


def _normalize_tags(card: dict) -> tuple[str, ...]:
    return tuple(sorted({str(tag).strip() for tag in (card.get("tags") or []) if str(tag or "").strip()}))


def _text(card: dict) -> str:
    parts = [str(card.get("type_line") or ""), str(card.get("oracle_text") or "")]
    for face in card.get("card_faces") or []:
        parts.append(str(face.get("type_line") or ""))
        parts.append(str(face.get("oracle_text") or ""))
    return " ".join(parts).lower()


def _keywords(card: dict) -> set[str]:
    out = {str(k).lower() for k in (card.get("keywords") or [])}
    for face in card.get("card_faces") or []:
        out.update(str(k).lower() for k in (face.get("keywords") or []))
    return out


def _type_line(card: dict) -> str:
    return str(card.get("type_line") or "").lower()


def _main_types(card: dict) -> tuple[str, ...]:
    line = _type_line(card)
    return tuple(sorted(t for t in _MAIN_TYPES if t in line))


def _is_repeatable(text: str) -> bool:
    return any(marker in text for marker in ("whenever", "at the beginning of", "for each", "{t}:", "{q}:"))


def _strategic_weight(tags: tuple[str, ...], card: dict, coverage: CoverageSummary) -> float:
    weight = 1.0
    important_tags = {
        "#Ramp",
        "#Draw",
        "#Removal",
        "#Counter",
        "#Boardwipe",
        "#Protection",
        "#Tutor",
        "#Setup",
        "#Engine",
        "#Payoff",
        "#Combo",
        "#Wincon",
    }
    if any(tag in important_tags for tag in tags):
        weight += 0.8
    if any(tag in tags for tag in ("#Engine", "#Payoff", "#Combo", "#Wincon")):
        weight += 0.7
    if bool(card.get("is_commander")):
        weight += 0.5
    if coverage.unsupported:
        weight += 0.2
    return round(weight, 3)


def _coverage_class(summary: CoverageSummary) -> CoverageClass:
    if summary.executable:
        return "executable"
    if summary.evaluative_only:
        return "evaluative-only"
    return "unsupported"


def _support_score(executable: list[str], evaluative: list[str], unsupported: list[str]) -> float:
    total = len(executable) + len(evaluative) + len(unsupported)
    if total <= 0:
        return 0.0
    score = (len(executable) + 0.5 * len(evaluative)) / total
    return round(float(score), 4)


def _compile_alt_win_rules(text: str, alt_win_kind: str | None) -> tuple[list[AltWinRule], list[str]]:
    rules: list[AltWinRule] = []
    unsupported: list[str] = []
    if "you win the game" not in text and "loses the game" not in text and not alt_win_kind:
        return rules, unsupported

    upkeep_match = _UPKEEP_WIN_RE.search(text)
    if upkeep_match:
        rules.append(AltWinRule(window="upkeep", metric="life", comparator=">=", threshold=float(upkeep_match.group(1)), zone_scope="self"))
        return rules, unsupported

    control_match = _CONTROL_WIN_RE.search(text)
    if control_match:
        threshold = _to_number(control_match.group(1))
        kind = control_match.group(2).lower()
        rules.append(AltWinRule(window="upkeep", metric=f"control_{kind}", comparator=">=", threshold=threshold, zone_scope="self"))
        return rules, unsupported

    counter_match = _COUNTER_WIN_RE.search(text)
    if counter_match:
        threshold = _to_number(counter_match.group(1))
        rules.append(AltWinRule(window="upkeep", metric="counters", comparator=">=", threshold=threshold, zone_scope="self"))
        return rules, unsupported

    strict_map = {
        "life40": AltWinRule(window="upkeep", metric="life", comparator=">=", threshold=40.0, zone_scope="self"),
        "artifacts20": AltWinRule(window="upkeep", metric="control_artifacts", comparator=">=", threshold=20.0, zone_scope="self"),
        "creatures20": AltWinRule(window="upkeep", metric="control_creatures", comparator=">=", threshold=20.0, zone_scope="self"),
        "graveyard20": AltWinRule(window="upkeep", metric="graveyard_count", comparator=">=", threshold=20.0, zone_scope="self"),
        "library2": AltWinRule(window="draw", metric="library_size", comparator="<=", threshold=2.0, zone_scope="self"),
        "library0": AltWinRule(window="draw", metric="library_size", comparator="<=", threshold=0.0, zone_scope="self"),
        "hand0": AltWinRule(window="upkeep", metric="hand_size", comparator="<=", threshold=0.0, zone_scope="self"),
        "life1": AltWinRule(window="state", metric="life", comparator="==", threshold=1.0, zone_scope="self"),
    }
    if alt_win_kind in strict_map:
        rules.append(strict_map[alt_win_kind])
    else:
        unsupported.append("Unsupported alternate-win predicate.")
    return rules, unsupported


def _draw_quantity(text: str) -> int:
    total = 0
    for raw in _DRAW_RE.findall(text):
        total += int(_to_number(raw))
    return total


def _compile_card_exec(card: dict) -> CardExec:
    tags = _normalize_tags(card)
    text = _text(card)
    keywords = _keywords(card)
    type_line = _type_line(card)
    mana_value = int(card.get("mana_value", 0) or 0)
    is_creature = bool(card.get("is_creature", False))
    is_land = "land" in type_line or bool(card.get("is_land", False))
    is_permanent = bool(card.get("is_permanent", False)) or any(main == "land" for main in _main_types(card))

    statics: list[StaticEffect] = []
    cast_modes: list[ActionTemplate] = []
    activated: list[ActionTemplate] = []
    triggers: dict[str, list[TriggerTemplate]] = {}
    exec_cov: list[str] = []
    eval_cov: list[str] = []
    unsupported_cov: list[str] = []

    def add_trigger(window: str, kind: str, payload: Dict[str, Any] | None = None) -> None:
        triggers.setdefault(window, []).append(TriggerTemplate(window=window, kind=kind, payload=payload or {}))

    if is_land:
        cast_modes.append(ActionTemplate(kind="play_land", cost=0, roles=tags))
        exec_cov.append("play_land")

    if is_creature:
        cast_modes.append(ActionTemplate(kind="cast_creature", cost=mana_value, roles=tags, payload={"power": float(card.get("power") or 0.0)}))
        exec_cov.append("creature_body")
    elif is_permanent:
        cast_modes.append(ActionTemplate(kind="cast_permanent", cost=mana_value, roles=tags))
        exec_cov.append("cast_permanent")
    else:
        cast_modes.append(ActionTemplate(kind="cast_spell", cost=mana_value, roles=tags))
        eval_cov.append("cast_spell")

    produced = tuple(str(m).upper() for m in (card.get("produced_mana") or []) if str(m or "").strip())
    mana_lines = "add {" in text or "add one mana" in text
    if produced or mana_lines:
        payload = {
            "produced_mana": produced,
            "repeatable": is_permanent,
            "conditional": "only to cast" in text or "spend this mana only" in text,
            "enters_tapped": "enters tapped" in text,
            "sacrifice": "sacrifice " in text and ":" in text,
        }
        kind = "mana_source" if is_permanent else "ritual"
        if is_permanent and mana_value <= 2:
            payload["fast_mana"] = True
            exec_cov.append("fast_mana")
        if not is_permanent:
            exec_cov.append("ritual")
        else:
            exec_cov.append("mana_source")
        target_list = activated if is_permanent and ":" in text else cast_modes
        target_list.append(ActionTemplate(kind=kind, cost=mana_value, roles=tags, payload=payload))

    if "costs {" in text and "less to cast" in text:
        statics.append(StaticEffect("cost_reduction", {"amount": 1}))
        exec_cov.append("cost_reduction")

    draw_qty = _draw_quantity(text)
    if draw_qty > 0:
        action = ActionTemplate(kind="draw", cost=mana_value, roles=tags, payload={"count": draw_qty, "repeatable": _is_repeatable(text)})
        (activated if ":" in text and is_permanent else cast_modes).append(action)
        exec_cov.append("draw")
    if "draw" in text and "discard" in text:
        cast_modes.append(ActionTemplate(kind="loot", cost=mana_value, roles=tags, payload={"repeatable": _is_repeatable(text)}))
        exec_cov.append("loot")
    if "exile the top" in text and ("you may play" in text or "you may cast" in text):
        cast_modes.append(ActionTemplate(kind="impulse_draw", cost=mana_value, roles=tags))
        exec_cov.append("impulse_draw")
    if "search your library" in text:
        payload = {
            "to_hand": "into your hand" in text,
            "to_battlefield": "onto the battlefield" in text,
            "land_only": "land card" in text,
        }
        cast_modes.append(ActionTemplate(kind="tutor", cost=mana_value, roles=tags, payload=payload))
        exec_cov.append("tutor")
        if payload["land_only"] and payload["to_hand"]:
            exec_cov.append("land_to_hand")
        if payload["land_only"] and payload["to_battlefield"]:
            exec_cov.append("land_to_battlefield")

    token_power = float(card.get("token_attack_power") or 0.0)
    token_bodies = float(card.get("token_bodies") or 0.0)
    if token_bodies > 0 or "create" in text and "token" in text:
        sig = {"bodies": max(1.0, token_bodies or 1.0), "attack_power": token_power}
        cast_modes.append(ActionTemplate(kind="create_tokens", cost=mana_value, roles=tags, payload=sig))
        exec_cov.append("create_tokens")

    combat_buff = float(card.get("combat_buff") or 0.0)
    commander_buff = float(card.get("commander_buff") or 0.0)
    if combat_buff > 0:
        statics.append(StaticEffect("static_buff", {"amount": combat_buff}))
        exec_cov.append("static_buff")
    if commander_buff > 0:
        statics.append(StaticEffect("commander_buff", {"amount": commander_buff}))
        exec_cov.append("commander_buff")
    if "creatures you control have haste" in text or "gains haste" in text or "haste" in keywords:
        statics.append(StaticEffect("haste_grant", {}))
        exec_cov.append("haste_grant")
    if any(marker in text for marker in ("can't be blocked", "flying", "menace", "trample", "unblockable")):
        statics.append(StaticEffect("evasion_grant", {}))
        exec_cov.append("evasion_grant")

    if float(card.get("extra_combat_factor") or 1.0) > 1.0 or "additional combat phase" in text or "extra combat phase" in text:
        cast_modes.append(ActionTemplate(kind="extra_combat", cost=mana_value, roles=tags))
        exec_cov.append("extra_combat")
    if "untap target" in text or "untap up to" in text or "untap all" in text:
        cast_modes.append(ActionTemplate(kind="selective_untap", cost=mana_value, roles=tags))
        exec_cov.append("selective_untap")

    burn_value = float(card.get("burn_value") or 0.0)
    repeatable_burn = float(card.get("repeatable_burn") or 0.0)
    if burn_value > 0 or repeatable_burn > 0 or _DAMAGE_RE.search(text) or _LOSE_LIFE_RE.search(text):
        target = "all_opponents" if "each opponent" in text else "single"
        kind = "drain_all_opponents" if "each opponent loses" in text and "you gain" in text else ("burn_all_opponents" if target == "all_opponents" else "burn_single_target")
        target_list = activated if ":" in text and is_permanent else cast_modes
        target_list.append(ActionTemplate(kind=kind, cost=mana_value, roles=tags, payload={"repeatable": repeatable_burn > 0}))
        exec_cov.append(kind)

    mill_value = float(card.get("mill_value") or 0.0)
    repeatable_mill = float(card.get("repeatable_mill") or 0.0)
    if mill_value > 0 or repeatable_mill > 0 or _MILL_RE.search(text):
        kind = "mill_all_opponents" if "each opponent mills" in text else "mill_single_target"
        target_list = activated if ":" in text and is_permanent else cast_modes
        target_list.append(ActionTemplate(kind=kind, cost=mana_value, roles=tags, payload={"repeatable": repeatable_mill > 0}))
        exec_cov.append(kind)

    if bool(card.get("proliferate")) or "proliferate" in text:
        cast_modes.append(ActionTemplate(kind="proliferate", cost=mana_value, roles=tags))
        exec_cov.append("proliferate")

    if "sacrifice another" in text or ("sacrifice a" in text and ":" in text) or ("sacrifice another creature" in text):
        activated.append(ActionTemplate(kind="sac_outlet", cost=0, roles=tags))
        exec_cov.append("sac_outlet")

    if "enters the battlefield" in text or "whenever " in text and " enters the battlefield" in text:
        add_trigger("etb", "etb_trigger")
        exec_cov.append("etb_trigger")
    if "dies" in text:
        add_trigger("death", "death_trigger")
        exec_cov.append("death_trigger")
    if "at the beginning of your upkeep" in text or "at the beginning of upkeep" in text:
        add_trigger("upkeep", "upkeep_trigger")
        exec_cov.append("upkeep_trigger")
    if "whenever " in text and " attacks" in text or "when this creature attacks" in text:
        add_trigger("attack", "attack_trigger")
        exec_cov.append("attack_trigger")

    if "return target" in text and "from your graveyard to the battlefield" in text:
        cast_modes.append(ActionTemplate(kind="reanimation", cost=mana_value, roles=tags))
        exec_cov.append("reanimation")
    elif "return target" in text and "from your graveyard to your hand" in text:
        cast_modes.append(ActionTemplate(kind="recursion", cost=mana_value, roles=tags))
        exec_cov.append("recursion")

    if "cast" in text and "from your graveyard" in text:
        statics.append(StaticEffect("cast_from_graveyard", {}))
        exec_cov.append("cast_from_graveyard")
    if "cast" in text and "top of your library" in text:
        statics.append(StaticEffect("cast_from_top", {}))
        exec_cov.append("cast_from_top")
    if "cast" in text and "from exile" in text:
        statics.append(StaticEffect("cast_from_exile", {}))
        exec_cov.append("cast_from_exile")

    alt_rules, unsupported_alt = _compile_alt_win_rules(text, str(card.get("alt_win_kind") or "").strip() or None)
    if alt_rules:
        exec_cov.append("alt_win_rule")
    unsupported_cov.extend(unsupported_alt)

    combo_roles = tuple(sorted({tag.lstrip("#!") for tag in tags if any(marker in tag for marker in ("Combo", "Wincon", "Payoff", "Engine"))}))
    if combo_roles and not exec_cov:
        eval_cov.append("combo_shell_only")
    if any(tag in tags for tag in ("#Protection", "#Control", "#Stax")) and not any(op in exec_cov for op in ("burn_single_target", "burn_all_opponents", "drain_all_opponents", "tutor", "draw")):
        eval_cov.append("strategic_tag_only")

    unsupported_markers = {
        "cascade": "Cascade unsupported.",
        "discover": "Discover unsupported.",
        "mutate": "Mutate unsupported.",
        "venture into": "Venture/initiative unsupported.",
        "the initiative": "Initiative unsupported.",
        "planeswalker": "Planeswalker loyalty execution unsupported.",
        "copy target spell": "Spell-copy stack interaction unsupported.",
    }
    for marker, note in unsupported_markers.items():
        if marker in text:
            unsupported_cov.append(note)

    summary = CoverageSummary(
        executable=tuple(sorted(set(exec_cov))),
        evaluative_only=tuple(sorted(set(eval_cov))),
        unsupported=tuple(sorted(set(unsupported_cov))),
        support_score=_support_score(list(set(exec_cov)), list(set(eval_cov)), list(set(unsupported_cov))),
    )
    notes = tuple(sorted(set(summary.evaluative_only + summary.unsupported)))
    coverage_class = _coverage_class(summary)
    if (
        "Unsupported alternate-win predicate." in summary.unsupported
        and not alt_rules
        and any(tag in tags for tag in ("#Wincon", "#Combo", "#Payoff", "#Engine"))
    ):
        coverage_class = "evaluative-only" if summary.evaluative_only or summary.executable else "unsupported"
    return CardExec(
        name=str(card.get("name") or ""),
        oracle_id=card.get("oracle_id"),
        statics=tuple(statics),
        cast_modes=tuple(cast_modes),
        activated=tuple(activated),
        triggers={window: tuple(entries) for window, entries in triggers.items()},
        alt_win_rules=tuple(alt_rules),
        combo_roles=combo_roles,
        coverage=coverage_class,
        coverage_summary=summary,
        tags=tags,
        strategic_weight=_strategic_weight(tags, card, summary),
        coverage_notes=notes,
    )


def compile_card_execs(cards: List[dict]) -> List[CardExec]:
    return [_compile_card_exec(card) for card in cards]


def summarize_compiled_execs(compiled: List[CardExec]) -> Dict[str, Any]:
    primitive_counts: Counter[str] = Counter()
    unsupported_counts: Counter[str] = Counter()
    card_rows: list[Dict[str, Any]] = []
    weighted_total = 0.0
    weighted_supported = 0.0

    for card in compiled:
        primitive_counts.update(card.coverage_summary.executable)
        unsupported_counts.update(card.coverage_summary.unsupported)
        weighted_total += card.strategic_weight
        weighted_supported += card.strategic_weight * card.coverage_summary.support_score
        card_rows.append(
            {
                "name": card.name,
                "coverage": card.coverage,
                "support_score": card.coverage_summary.support_score,
                "strategic_weight": card.strategic_weight,
                "tags": list(card.tags),
                "executable": list(card.coverage_summary.executable),
                "evaluative_only": list(card.coverage_summary.evaluative_only),
                "unsupported": list(card.coverage_summary.unsupported),
                "combo_roles": list(card.combo_roles),
            }
        )

    important_unsupported = [
        row
        for row in sorted(card_rows, key=lambda item: (-item["strategic_weight"], item["support_score"], item["name"]))
        if row["unsupported"] or (row["strategic_weight"] >= 1.8 and row["coverage"] != "executable")
    ][:12]

    return {
        "executable": sum(1 for card in compiled if card.coverage == "executable"),
        "evaluative_only": sum(1 for card in compiled if card.coverage == "evaluative-only"),
        "unsupported": sum(1 for card in compiled if card.coverage == "unsupported"),
        "support_confidence": round((weighted_supported / weighted_total), 4) if weighted_total > 0 else 0.0,
        "primitive_totals": dict(sorted(primitive_counts.items())),
        "unsupported_effects": [
            {"effect": effect, "count": count}
            for effect, count in unsupported_counts.most_common(16)
        ],
        "important_cards": important_unsupported,
        "card_coverage": card_rows,
    }
