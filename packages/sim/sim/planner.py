from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from sim.ir import DeckFingerprint, Winline
from sim.opponents import card_salience, expected_incoming_pressure, response_probability, table_noise
from sim.state import GameState, PermanentState
from sim.tiebreak import stable_argmax, stable_sorted


INTENT_VALUES = ("develop", "assemble", "convert", "protect", "race")


@dataclass(frozen=True)
class HandPlan:
    keep: bool
    score: float
    plan: str
    commander_window: int | None
    bottomed_indices: tuple[int, ...] = ()
    bottomed: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


def _normalize_name(name: str | None) -> str:
    return (name or "").strip().lower()


def _tags(cards: Iterable[Any]) -> list[str]:
    out: list[str] = []
    for card in cards:
        out.extend(list(getattr(card, "tags", []) or []))
    return out


def _avg_mana_value(cards: Sequence[Any]) -> float:
    if not cards:
        return 0.0
    return float(sum(int(getattr(card, "mana_value", 0) or 0) for card in cards) / len(cards))


def _commander_role(commander_cards: Sequence[Any], exec_lookup: Mapping[str, Any]) -> str:
    scores = {"engine": 0.0, "payoff": 0.0, "support": 0.0, "value": 0.0}
    for card in commander_cards:
        tags = set(getattr(card, "tags", []) or [])
        card_exec = exec_lookup.get(_normalize_name(getattr(card, "name", "")))
        exec_ops = set(getattr(getattr(card_exec, "coverage_summary", None), "executable", ()) or ())
        if "#Engine" in tags or {"draw", "mana_source", "upkeep_trigger", "etb_trigger"} & exec_ops:
            scores["engine"] += 2.0
        if {"#Payoff", "#Wincon", "#Combo", "#Voltron"} & tags:
            scores["payoff"] += 2.0
        if "#Voltron" in tags or float(getattr(card, "commander_buff", 0.0) or 0.0) > 0.0:
            scores["payoff"] += 1.35
        if bool(getattr(card, "is_creature", False)) and (
            float(getattr(card, "power", 0.0) or 0.0) >= 5.0
            or float(getattr(card, "evasion_score", 0.0) or 0.0) >= 0.4
        ):
            scores["payoff"] += 0.8
        if {"#Protection", "#Control", "#Counter", "#Stax"} & tags:
            scores["support"] += 1.5
        scores["value"] += 0.5
    return max(scores.items(), key=lambda kv: (kv[1], kv[0]))[0]


def compile_deck_fingerprint(cards: Sequence[Any], commander_cards: Sequence[Any], exec_lookup: Mapping[str, Any]) -> DeckFingerprint:
    all_cards = list(cards) + list(commander_cards)
    tag_list = _tags(all_cards)
    tag_counts = {tag: tag_list.count(tag) for tag in set(tag_list)}
    creature_count = sum(1 for card in all_cards if bool(getattr(card, "is_creature", False)))
    low_curve = sum(1 for card in cards if int(getattr(card, "mana_value", 0) or 0) <= 2)
    fast_mana = tag_counts.get("#FastMana", 0) + sum(
        1
        for card in cards
        if "#Ramp" in getattr(card, "tags", []) and int(getattr(card, "mana_value", 0) or 0) <= 2
    )
    exec_summaries = [
        getattr(exec_lookup.get(_normalize_name(getattr(card, "name", ""))), "coverage_summary", None)
        for card in list(cards) + list(commander_cards)
    ]
    support_scores = [float(getattr(summary, "support_score", 0.0)) for summary in exec_summaries if summary is not None]

    combo_piece_count = tag_counts.get("#Combo", 0)
    alt_win_sources = sum(1 for card in cards if getattr(card, "alt_win_kind", None))
    alt_win_exec_count = sum(1 for card_exec in exec_lookup.values() if getattr(card_exec, "alt_win_rules", ()))
    effective_alt_win_count = max(alt_win_sources, alt_win_exec_count)

    combo_tutor_support = min(tag_counts.get("#Tutor", 0), max(0, combo_piece_count) + 1)
    combo_engine_support = min(tag_counts.get("#Engine", 0), max(0, combo_piece_count) + 1)

    commander_pressure = sum(
        max(0.0, float(getattr(card, "power", 0.0) or 0.0) - 3.0)
        + max(0.0, float(getattr(card, "evasion_score", 0.0) or 0.0) * 3.0)
        for card in commander_cards
        if bool(getattr(card, "is_creature", False))
    )
    voltron_support = (
        tag_counts.get("#Voltron", 0) * 1.5
        + sum(float(getattr(card, "commander_buff", 0.0) or 0.0) for card in cards) * 0.45
        + sum(
            max(0.0, float(getattr(card, "extra_combat_factor", 1.0) or 1.0) - 1.0)
            for card in cards
        )
    )

    plan_scores = {
        "combo": combo_piece_count * 2.2 + combo_tutor_support * 0.6 + combo_engine_support * 0.35,
        "combat": (
            creature_count * 0.18
            + tag_counts.get("#Payoff", 0) * 0.35
            + sum(float(getattr(card, "combat_buff", 0.0) or 0.0) for card in cards)
            + commander_pressure * 0.4
            + voltron_support
        ),
        "poison": sum(1 for card in cards if bool(getattr(card, "infect", False)) or float(getattr(card, "toxic", 0.0) or 0.0) > 0) * 2.2
        + sum(1 for card in cards if bool(getattr(card, "proliferate", False))) * 0.8,
        "drain": sum(1 for summary in exec_summaries if summary and any(op in summary.executable for op in ("drain_all_opponents", "burn_all_opponents", "burn_single_target"))) * 1.3,
        "mill": sum(1 for summary in exec_summaries if summary and any(op in summary.executable for op in ("mill_all_opponents", "mill_single_target"))) * 1.5,
        "alt-win": (
            effective_alt_win_count * 4.0 + tag_counts.get("#Protection", 0) * 0.2 + tag_counts.get("#Draw", 0) * 0.1
            if effective_alt_win_count > 0
            else 0.0
        ),
    }
    primary_plan = max(plan_scores.items(), key=lambda kv: (kv[1], kv[0]))[0]
    secondary_plan = None
    for name, _score in sorted(plan_scores.items(), key=lambda kv: (kv[1], kv[0]), reverse=True):
        if name != primary_plan and _score >= max(1.0, plan_scores[primary_plan] * 0.45):
            secondary_plan = name
            break

    commander_role = _commander_role(commander_cards, exec_lookup)
    if fast_mana >= 6 or (primary_plan == "combo" and tag_counts.get("#Tutor", 0) >= 4):
        speed_tier = "cedh"
    elif low_curve >= 18 or fast_mana >= 3:
        speed_tier = "optimized"
    else:
        speed_tier = "casual"

    resource_profile: list[str] = []
    if tag_counts.get("#Ramp", 0) >= 8:
        resource_profile.append("ramp")
    if tag_counts.get("#Draw", 0) >= 8:
        resource_profile.append("draw")
    if tag_counts.get("#Tutor", 0) >= 4:
        resource_profile.append("tutors")
    if not resource_profile:
        resource_profile.append("curve")

    conversion_profile: list[str] = [primary_plan]
    if secondary_plan:
        conversion_profile.append(secondary_plan)
    if tag_counts.get("#Protection", 0) + tag_counts.get("#Counter", 0) >= 5:
        conversion_profile.append("protected")

    prefers_focus_fire = primary_plan in {"combo", "poison", "drain", "alt-win"} or (
        primary_plan == "combat" and creature_count <= 18
    )

    return DeckFingerprint(
        primary_plan=primary_plan,
        secondary_plan=secondary_plan,
        commander_role=commander_role,
        speed_tier=speed_tier,
        prefers_focus_fire=prefers_focus_fire,
        protection_density=round((tag_counts.get("#Protection", 0) + tag_counts.get("#Counter", 0)) / max(1, len(cards)), 4),
        resource_profile=tuple(resource_profile),
        conversion_profile=tuple(conversion_profile),
        wipe_recovery=round((tag_counts.get("#Recursion", 0) + tag_counts.get("#Draw", 0) * 0.5) / max(1, len(cards)), 4),
        support_confidence=round(sum(support_scores) / len(support_scores), 4) if support_scores else 0.0,
    )


def compile_winlines(cards: Sequence[Any], fingerprint: DeckFingerprint) -> tuple[Winline, ...]:
    line_map = {
        "combo": Winline(kind="combo", requirements=("combo_piece", "engine"), support=("tutor", "protection"), sink_requirements=("sink",), horizon_class="now"),
        "combat": Winline(kind="combat", requirements=("board_presence", "evasion"), support=("ramp", "draw"), sink_requirements=("finisher",), horizon_class="soon"),
        "poison": Winline(kind="poison", requirements=("poison_source", "evasion"), support=("proliferate", "extra_combat"), sink_requirements=(), horizon_class="soon"),
        "drain": Winline(kind="drain", requirements=("drain_source",), support=("engine", "recursion"), sink_requirements=(), horizon_class="soon"),
        "mill": Winline(kind="mill", requirements=("mill_source",), support=("draw", "untap"), sink_requirements=(), horizon_class="grindy"),
        "alt-win": Winline(kind="alt-win", requirements=("alt_win_permanent",), support=("protection", "draw"), sink_requirements=(), horizon_class="grindy"),
    }
    winlines: list[Winline] = [line_map[fingerprint.primary_plan]]
    if fingerprint.secondary_plan and fingerprint.secondary_plan in line_map and fingerprint.secondary_plan != fingerprint.primary_plan:
        winlines.append(line_map[fingerprint.secondary_plan])
    if fingerprint.primary_plan != "combat":
        creature_count = sum(1 for card in cards if bool(getattr(card, "is_creature", False)))
        if creature_count >= 14:
            winlines.append(line_map["combat"])
    return tuple(winlines[:3])


def _board_and_hand_cards(state: GameState, hand: Sequence[Any]) -> list[Any]:
    return [perm.card for perm in state.battlefield] + list(hand)


def _requirement_score(cards: Sequence[Any], state: GameState, requirement: str) -> float:
    tags = set(_tags(cards))
    if requirement == "combo_piece":
        return 1.0 if {"#Combo", "#Wincon"} & tags else 0.0
    if requirement == "engine":
        return 1.0 if ("#Engine" in tags or state.active_engines) else 0.0
    if requirement == "tutor":
        return 1.0 if "#Tutor" in tags else 0.0
    if requirement == "protection":
        return 1.0 if {"#Protection", "#Counter"} & tags else 0.0
    if requirement == "board_presence":
        body_count = sum(1 for card in cards if bool(getattr(card, "is_creature", False))) + sum(state.token_buckets.values())
        return min(1.0, body_count / 3.0)
    if requirement == "evasion":
        return 1.0 if any(float(getattr(card, "evasion_score", 0.0) or 0.0) > 0.25 or bool(getattr(card, "has_haste", False)) for card in cards) else 0.0
    if requirement == "finisher":
        return 1.0 if {"#Payoff", "#Wincon"} & tags or any(float(getattr(card, "combat_buff", 0.0) or 0.0) >= 1.0 for card in cards) else 0.0
    if requirement == "poison_source":
        return 1.0 if any(bool(getattr(card, "infect", False)) or float(getattr(card, "toxic", 0.0) or 0.0) > 0.0 for card in cards) else 0.0
    if requirement == "proliferate":
        return 1.0 if any(bool(getattr(card, "proliferate", False)) for card in cards) else 0.0
    if requirement == "extra_combat":
        return 1.0 if any(float(getattr(card, "extra_combat_factor", 1.0) or 1.0) > 1.0 for card in cards) else 0.0
    if requirement == "drain_source":
        return 1.0 if any(float(getattr(card, "burn_value", 0.0) or 0.0) > 0 or float(getattr(card, "repeatable_burn", 0.0) or 0.0) > 0 for card in cards) else 0.0
    if requirement == "mill_source":
        return 1.0 if any(float(getattr(card, "mill_value", 0.0) or 0.0) > 0 or float(getattr(card, "repeatable_mill", 0.0) or 0.0) > 0 for card in cards) else 0.0
    if requirement == "untap":
        return 1.0 if any("untap" in str(getattr(card, "oracle_text", "")).lower() for card in cards) else 0.0
    if requirement == "sink":
        return 1.0 if {"#Payoff", "#Wincon"} & tags or any(float(getattr(card, "burn_value", 0.0) or 0.0) > 0 for card in cards) else 0.0
    if requirement == "ramp":
        return min(1.0, sum(1 for card in cards if "#Ramp" in getattr(card, "tags", [])) / 3.0)
    if requirement == "draw":
        return min(1.0, sum(1 for card in cards if "#Draw" in getattr(card, "tags", [])) / 3.0)
    if requirement == "recursion":
        return 1.0 if {"#Recursion", "#Reanimator"} & tags else 0.0
    if requirement == "alt_win_permanent":
        return 1.0 if any(getattr(card, "alt_win_kind", None) for card in cards) else 0.0
    return 0.0


def winline_distance(state: GameState, hand: Sequence[Any], winline: Winline) -> float:
    cards = _board_and_hand_cards(state, hand)
    distance = 0.0
    for requirement in winline.requirements:
        distance += max(0.0, 1.0 - _requirement_score(cards, state, requirement))
    for support in winline.support:
        distance += 0.45 * max(0.0, 1.0 - _requirement_score(cards, state, support))
    for sink in winline.sink_requirements:
        distance += 0.7 * max(0.0, 1.0 - _requirement_score(cards, state, sink))
    return round(distance, 4)


def choose_turn_intent(
    state: GameState,
    hand: Sequence[Any],
    fingerprint: DeckFingerprint,
    winlines: Sequence[Winline],
    threat_model: bool = False,
    opponent_table: Any | None = None,
) -> str:
    best_line = min(winlines or [Winline(kind=fingerprint.primary_plan)], key=lambda line: winline_distance(state, hand, line))
    best_distance = winline_distance(state, hand, best_line)
    board_presence = len(state.battlefield) + sum(state.token_buckets.values())
    if threat_model and opponent_table is not None:
        incoming_pressure = expected_incoming_pressure(opponent_table, state, state.turn)
        if state.self_life - incoming_pressure <= 10.0 and best_line.kind in {"combat", "poison", "drain"}:
            return "race"
        if board_presence >= 4 and fingerprint.protection_density > 0.05 and any(tag in _tags(hand) for tag in ("#Protection", "#Counter")):
            wipe_risk = max(
                (
                    response_probability(
                        opponent,
                        salience=min(5.0, 2.5 + board_presence * 0.35),
                        turn=state.turn,
                        table_noise_value=table_noise(opponent_table, state),
                        answer_kind="wipe",
                    )
                    for opponent in opponent_table.opponents
                ),
                default=0.0,
            )
            if wipe_risk >= 0.42:
                return "protect"
    if best_line.kind in {"combat", "poison", "drain"} and board_presence >= 4 and best_distance <= 1.0:
        return "convert" if not threat_model else "race"
    if best_distance <= 0.75:
        if threat_model and fingerprint.protection_density > 0.06 and any(tag in _tags(hand) for tag in ("#Protection", "#Counter")):
            return "protect"
        return "convert"
    if state.turn >= 5 and best_line.kind in {"combat", "poison", "drain"} and (state.active_engines or sum(state.token_buckets.values()) >= 2):
        return "race"
    if best_distance <= 1.8 or any("#Tutor" in getattr(card, "tags", []) for card in hand):
        return "assemble"
    return "develop"


def _land_tempo_tax(card: Any) -> float:
    return 0.45 if "enters tapped" in str(getattr(card, "oracle_text", "")).lower() else 0.0


def _card_plan_contribution(card: Any, fingerprint: DeckFingerprint, winlines: Sequence[Winline]) -> float:
    tags = set(getattr(card, "tags", []) or [])
    score = 0.0
    if "#Land" in tags:
        score += 1.3
    if "#Ramp" in tags or "#FastMana" in tags:
        score += 1.25
    if "#Draw" in tags:
        score += 1.0
    if "#Tutor" in tags:
        score += 1.2
    if "#Protection" in tags or "#Counter" in tags:
        score += 0.9
    if fingerprint.primary_plan == "combo" and ("#Combo" in tags or "#Wincon" in tags or "#Engine" in tags):
        score += 1.35
    if fingerprint.primary_plan == "combat" and (
        bool(getattr(card, "is_creature", False))
        or float(getattr(card, "combat_buff", 0.0) or 0.0) > 0
        or float(getattr(card, "commander_buff", 0.0) or 0.0) > 0
        or "#Voltron" in tags
    ):
        score += 1.15
    if fingerprint.primary_plan == "poison" and (bool(getattr(card, "infect", False)) or float(getattr(card, "toxic", 0.0) or 0.0) > 0 or bool(getattr(card, "proliferate", False))):
        score += 1.25
    if fingerprint.primary_plan == "drain" and (float(getattr(card, "burn_value", 0.0) or 0.0) > 0 or float(getattr(card, "repeatable_burn", 0.0) or 0.0) > 0):
        score += 1.15
    if fingerprint.primary_plan == "mill" and (float(getattr(card, "mill_value", 0.0) or 0.0) > 0 or float(getattr(card, "repeatable_mill", 0.0) or 0.0) > 0):
        score += 1.15
    if fingerprint.primary_plan == "alt-win" and getattr(card, "alt_win_kind", None):
        score += 1.25
    if any(w.kind == "combat" for w in winlines) and bool(getattr(card, "has_haste", False)):
        score += 0.2
    score -= max(0.0, int(getattr(card, "mana_value", 0) or 0) - 5) * 0.35
    score -= _land_tempo_tax(card)
    return round(score, 4)


def hand_plan(hand: Sequence[Any], fingerprint: DeckFingerprint, winlines: Sequence[Winline], colors_required: int, commander_cards: Sequence[Any], mulligans_taken: int, multiplayer: bool) -> HandPlan:
    lands = [card for card in hand if "#Land" in getattr(card, "tags", [])]
    land_count = len(lands)
    early_actions = sum(1 for card in hand if int(getattr(card, "mana_value", 0) or 0) <= 2 and {"#Ramp", "#Draw", "#Setup"} & set(getattr(card, "tags", [])))
    fixing = sum(1 for card in hand if "#Fixing" in getattr(card, "tags", []))
    clunk = sum(1 for card in hand if int(getattr(card, "mana_value", 0) or 0) >= 5)
    tapped_tax = sum(_land_tempo_tax(card) for card in lands)
    avg_mv = _avg_mana_value(hand)
    commander_window = None
    if commander_cards:
        cheapest = min(int(getattr(card, "mana_value", 0) or 0) for card in commander_cards)
        commander_window = max(2, cheapest - max(0, early_actions - 1))

    hand_state = GameState(hand=list(hand))
    best_line = min(winlines or [Winline(kind=fingerprint.primary_plan)], key=lambda line: winline_distance(hand_state, hand, line))
    line_distance = winline_distance(hand_state, hand, best_line)

    score = 0.0
    reasons: list[str] = []
    ideal_low, ideal_high = (1, 4) if fingerprint.speed_tier == "cedh" else (2, 5)
    if ideal_low <= land_count <= ideal_high:
        score += 2.2
        reasons.append("land band")
    else:
        score -= 1.6
    if colors_required >= 3:
        color_score = min(1.0, (land_count + fixing) / 3.0)
        score += color_score * 1.4
        if color_score >= 0.66:
            reasons.append("fixing")
    else:
        score += min(1.0, land_count / 2.0) * 0.8
    score += min(2.0, early_actions * 0.8)
    if early_actions:
        reasons.append("early action")
    score += max(0.0, 2.2 - line_distance)
    if line_distance <= 1.2:
        reasons.append("plan progress")
    if commander_window is not None and commander_window <= 4:
        score += 0.8 if fingerprint.commander_role in {"engine", "support"} else 0.4
    score -= clunk * 0.45
    score -= tapped_tax
    if avg_mv <= 3.2:
        score += 0.35
    if fingerprint.speed_tier == "cedh" and land_count == 1 and any("#FastMana" in getattr(card, "tags", []) for card in hand) and early_actions:
        score += 1.1
    threshold = {"cedh": 3.8, "optimized": 3.4, "casual": 3.0}.get(fingerprint.speed_tier, 3.2) - min(0.9, mulligans_taken * 0.35)
    keep = score >= threshold

    bottom_count = mulligans_taken
    if multiplayer and mulligans_taken == 1:
        bottom_count = 0
    indexed_hand = list(enumerate(hand))
    ranked = stable_sorted(
        indexed_hand,
        key=lambda pair: (
            _card_plan_contribution(pair[1], fingerprint, winlines),
            -int(getattr(pair[1], "mana_value", 0) or 0),
            getattr(pair[1], "name", ""),
        ),
    )
    keep_count = max(0, len(hand) - bottom_count)
    keep_indices = {idx for idx, _card in ranked[-keep_count:]} if bottom_count else set(range(len(hand)))
    bottomed_indices = tuple(idx for idx in range(len(hand)) if idx not in keep_indices)
    bottomed = tuple(getattr(hand[idx], "name", "") for idx in bottomed_indices)
    return HandPlan(
        keep=keep,
        score=round(score, 4),
        plan=best_line.kind,
        commander_window=commander_window,
        bottomed_indices=bottomed_indices,
        bottomed=bottomed,
        reasons=tuple(reasons),
    )


def _two_turn_commander_value(card: Any, card_exec: Any, fingerprint: DeckFingerprint) -> float:
    exec_ops = set(getattr(getattr(card_exec, "coverage_summary", None), "executable", ()) or ())
    value = 0.6
    if fingerprint.commander_role == "engine":
        value += 1.5
    if fingerprint.commander_role == "support":
        value += 0.9
    if fingerprint.commander_role == "payoff":
        value += 1.0
    value += 0.7 if {"draw", "mana_source", "etb_trigger", "upkeep_trigger", "attack_trigger"} & exec_ops else 0.0
    value += 0.25 if bool(getattr(card, "is_creature", False)) and (bool(getattr(card, "has_haste", False)) or float(getattr(card, "evasion_score", 0.0) or 0.0) > 0.2) else 0.0
    if "#Voltron" in set(getattr(card, "tags", []) or []):
        value += 0.75
    if float(getattr(card, "power", 0.0) or 0.0) >= 5.0:
        value += 0.45
    return round(value, 4)


def _card_immediate_value(card: Any, card_exec: Any, intent: str, fingerprint: DeckFingerprint, state: GameState, winlines: Sequence[Winline]) -> float:
    tags = set(getattr(card, "tags", []) or [])
    exec_ops = set(getattr(getattr(card_exec, "coverage_summary", None), "executable", ()) or ())
    value = 0.0
    if "#Land" in tags:
        value += 1.0 - _land_tempo_tax(card)
    if {"#Ramp", "#FastMana"} & tags:
        value += 1.4 if intent in {"develop", "assemble"} else 0.7
    if "#Draw" in tags:
        weak_hand = len(state.hand) <= 4 or sum(1 for c in state.hand if int(getattr(c, "mana_value", 0) or 0) <= 2) <= 1
        value += 1.25 if weak_hand or intent == "assemble" else 0.75
    if "#Tutor" in tags or "tutor" in exec_ops:
        value += 1.6 if intent in {"assemble", "convert"} else 0.9
    if {"#Protection", "#Counter"} & tags:
        value += 1.4 if intent in {"protect", "convert"} else 0.25
    if {"#Payoff", "#Wincon"} & tags:
        value += 1.35 if intent in {"convert", "race"} else 0.45
    if "#Voltron" in tags or float(getattr(card, "commander_buff", 0.0) or 0.0) > 0.0:
        value += 1.4 if intent in {"assemble", "convert", "race"} else 0.55
    if "#Engine" in tags:
        value += 1.2 if intent in {"develop", "assemble"} else 0.55
    if "create_tokens" in exec_ops and fingerprint.primary_plan in {"combat", "drain"}:
        value += 0.9
    if "extra_combat" in exec_ops and intent in {"convert", "race"}:
        value += 1.2
    if "proliferate" in exec_ops and fingerprint.primary_plan == "poison":
        value += 1.0
    if bool(getattr(card, "is_creature", False)) and intent == "race":
        value += 0.4 + float(getattr(card, "evasion_score", 0.0) or 0.0)
    value -= max(0, int(getattr(card, "mana_value", 0) or 0) - 5) * 0.3
    return round(value, 4)


def _projected_distance_delta(state: GameState, hand: Sequence[Any], action_card: Any, winlines: Sequence[Winline]) -> float:
    before = min((winline_distance(state, hand, line) for line in winlines), default=0.0)
    projected_hand = [card for card in hand if card is not action_card]
    projected_state = GameState(
        hand=list(projected_hand),
        battlefield=list(state.battlefield),
        token_buckets=dict(state.token_buckets),
        active_engines=set(state.active_engines),
        active_locks=set(state.active_locks),
    )
    if "#Land" not in getattr(action_card, "tags", []):
        projected_state.battlefield.append(PermanentState(permanent_id=-1, card=action_card, card_exec=None))
    after = min((winline_distance(projected_state, projected_hand, line) for line in winlines), default=0.0)
    return round(max(0.0, before - after), 4)


def choose_best_action(
    *,
    state: GameState,
    hand: Sequence[Any],
    commander_cards: Sequence[Any],
    commander_live_names: set[str],
    commander_index: Mapping[str, int] | None,
    exec_lookup: Mapping[str, Any],
    intent: str,
    fingerprint: DeckFingerprint,
    winlines: Sequence[Winline],
    threat_model: bool,
    opponent_table: Any | None = None,
) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    noise = table_noise(opponent_table, state) if threat_model and opponent_table is not None else 0.0

    if state.lands_played_this_turn < (1 + state.extra_land_plays):
        for idx, card in enumerate(hand):
            if "#Land" not in getattr(card, "tags", []):
                continue
            untapped_bonus = 0.2 if "enters tapped" not in str(getattr(card, "oracle_text", "")).lower() else -0.25
            fixing_bonus = 0.25 if "#Fixing" in getattr(card, "tags", []) else 0.0
            candidates.append(
                {
                    "type": "land",
                    "index": idx,
                    "card": card,
                    "score": 1.0 + untapped_bonus + fixing_bonus,
                    "distance": 0.1 + fixing_bonus,
                    "efficiency": 1.0,
                    "exposure": 0.0,
                }
            )

    potential_mana = int(state.mana_state.floating) + sum(1 for perm in state.battlefield if not perm.tapped and ("#Land" in getattr(perm.card, "tags", []) or "#Ramp" in getattr(perm.card, "tags", [])))
    for idx, card in enumerate(hand):
        if "#Land" in getattr(card, "tags", []):
            continue
        mv = int(getattr(card, "mana_value", 0) or 0)
        if mv > potential_mana:
            continue
        card_exec = exec_lookup.get(_normalize_name(getattr(card, "name", "")))
        if card_exec is None:
            continue
        immediate = _card_immediate_value(card, card_exec, intent, fingerprint, state, winlines)
        distance = _projected_distance_delta(state, hand, card, winlines)
        efficiency = round(max(0.0, 1.8 - 0.15 * mv), 4)
        exposure = 0.45 if threat_model and {"#Payoff", "#Wincon", "#Combo"} & set(getattr(card, "tags", [])) and intent != "convert" else 0.0
        if threat_model and opponent_table is not None:
            salience = card_salience(card, is_commander=False)
            hazard = max(
                (
                    max(
                        response_probability(opponent, salience=salience, turn=state.turn, table_noise_value=noise, answer_kind="counter"),
                        response_probability(opponent, salience=salience, turn=state.turn, table_noise_value=noise, answer_kind="spot_removal"),
                    )
                    for opponent in opponent_table.opponents
                ),
                default=0.0,
            )
            exposure += 0.65 * hazard
        candidates.append(
            {
                "type": "cast",
                "index": idx,
                "card": card,
                "card_exec": card_exec,
                "score": immediate + 0.55 * distance + 0.2 * efficiency - exposure,
                "distance": distance,
                "efficiency": efficiency,
                "exposure": exposure,
            }
        )

    for card in commander_cards:
        key = _normalize_name(getattr(card, "name", ""))
        if key in commander_live_names:
            continue
        card_exec = exec_lookup.get(key)
        if card_exec is None:
            continue
        slot = commander_index.get(key) if commander_index is not None else None
        cmd_cost = int(getattr(card, "mana_value", 0) or 0) + (state.commander_tax[slot] if slot is not None else 0)
        if cmd_cost > potential_mana:
            continue
        candidates.append(
            {
                "type": "commander",
                "card": card,
                "card_exec": card_exec,
                "score": _two_turn_commander_value(card, card_exec, fingerprint) + (0.4 if intent in {"develop", "assemble"} else 0.0),
                "distance": 0.5 if fingerprint.commander_role in {"engine", "support"} else 0.15,
                "efficiency": max(0.0, 1.4 - 0.12 * int(getattr(card, "mana_value", 0) or 0)),
                "exposure": (
                    0.25 if threat_model and fingerprint.commander_role == "payoff" and intent != "convert" else 0.0
                ) + (
                    0.75
                    * max(
                        (
                            max(
                                response_probability(opponent, salience=card_salience(card, is_commander=True), turn=state.turn, table_noise_value=noise, answer_kind="counter"),
                                response_probability(opponent, salience=card_salience(card, is_commander=True), turn=state.turn, table_noise_value=noise, answer_kind="spot_removal"),
                            )
                            for opponent in (opponent_table.opponents if threat_model and opponent_table is not None else ())
                        ),
                        default=0.0,
                    )
                ),
            }
        )

    for permanent in state.battlefield:
        if permanent.used_this_turn:
            continue
        for action in getattr(getattr(permanent, "card_exec", None), "activated", ()) or ():
            if action.kind == "mana_source":
                continue
            if action.kind == "sac_outlet":
                has_fodder = bool(state.token_buckets) or any(
                    perm.card.is_creature and not perm.card.is_commander and perm.permanent_id != permanent.permanent_id
                    for perm in state.battlefield
                )
                if not has_fodder:
                    continue
            immediate = 1.0 if action.kind in {"draw", "tutor", "sac_outlet"} else 0.6
            if action.kind in {"extra_combat", "proliferate"} and intent in {"convert", "race"}:
                immediate += 0.8
            if threat_model and opponent_table is not None and action.kind in {"draw", "tutor", "extra_combat"}:
                immediate -= 0.25 * max(
                    (
                        response_probability(opponent, salience=2.8, turn=state.turn, table_noise_value=noise, answer_kind="spot_removal")
                        for opponent in opponent_table.opponents
                    ),
                    default=0.0,
                )
            candidates.append(
                {
                    "type": "activate",
                    "permanent": permanent,
                    "effect_kind": action.kind,
                    "score": immediate,
                    "distance": 0.35 if action.kind in {"draw", "tutor", "extra_combat", "proliferate"} else 0.1,
                    "efficiency": 0.8,
                    "exposure": 0.0,
                }
            )

    best = stable_argmax(
        candidates,
        key=lambda candidate: (
            round(float(candidate["score"]), 6),
            round(float(candidate["distance"]), 6),
            round(float(candidate["efficiency"]), 6),
            -round(float(candidate["exposure"]), 6),
            -int(getattr(candidate.get("card") or getattr(candidate.get("permanent"), "card", None), "mana_value", 0) or 0),
            str(getattr(candidate.get("card") or getattr(candidate.get("permanent"), "card", None), "name", "")),
        ),
    )
    return best
