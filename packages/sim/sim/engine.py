from __future__ import annotations

import random
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from statistics import median
from typing import Any, Dict, List, Tuple

from sim.config import (
    MAX_COMMANDERS,
    ResolvedSimConfig,
    coerce_resolved_sim_config,
    normalize_selected_wincons,
)
from sim.ir import DeckFingerprint, OutcomeResult, OutcomeTier, Winline, compile_card_execs, summarize_compiled_execs
from sim.opponents import (
    VirtualTable,
    blocker_budget_vector,
    card_salience,
    expected_incoming_pressure,
    live_indices,
    maybe_counter_spell,
    maybe_remove_permanent,
    maybe_wipe_event,
    sample_virtual_table,
)
from sim.planner import (
    choose_best_action,
    choose_turn_intent,
    compile_deck_fingerprint,
    compile_winlines,
    hand_plan,
    winline_distance,
)
from sim.rng import RNGManager
from sim.state import GameState, PermanentState, TokenSig, TriggerInstance
from sim.tiebreak import stable_sorted


@dataclass
class Card:
    name: str
    tags: List[str] = field(default_factory=list)
    mana_value: int = 2
    type_line: str = ""
    oracle_text: str = ""
    keywords: List[str] = field(default_factory=list)
    power: float = 0.0
    toughness: float = 0.0
    is_creature: bool = False
    is_permanent: bool = False
    has_haste: bool = False
    is_commander: bool = False
    evasion_score: float = 0.0
    combat_buff: float = 0.0
    commander_buff: float = 0.0
    token_attack_power: float = 0.0
    token_bodies: float = 0.0
    extra_combat_factor: float = 1.0
    infect: bool = False
    toxic: float = 0.0
    proliferate: bool = False
    burn_value: float = 0.0
    repeatable_burn: float = 0.0
    mill_value: float = 0.0
    repeatable_mill: float = 0.0
    alt_win_kind: str | None = None


@dataclass
class RunMetrics:
    mana_by_turn: List[int]
    lands_by_turn: List[int]
    colors_by_turn: List[int]
    actions_by_turn: List[int]
    phase_by_turn: List[str]
    mulligans_taken: int
    commander_cast_turn: int | None
    cards_seen: int
    ramp_online_turn: int | None
    draw_engine_turn: int | None
    dead_cards: List[str]
    plan_progress_by_turn: List[float]
    seen_cards: set[str]
    cast_cards: set[str]
    win_turn: int | None
    achieved_wincon: str | None
    win_reason: str | None
    outcome_tier: str = OutcomeTier.NONE.value
    model_win_reason: str | None = None
    lock_established: bool = False
    lock_plus_clock: bool = False
    opponent_archetypes: List[str] = field(default_factory=list)
    interaction_encountered: Dict[str, int] = field(default_factory=dict)
    answer_expenditure: Dict[str, int] = field(default_factory=dict)
    wipe_turns: List[int] = field(default_factory=list)
    self_life: float = 40.0
    trace: Dict | None = None


def _normalize_name(name: str | None) -> str:
    return (name or "").strip().lower()


def _commander_names(commander: str | List[str] | None) -> List[str]:
    if isinstance(commander, list):
        return [str(name).strip() for name in commander if str(name or "").strip()]
    if commander and str(commander).strip():
        return [str(commander).strip()]
    return []


def _build_sim_deck(cards: List[dict], commander: str | List[str] | None) -> tuple[List[Card], List[Card]]:
    commander_keys = {_normalize_name(name) for name in _commander_names(commander)}
    commander_cards: List[Card] = []
    deck: List[Card] = []

    for c in cards:
        qty = int(c.get("qty", 1))
        card = Card(
            name=c["name"],
            tags=c.get("tags", []),
            mana_value=c.get("mana_value", 2),
            type_line=str(c.get("type_line") or ""),
            oracle_text=str(c.get("oracle_text") or ""),
            keywords=list(c.get("keywords") or []),
            power=float(c.get("power") or 0.0),
            toughness=float(c.get("toughness") or 0.0),
            is_creature=bool(c.get("is_creature", False)),
            is_permanent=bool(c.get("is_permanent", False)),
            has_haste=bool(c.get("has_haste", False)),
            is_commander=bool(c.get("is_commander", False)),
            evasion_score=float(c.get("evasion_score") or 0.0),
            combat_buff=float(c.get("combat_buff") or 0.0),
            commander_buff=float(c.get("commander_buff") or 0.0),
            token_attack_power=float(c.get("token_attack_power") or 0.0),
            token_bodies=float(c.get("token_bodies") or 0.0),
            extra_combat_factor=float(c.get("extra_combat_factor") or 1.0),
            infect=bool(c.get("infect", False)),
            toxic=float(c.get("toxic") or 0.0),
            proliferate=bool(c.get("proliferate", False)),
            burn_value=float(c.get("burn_value") or 0.0),
            repeatable_burn=float(c.get("repeatable_burn") or 0.0),
            mill_value=float(c.get("mill_value") or 0.0),
            repeatable_mill=float(c.get("repeatable_mill") or 0.0),
            alt_win_kind=c.get("alt_win_kind"),
        )
        section = str(c.get("section", "deck") or "deck").strip().lower()
        is_commander = section == "commander" or _normalize_name(c.get("name")) in commander_keys

        if is_commander and (section == "commander" or not any(existing.name == card.name for existing in commander_cards)):
            commander_cards.append(card)
            if section != "deck":
                continue
        if section != "deck":
            continue
        if is_commander:
            continue
        for _ in range(max(1, qty)):
            deck.append(
                Card(
                    name=card.name,
                    tags=list(card.tags),
                    mana_value=card.mana_value,
                    type_line=card.type_line,
                    oracle_text=card.oracle_text,
                    keywords=list(card.keywords),
                    power=card.power,
                    toughness=card.toughness,
                    is_creature=card.is_creature,
                    is_permanent=card.is_permanent,
                    has_haste=card.has_haste,
                    is_commander=card.is_commander,
                    evasion_score=card.evasion_score,
                    combat_buff=card.combat_buff,
                    commander_buff=card.commander_buff,
                    token_attack_power=card.token_attack_power,
                    token_bodies=card.token_bodies,
                    extra_combat_factor=card.extra_combat_factor,
                    infect=card.infect,
                    toxic=card.toxic,
                    proliferate=card.proliferate,
                    burn_value=card.burn_value,
                    repeatable_burn=card.repeatable_burn,
                    mill_value=card.mill_value,
                    repeatable_mill=card.repeatable_mill,
                    alt_win_kind=card.alt_win_kind,
                )
            )

    return deck, commander_cards


def _normalize_combo_variants(combo_variants: List[Dict] | None) -> List[Dict]:
    def infer_result_class(recipe: str) -> tuple[str, tuple[str, ...]]:
        text = recipe.lower()
        if "near-infinite" in text:
            return "near_infinite", ()
        if "win the game" in text:
            return "alt_win", ()
        if "infinite damage" in text or "infinite lifeloss" in text or "infinite life loss" in text:
            return "table_kill", ()
        if "infinite mill" in text:
            return "mill_table", ()
        if "infinite mana" in text:
            return "infinite_mana", ("sink",)
        if "infinite proliferate" in text:
            return "infinite_proliferate", ("poison_seed",)
        if "infinite combat" in text or "infinite combats" in text:
            return "combat_loop", ()
        if "infinite tokens" in text:
            return "infinite_tokens", ()
        return "engine_loop", ()

    normalized: List[Dict] = []
    for variant in combo_variants or []:
        raw_cards = variant.get("cards") or []
        cards = []
        keys = set()
        for name in raw_cards:
            key = _normalize_name(str(name))
            if not key:
                continue
            keys.add(key)
            cards.append(str(name).strip())
        if not keys:
            continue
        recipe = str(variant.get("recipe") or variant.get("description") or "").strip()
        result_class, sink_requirements = infer_result_class(recipe)
        normalized.append(
            {
                "variant_id": str(variant.get("variant_id") or ""),
                "cards": cards,
                "keys": keys,
                "recipe": recipe,
                "prerequisites": tuple(str(item).strip() for item in (variant.get("prerequisites") or ()) if str(item or "").strip()),
                "initial_state": tuple(str(item).strip() for item in (variant.get("initial_state") or ()) if str(item or "").strip()),
                "activation_needs": tuple(str(item).strip() for item in (variant.get("activation_needs") or ()) if str(item or "").strip()),
                "mana_needed": int(variant.get("mana_needed") or 0),
                "result_class": result_class,
                "sink_requirements": sink_requirements,
            }
        )
    return normalized


def _opponent_alive(state: GameState, opponent_idx: int) -> bool:
    return (
        state.opp_life[opponent_idx] > 0
        and state.opp_poison[opponent_idx] < 10
        and all(state.opp_cmdr_dmg[slot][opponent_idx] < 21 for slot in range(MAX_COMMANDERS))
        and state.opp_library[opponent_idx] > 0
    )


def _has_combo_sink(state: GameState) -> bool:
    cards = [perm.card for perm in state.battlefield] + list(state.hand)
    for card in cards:
        tags = set(getattr(card, "tags", []) or [])
        if {"#Payoff", "#Wincon"} & tags:
            return True
        if any(
            float(getattr(card, attr, 0.0) or 0.0) > 0
            for attr in ("burn_value", "repeatable_burn", "mill_value", "repeatable_mill")
        ):
            return True
        if getattr(card, "alt_win_kind", None):
            return True
    return False


def _live_combo_variant(
    state: GameState,
    combo_variants: List[Dict],
    commanders: str | List[str] | None,
    commander_live_names: set[str],
) -> Dict[str, Any] | None:
    if not combo_variants:
        return None
    live_cards = {_normalize_name(perm.card.name) for perm in state.battlefield}
    for commander_name in _commander_names(commanders):
        if _normalize_name(commander_name) in commander_live_names:
            live_cards.add(_normalize_name(commander_name))
    for variant in combo_variants:
        if variant["keys"].issubset(live_cards):
            return variant
    return None


def _combo_hard_win(state: GameState, combo_variant: Dict[str, Any] | None) -> tuple[str | None, str | None]:
    if not combo_variant:
        return None, None
    result_class = str(combo_variant.get("result_class") or "")
    recipe = str(combo_variant.get("recipe") or "").strip()
    generic_reason = recipe or "All required cards for the CommanderSpellbook combo are live."
    if not result_class:
        if combo_variant.get("keys") or combo_variant.get("cards"):
            return "Combo", generic_reason
        return None, None
    if result_class == "near_infinite":
        return None, None
    if result_class == "engine_loop":
        if not recipe and (combo_variant.get("keys") or combo_variant.get("cards")):
            return "Combo", generic_reason
        return None, None
    if result_class == "infinite_mana" and not _has_combo_sink(state):
        return None, None
    if result_class == "infinite_proliferate" and not all(poison > 0 for poison in state.opp_poison):
        return None, None
    if result_class in {"table_kill", "mill_table", "alt_win", "combat_loop"}:
        return "Combo", recipe or "A fully live combo line deterministically ends the game."
    if result_class == "infinite_mana":
        return "Combo", recipe or "Infinite mana plus a live sink deterministically ends the game."
    if result_class == "infinite_proliferate":
        return "Combo", recipe or "Infinite proliferate with poison already seeded kills the table."
    if result_class == "infinite_tokens":
        return None, None
    return None, None


def _shell_combo_model_win(state: GameState, fingerprint, combo_variant: Dict[str, Any] | None) -> str | None:
    if combo_variant is not None:
        result_class = str(combo_variant.get("result_class") or "")
        if result_class in {"infinite_tokens", "engine_loop", "near_infinite"}:
            return combo_variant.get("recipe") or "A combo shell is fully live but does not yet cash out deterministically."
    tags = Counter(tag for perm in state.battlefield for tag in getattr(perm.card, "tags", []) or [])
    if fingerprint.primary_plan != "combo":
        return None
    if tags.get("#Sacrifice", 0) >= 1 and tags.get("#Payoff", 0) >= 1 and (tags.get("#Tokens", 0) >= 1 or tags.get("#Recursion", 0) >= 1):
        return "Aristocrats shell is online but not yet deterministic."
    if tags.get("#Artifacts", 0) >= 4 and len(state.active_engines) >= 1 and (tags.get("#Payoff", 0) >= 1 or tags.get("#Combo", 0) >= 1):
        return "Artifact engine shell is online but not yet deterministic."
    if tags.get("#Reanimator", 0) >= 1 and tags.get("#Recursion", 0) >= 1 and (tags.get("#Payoff", 0) >= 1 or tags.get("#Combo", 0) >= 1):
        return "Graveyard combo shell is online but not yet deterministic."
    return None


def _evaluate_alt_win_window(state: GameState, current_window: str) -> tuple[str | None, str | None]:
    artifact_count = sum(1 for perm in state.battlefield if "artifact" in perm.card.type_line.lower())
    creature_count = sum(1 for perm in state.battlefield if perm.card.is_creature) + int(sum(state.token_buckets.values()))
    for permanent in state.battlefield:
        for rule in permanent.card_exec.alt_win_rules:
            if rule.window != current_window:
                continue
            metric_value = 0.0
            if rule.metric == "life":
                metric_value = 40.0
            elif rule.metric == "control_artifacts":
                metric_value = float(artifact_count)
            elif rule.metric == "control_creatures":
                metric_value = float(creature_count)
            elif rule.metric == "graveyard_count":
                metric_value = float(len(state.graveyard))
            elif rule.metric == "library_size":
                metric_value = float(state.library_pos)
            elif rule.metric == "hand_size":
                metric_value = float(len(state.hand))
            elif rule.metric == "counters":
                metric_value = float(sum(sum(counters.values()) for counters in state.permanent_counters.values()))
            else:
                continue
            passed = False
            if rule.comparator == ">=":
                passed = metric_value >= rule.threshold
            elif rule.comparator == "<=":
                passed = metric_value <= rule.threshold
            elif rule.comparator == "==":
                passed = metric_value == rule.threshold
            if passed:
                return "Alt Win", f"{permanent.card.name} satisfied its registered alternate-win predicate during {current_window}."
    return None, None


def _is_land(card: Card) -> bool:
    return "#Land" in card.tags


def _is_fast_mana(card: Card) -> bool:
    return "#FastMana" in card.tags or "#Ramp" in card.tags and card.mana_value <= 2


def _is_early_action(card: Card) -> bool:
    return card.mana_value <= 2 and any(t in card.tags for t in ["#Ramp", "#Draw", "#Setup"])


def _keep_hand(hand: List[Card], policy: str, colors_required: int) -> bool:
    lands = sum(1 for card in hand if _is_land(card))
    fixing = sum(1 for card in hand if "#Fixing" in card.tags)
    early_actions = sum(1 for card in hand if _is_early_action(card))
    if policy == "optimized":
        return 2 <= lands <= 4 and (fixing >= max(0, colors_required - 1) or early_actions >= 1)
    if policy == "commander-centric":
        return 2 <= lands <= 5
    if policy == "hold-commander":
        return 3 <= lands <= 5
    return 2 <= lands <= 5


def _fallback_bottom_indices(hand7: List[Card], bottoms: int) -> Tuple[int, ...]:
    ordering = stable_sorted(
        list(range(len(hand7))),
        key=lambda idx: (
            0 if _is_land(hand7[idx]) else 1,
            hand7[idx].mana_value,
            hand7[idx].name,
            idx,
        ),
    )
    if bottoms <= 0:
        return ()
    return tuple(ordering[-bottoms:])


def london_mulligan(
    deck: List[Card],
    policy: str,
    multiplayer: bool,
    rng: random.Random,
    colors_required: int,
    commander_cards: List[Card] | None = None,
    fingerprint=None,
    winlines=None,
    capture_log: bool = False,
    rng_manager: RNGManager | None = None,
) -> tuple[list[Card], int] | tuple[list[Card], int, List[Dict]]:
    fallback_fingerprint = fingerprint
    fallback_winlines = tuple(winlines or ())
    if fallback_fingerprint is None:
        resolved_policy = _policy_alias(policy, 3)
        fallback_fingerprint = DeckFingerprint(
            primary_plan="combat",
            commander_role="value",
            speed_tier="cedh" if resolved_policy == "optimized" and colors_required <= 2 else "optimized",
            prefers_focus_fire=False,
            resource_profile=("curve",),
            conversion_profile=("combat",),
        )
        fallback_winlines = (Winline(kind=fallback_fingerprint.primary_plan),)

    def finalize_hand(hand7: List[Card], bottoms: int, bottomed_indices: Tuple[int, ...], plan_bottomed: Tuple[str, ...]) -> tuple[List[Card], List[Card]]:
        keep_count = max(0, len(hand7) - bottoms)
        effective_indices = bottomed_indices[:bottoms] if bottomed_indices else _fallback_bottom_indices(hand7, bottoms)
        bottom_index_set = set(effective_indices)
        keep_indices = [idx for idx in range(len(hand7)) if idx not in bottom_index_set][:keep_count]
        hand = [hand7[idx] for idx in keep_indices]
        bottomed_cards = [card for idx, card in enumerate(hand7) if idx in bottom_index_set]
        if capture_log and steps:
            steps[-1]["bottom_count"] = bottoms
            if plan_bottomed:
                steps[-1]["bottomed"] = list(plan_bottomed[:bottoms])
            else:
                steps[-1]["bottomed"] = [hand7[idx].name for idx in effective_indices]
            steps[-1]["kept_hand"] = [c.name for c in hand]
        return hand, bottomed_cards

    mulligans = 0
    steps: List[Dict] = []
    while True:
        if rng_manager is not None:
            order = rng_manager.permutation("mulligan", len(deck), mulligans)
            deck[:] = [deck[int(idx)] for idx in order.tolist()]
        else:
            rng.shuffle(deck)
        hand7 = deck[:7]
        plan = hand_plan(
            hand7,
            fingerprint=fallback_fingerprint,
            winlines=fallback_winlines,
            colors_required=colors_required,
            commander_cards=commander_cards or [],
            mulligans_taken=mulligans,
            multiplayer=multiplayer,
        )
        keep = plan.keep if fingerprint is not None else (plan.keep and _keep_hand(hand7, policy, colors_required))
        bottomed_indices = plan.bottomed_indices or _fallback_bottom_indices(hand7, mulligans)
        plan_bottomed = plan.bottomed or tuple(hand7[idx].name for idx in bottomed_indices)
        plan_score = plan.score
        plan_name = plan.plan if fingerprint is not None else "fallback_keep"
        plan_reasons = list(plan.reasons)
        if fingerprint is None:
            plan_reasons.append("Fallback mulligan fingerprint used because no deck fingerprint was provided.")
        if capture_log:
            steps.append(
                {
                    "attempt": mulligans,
                    "hand": [c.name for c in hand7],
                    "kept": keep,
                    "score": plan_score,
                    "plan": plan_name,
                    "reasons": plan_reasons,
                }
            )
        if keep:
            bottoms = mulligans
            if multiplayer and mulligans == 1:
                bottoms = 0
            hand, bottomed_cards = finalize_hand(hand7, bottoms, bottomed_indices, plan_bottomed)
            deck[:] = list(hand) + list(deck[7:]) + bottomed_cards
            if capture_log:
                return hand, mulligans, steps
            return hand, mulligans
        mulligans += 1
        if mulligans >= 3:
            bottoms = mulligans
            if multiplayer and mulligans == 1:
                bottoms = 0
            hand, bottomed_cards = finalize_hand(hand7, bottoms, bottomed_indices, plan_bottomed)
            deck[:] = list(hand) + list(deck[7:]) + bottomed_cards
            if capture_log:
                return hand, mulligans, steps
            return hand, mulligans


def _policy_alias(policy: str, bracket: int) -> str:
    return coerce_resolved_sim_config(
        None,
        commander=None,
        requested_policy=policy,
        bracket=bracket,
        turn_limit=8,
        multiplayer=True,
        threat_model=False,
        primary_wincons=None,
        color_identity_size=0,
        seed=42,
    ).policy.resolved_policy


def _normalize_wincons(primary_wincons: List[str] | None) -> List[str]:
    return list(normalize_selected_wincons(primary_wincons))


def _lock_status(state: GameState, fingerprint, opponent_table: VirtualTable) -> tuple[bool, bool]:
    live = live_indices(opponent_table, state)
    live_budget = sum(
        opponent_table.opponents[idx].remaining_counter + opponent_table.opponents[idx].remaining_spot_removal
        for idx in live
    )
    lock_established = len(state.active_locks) >= max(1, live_budget)
    pressure = state.combat_damage_total + state.burn_total + state.mill_total * 0.6 + sum(state.opp_poison)
    lock_plus_clock = lock_established and pressure >= 18.0
    if fingerprint.primary_plan in {"control", "alt-win"}:
        lock_plus_clock = lock_plus_clock or (lock_established and len(state.active_engines) >= 1)
    return lock_established, lock_plus_clock


def _evaluate_outcome(
    *,
    state: GameState,
    selected_wincons: List[str],
    fingerprint,
    opponent_table: VirtualTable,
    current_window: str,
    combat_snapshot: Dict[str, Any] | None,
    commanders: str | List[str] | None,
    combo_variants: List[Dict] | None,
    combo_source_live: bool,
    commander_live_names: set[str],
) -> OutcomeResult:
    live_variant = _live_combo_variant(state, combo_variants or [], commanders, commander_live_names) if combo_source_live else None
    lock_established, lock_plus_clock = _lock_status(state, fingerprint, opponent_table)

    if "Alt Win" in selected_wincons:
        alt_wincon, alt_reason = _evaluate_alt_win_window(state, current_window)
        if alt_wincon:
            return OutcomeResult(OutcomeTier.HARD_WIN, wincon=alt_wincon, reason=alt_reason, lock_established=lock_established, lock_plus_clock=lock_plus_clock)

    if "Combo" in selected_wincons:
        combo_wincon, combo_reason = _combo_hard_win(state, live_variant)
        if combo_wincon:
            return OutcomeResult(OutcomeTier.HARD_WIN, wincon=combo_wincon, reason=combo_reason, lock_established=lock_established, lock_plus_clock=lock_plus_clock)

    all_dead_by_burn = all(life <= 0 for life in state.opp_life)
    all_dead_by_poison = all(poison >= 10 for poison in state.opp_poison)
    all_dead_by_mill = all(size <= 0 for size in state.opp_library)
    all_dead_by_commander = all(any(state.opp_cmdr_dmg[slot][opp_idx] >= 21 for slot in range(MAX_COMMANDERS)) for opp_idx in range(3))
    if "Drain/Burn" in selected_wincons and all_dead_by_burn:
        return OutcomeResult(OutcomeTier.HARD_WIN, wincon="Drain/Burn", reason="All opponents were reduced to zero life by noncombat damage or drain.", lock_established=lock_established, lock_plus_clock=lock_plus_clock)
    if "Poison" in selected_wincons and all_dead_by_poison:
        return OutcomeResult(OutcomeTier.HARD_WIN, wincon="Poison", reason="All opponents reached ten or more poison counters.", lock_established=lock_established, lock_plus_clock=lock_plus_clock)
    if "Mill" in selected_wincons and all_dead_by_mill:
        return OutcomeResult(OutcomeTier.HARD_WIN, wincon="Mill", reason="All opponent libraries were emptied.", lock_established=lock_established, lock_plus_clock=lock_plus_clock)
    if "Commander Damage" in selected_wincons and all_dead_by_commander:
        return OutcomeResult(OutcomeTier.HARD_WIN, wincon="Commander Damage", reason="Each opponent took lethal commander damage from a specific commander.", lock_established=lock_established, lock_plus_clock=lock_plus_clock)

    if "Combat" in selected_wincons and combat_snapshot and bool(combat_snapshot.get("hard_win")):
        return OutcomeResult(OutcomeTier.HARD_WIN, wincon="Combat", reason="Combat allocation kills the full table under the current blocker/removal model.", lock_established=lock_established, lock_plus_clock=lock_plus_clock)

    shell_reason = _shell_combo_model_win(state, fingerprint, live_variant if combo_source_live else None)
    if shell_reason:
        return OutcomeResult(OutcomeTier.MODEL_WIN, wincon="Combo", reason=shell_reason, lock_established=lock_established, lock_plus_clock=lock_plus_clock)

    if lock_plus_clock:
        return OutcomeResult(OutcomeTier.MODEL_WIN, wincon="Control Lock", reason="A lock plus a credible clock is established under the table model.", lock_established=lock_established, lock_plus_clock=lock_plus_clock)

    if combat_snapshot:
        projected_life = combat_snapshot.get("projected_life") or state.opp_life
        projected_poison = combat_snapshot.get("projected_poison") or state.opp_poison
        if sum(1 for idx in range(3) if projected_life[idx] <= 0 or projected_poison[idx] >= 10) >= 2:
            return OutcomeResult(OutcomeTier.MODEL_WIN, wincon="Combat", reason="Combat pressure likely eliminates most of the table on the next cycle.", lock_established=lock_established, lock_plus_clock=lock_plus_clock)
        if combat_snapshot.get("combat_damage", 0.0) >= 18.0 or sum(projected_poison) >= 10.0:
            return OutcomeResult(OutcomeTier.DOMINANT, wincon="Combat", reason="Combat pressure is strong, but not a deterministic table kill.", lock_established=lock_established, lock_plus_clock=lock_plus_clock)

    if state.burn_total >= 18.0 or state.mill_total >= 40.0 or len(state.active_engines) >= 2:
        return OutcomeResult(OutcomeTier.DOMINANT, wincon=fingerprint.primary_plan.title(), reason="The deck is materially ahead, but the line is not deterministic yet.", lock_established=lock_established, lock_plus_clock=lock_plus_clock)

    return OutcomeResult(OutcomeTier.NONE, lock_established=lock_established, lock_plus_clock=lock_plus_clock)


def _exec_lookup(cards: List[Card], commander_cards: List[Card], compiled_exec_lookup: Dict[str, Any] | None) -> Dict[str, Any]:
    lookup = dict(compiled_exec_lookup or {})
    missing_cards = [card for card in list(cards) + list(commander_cards) if _normalize_name(card.name) not in lookup]
    if not missing_cards:
        return lookup
    raw_cards = []
    for card in missing_cards:
        raw_cards.append(
            {
                "name": card.name,
                "type_line": card.type_line,
                "oracle_text": card.oracle_text,
                "mana_value": card.mana_value,
                "keywords": list(card.keywords),
                "power": card.power,
                "toughness": card.toughness,
                "is_creature": card.is_creature,
                "is_permanent": card.is_permanent,
                "is_commander": card.is_commander,
                "tags": list(card.tags),
                "produced_mana": [],
                "combat_buff": card.combat_buff,
                "commander_buff": card.commander_buff,
                "token_attack_power": card.token_attack_power,
                "token_bodies": card.token_bodies,
                "extra_combat_factor": card.extra_combat_factor,
                "infect": card.infect,
                "toxic": card.toxic,
                "proliferate": card.proliferate,
                "burn_value": card.burn_value,
                "repeatable_burn": card.repeatable_burn,
                "mill_value": card.mill_value,
                "repeatable_mill": card.repeatable_mill,
                "alt_win_kind": card.alt_win_kind,
            }
        )
    lookup.update({_normalize_name(exec_card.name): exec_card for exec_card in compile_card_execs(raw_cards)})
    return lookup


def _mana_source_permanent(permanent: PermanentState) -> bool:
    if _is_land(permanent.card):
        return True
    return any(action.kind == "mana_source" for action in permanent.card_exec.activated)


def _untapped_mana_sources(state: GameState) -> List[PermanentState]:
    return [perm for perm in state.battlefield if _mana_source_permanent(perm) and not perm.tapped]


def _potential_mana(state: GameState) -> int:
    return int(state.mana_state.floating) + len(_untapped_mana_sources(state))


def _pay_generic_mana(state: GameState, cost: int) -> bool:
    if cost <= 0:
        return True
    if _potential_mana(state) < cost:
        return False
    floating = min(state.mana_state.floating, cost)
    state.mana_state.floating -= floating
    remaining = cost - floating
    if remaining <= 0:
        return True
    mana_perms = stable_sorted(_untapped_mana_sources(state), key=lambda perm: (0 if _is_land(perm.card) else 1, perm.card.mana_value, perm.permanent_id))
    for perm in mana_perms[:remaining]:
        perm.tapped = True
        perm.used_this_turn = True
        state.used_this_turn.add(perm.permanent_id)
    return True


def _draw_cards(state: GameState, count: int) -> list[str]:
    drawn: list[str] = []
    for _ in range(max(0, count)):
        if not state.library:
            break
        card = state.library.pop(0)
        state.hand.append(card)
        drawn.append(card.name)
    return drawn


def _token_power_toughness(card: Card) -> tuple[float, float]:
    power = max(1.0, float(card.token_attack_power or 1.0))
    toughness = max(1.0, float(card.toughness or 1.0))
    return power, toughness


def _add_tokens_from_card(state: GameState, card: Card) -> None:
    bodies = int(max(1.0, float(card.token_bodies or 0.0)))
    if bodies <= 0:
        return
    power, toughness = _token_power_toughness(card)
    sig = TokenSig(
        power=power,
        toughness=toughness,
        evasion_score=card.evasion_score,
        has_haste=card.has_haste,
        infect=card.infect,
        toxic=card.toxic,
    )
    state.token_buckets[sig] = state.token_buckets.get(sig, 0) + bodies


def _enqueue_trigger(state: GameState, permanent: PermanentState, window: str, kind: str, payload: Dict[str, Any] | None = None) -> None:
    priority_map = {
        "upkeep": 10,
        "etb": 20,
        "attack": 30,
        "death": 40,
        "end_step": 50,
    }
    state.pending_triggers.append(
        TriggerInstance(
            window=window,  # type: ignore[arg-type]
            source_id=permanent.permanent_id,
            source_name=permanent.card.name,
            kind=kind,
            payload=payload or {},
            priority=priority_map.get(window, 99),
        )
    )


def _add_permanent(state: GameState, card: Card, card_exec: Any, tapped: bool = False) -> PermanentState:
    permanent = PermanentState(
        permanent_id=state.next_permanent_id,
        card=card,
        card_exec=card_exec,
        tapped=tapped,
        summoning_sick=card.is_creature and not card.has_haste,
    )
    state.next_permanent_id += 1
    state.battlefield.append(permanent)
    state.permanent_counters[permanent.permanent_id] = permanent.counters
    for trigger in card_exec.triggers.get("etb", ()):
        _enqueue_trigger(state, permanent, "etb", trigger.kind, dict(trigger.payload))
    if "#Engine" in card.tags or "draw" in card_exec.coverage_summary.executable:
        state.active_engines.add(card.name)
    if "#Stax" in card.tags or "#Control" in card.tags or "#Counter" in card.tags:
        state.active_locks.add(card.name)
    return permanent


def _remove_permanent(state: GameState, permanent: PermanentState, commander_slots: tuple[str, ...] = ()) -> None:
    state.battlefield = [perm for perm in state.battlefield if perm.permanent_id != permanent.permanent_id]
    state.permanent_counters.pop(permanent.permanent_id, None)
    state.used_this_turn.discard(permanent.permanent_id)
    state.active_engines.discard(permanent.card.name)
    state.active_locks.discard(permanent.card.name)
    if permanent.card.is_commander:
        for slot, commander_name in enumerate(commander_slots[:MAX_COMMANDERS]):
            if commander_name and _normalize_name(commander_name) == _normalize_name(permanent.card.name):
                state.commander_zone[slot] = permanent.card
                break


def _apply_creature_wipe(state: GameState, commander_slots: tuple[str, ...]) -> None:
    dying = [perm for perm in state.battlefield if perm.card.is_creature]
    if not dying and not state.token_buckets:
        return
    if dying or state.token_buckets:
        _queue_death_triggers(state)
    for permanent in list(dying):
        _remove_permanent(state, permanent, commander_slots)
        if not permanent.card.is_commander:
            state.graveyard.append(permanent.card)
    state.token_buckets.clear()


def _pick_sacrifice_target(state: GameState) -> Card | None:
    if state.token_buckets:
        sig = next(iter(state.token_buckets))
        count = state.token_buckets.get(sig, 0)
        if count > 0:
            state.token_buckets[sig] = count - 1
            if state.token_buckets[sig] <= 0:
                state.token_buckets.pop(sig, None)
            return Card(name="Token", is_creature=True, power=sig.power, toughness=sig.toughness)
    creature_perms = [perm for perm in state.battlefield if perm.card.is_creature and not perm.card.is_commander]
    if not creature_perms:
        return None
    target = min(creature_perms, key=lambda perm: (perm.card.mana_value, perm.card.power, perm.permanent_id))
    state.battlefield = [perm for perm in state.battlefield if perm.permanent_id != target.permanent_id]
    state.permanent_counters.pop(target.permanent_id, None)
    return target.card


def _queue_death_triggers(state: GameState) -> None:
    for perm in state.battlefield:
        for trigger in perm.card_exec.triggers.get("death", ()):
            _enqueue_trigger(state, perm, "death", trigger.kind, dict(trigger.payload))


def _pick_tutor_target(state: GameState, fingerprint, winlines) -> Card | None:
    if not state.library:
        return None
    current_distance = min((winline_distance(state, state.hand, line) for line in winlines), default=0.0)
    live_tags = Counter(tag for perm in state.battlefield for tag in getattr(perm.card, "tags", []) or [])
    live_tags.update(tag for card in state.hand for tag in getattr(card, "tags", []) or [])

    def _requirement_gap(requirement: str) -> float:
        req = str(requirement or "").strip().lower()
        if not req:
            return 0.0
        if req in {"combo_piece", "combo"}:
            return 1.0 if live_tags["#Combo"] <= 0 else 0.0
        if req in {"engine", "engine_piece"}:
            return 1.0 if live_tags["#Engine"] <= 0 else 0.0
        if req in {"sink", "payoff", "wincon"}:
            return 1.0 if (live_tags["#Payoff"] + live_tags["#Wincon"]) <= 0 else 0.0
        if req in {"tutor"}:
            return 1.0 if live_tags["#Tutor"] <= 0 else 0.0
        if req in {"board_presence", "creature"}:
            creature_count = sum(1 for perm in state.battlefield if perm.card.is_creature) + int(sum(state.token_buckets.values()))
            return 1.0 if creature_count <= 0 else 0.0
        if req in {"protection"}:
            return 1.0 if live_tags["#Protection"] <= 0 else 0.0
        return 0.0

    def _candidate_requirement_hits(candidate: Card, requirement: str) -> float:
        req = str(requirement or "").strip().lower()
        tags = set(candidate.tags)
        if req in {"combo_piece", "combo"}:
            return 1.0 if "#Combo" in tags else 0.0
        if req in {"engine", "engine_piece"}:
            return 1.0 if "#Engine" in tags or "#Setup" in tags else 0.0
        if req in {"sink", "payoff", "wincon"}:
            return 1.0 if {"#Payoff", "#Wincon"} & tags else 0.0
        if req in {"tutor"}:
            return 1.0 if "#Tutor" in tags else 0.0
        if req in {"board_presence", "creature"}:
            return 1.0 if candidate.is_creature or candidate.is_permanent else 0.0
        if req in {"protection"}:
            return 1.0 if "#Protection" in tags or "#Counter" in tags else 0.0
        return 0.0

    priorities_by_plan = {
        "combo": ["#Combo", "#Wincon", "#Engine", "#Tutor", "#Draw", "#Ramp", "#Setup", "#Protection"],
        "combat": ["#Payoff", "#Wincon", "#Engine", "#Draw", "#Ramp", "#Setup", "#Protection"],
        "poison": ["#Wincon", "#Payoff", "#Engine", "#Draw", "#Ramp", "#Protection"],
        "drain": ["#Payoff", "#Engine", "#Draw", "#Recursion", "#Ramp", "#Protection"],
        "mill": ["#Payoff", "#Engine", "#Draw", "#Ramp", "#Protection"],
        "alt-win": ["#Wincon", "#Protection", "#Draw", "#Ramp", "#Tutor"],
    }
    priorities = priorities_by_plan.get(
        getattr(fingerprint, "primary_plan", "combat"),
        ["#Wincon", "#Engine", "#Draw", "#Ramp", "#Setup"],
    )

    def _priority_rank(card: Card) -> int:
        tags = set(card.tags)
        for idx, tag in enumerate(priorities):
            if tag in tags:
                return idx
        return len(priorities) + 1

    best_pick: Card | None = None
    best_key: tuple[float, float, float, float, int, int, str] | None = None
    for candidate in state.library:
        projected_hand = list(state.hand) + [candidate]
        projected_distance = min((winline_distance(state, projected_hand, line) for line in winlines), default=current_distance)
        distance_gain = round(current_distance - projected_distance, 4)
        tags = set(candidate.tags)
        missing_requirement_value = 0.0
        for line in winlines:
            for requirement in getattr(line, "requirements", ()) + getattr(line, "sink_requirements", ()):
                gap = _requirement_gap(requirement)
                if gap > 0:
                    missing_requirement_value += gap * _candidate_requirement_hits(candidate, requirement)
        sink_bonus = 0.35 if "#Wincon" in tags or "#Payoff" in tags else 0.0
        protection_bonus = 0.15 if "#Protection" in tags or "#Counter" in tags else 0.0
        key = (
            round(missing_requirement_value, 4),
            distance_gain,
            sink_bonus,
            protection_bonus,
            -_priority_rank(candidate),
            -int(candidate.mana_value or 0),
            candidate.name,
        )
        if best_key is None or key > best_key:
            best_pick = candidate
            best_key = key
    return best_pick


def _resolve_card_effect(state: GameState, card: Card, card_exec: Any, effect_kind: str, *, fingerprint=None, winlines=None, current_intent: str = "develop") -> None:
    if effect_kind == "draw":
        count = 2 if "#Draw" in card.tags else 1
        _draw_cards(state, count)
    elif effect_kind == "loot":
        drawn = _draw_cards(state, 1)
        if drawn and state.hand:
            discard = max(state.hand, key=lambda c: (c.mana_value, c.name))
            state.hand.remove(discard)
            state.graveyard.append(discard)
    elif effect_kind == "impulse_draw":
        _draw_cards(state, 1)
    elif effect_kind == "tutor":
        pick = _pick_tutor_target(state, fingerprint, winlines)
        if pick is not None:
            state.library.remove(pick)
            state.hand.append(pick)
    elif effect_kind == "create_tokens":
        _add_tokens_from_card(state, card)
    elif effect_kind == "extra_combat":
        state.extra_combats += 1
    elif effect_kind == "selective_untap":
        target = None
        if current_intent in {"convert", "race"}:
            tapped_creatures = [
                perm
                for perm in state.battlefield
                if perm.tapped and perm.card.is_creature
            ]
            if tapped_creatures:
                target = max(tapped_creatures, key=lambda perm: (perm.card.power, perm.card.evasion_score, -perm.permanent_id))
        if target is None:
            target = next((perm for perm in state.battlefield if perm.tapped and _mana_source_permanent(perm)), None)
        if target is not None:
            target.tapped = False
            target.used_this_turn = False
            state.used_this_turn.discard(target.permanent_id)
    elif effect_kind == "burn_single_target":
        amount = max(card.burn_value, card.repeatable_burn, 1.0)
        target = min((idx for idx in range(3) if _opponent_alive(state, idx)), key=lambda idx: state.opp_life[idx], default=0)
        state.opp_life[target] = max(0.0, state.opp_life[target] - amount)
        state.burn_total += amount
    elif effect_kind == "burn_all_opponents":
        amount = max(card.burn_value, card.repeatable_burn, 1.0)
        state.opp_life = [max(0.0, life - amount) for life in state.opp_life]
        state.burn_total += amount * len(state.opp_life)
    elif effect_kind == "drain_all_opponents":
        amount = max(card.burn_value, card.repeatable_burn, 1.0)
        state.opp_life = [max(0.0, life - amount) for life in state.opp_life]
        state.burn_total += amount * len(state.opp_life)
    elif effect_kind == "mill_single_target":
        amount = int(max(card.mill_value, card.repeatable_mill, 1.0))
        target = min((idx for idx in range(3) if _opponent_alive(state, idx)), key=lambda idx: state.opp_library[idx], default=0)
        state.opp_library[target] = max(0, state.opp_library[target] - amount)
        state.mill_total += amount
    elif effect_kind == "mill_all_opponents":
        amount = int(max(card.mill_value, card.repeatable_mill, 1.0))
        state.opp_library = [max(0, size - amount) for size in state.opp_library]
        state.mill_total += amount * len(state.opp_library)
    elif effect_kind == "proliferate":
        state.opp_poison = [poison + 1 if poison > 0 else poison for poison in state.opp_poison]
    elif effect_kind == "sac_outlet":
        sacrificed = _pick_sacrifice_target(state)
        if sacrificed is not None:
            state.graveyard.append(sacrificed)
            _queue_death_triggers(state)
    elif effect_kind == "reanimation":
        target = next((c for c in reversed(state.graveyard) if c.is_creature), None)
        if target is not None:
            state.graveyard.remove(target)
            _add_permanent(state, target, card_exec)
    elif effect_kind == "recursion":
        target = next((c for c in reversed(state.graveyard) if c.is_permanent or c.is_creature), None)
        if target is not None:
            state.graveyard.remove(target)
            state.hand.append(target)


def _resolve_trigger_queue(state: GameState, current_intent: str = "develop", *, fingerprint=None, winlines=None) -> None:
    while state.pending_triggers:
        queue = stable_sorted(list(state.pending_triggers), key=lambda trig: (trig.priority, trig.source_id, trig.kind))
        if current_intent in {"convert", "race"}:
            queue = stable_sorted(queue, key=lambda trig: (0 if trig.kind in {"attack_trigger", "death_trigger"} else 1, trig.priority, trig.source_id))
        trigger = queue[0]
        for idx, queued in enumerate(state.pending_triggers):
            if queued is trigger:
                del state.pending_triggers[idx]
                break
        permanent = next((perm for perm in state.battlefield if perm.permanent_id == trigger.source_id), None)
        if permanent is None:
            continue
        exec_ops = set(permanent.card_exec.coverage_summary.executable)
        if trigger.window == "upkeep":
            for effect in ("draw", "create_tokens", "burn_all_opponents", "drain_all_opponents", "mill_all_opponents"):
                if effect in exec_ops:
                    _resolve_card_effect(state, permanent.card, permanent.card_exec, effect, fingerprint=fingerprint, winlines=winlines, current_intent=current_intent)
        elif trigger.window == "etb":
            for effect in ("draw", "create_tokens", "burn_single_target", "burn_all_opponents", "mill_single_target", "mill_all_opponents", "reanimation", "recursion"):
                if effect in exec_ops:
                    _resolve_card_effect(state, permanent.card, permanent.card_exec, effect, fingerprint=fingerprint, winlines=winlines, current_intent=current_intent)
        elif trigger.window == "attack":
            for effect in ("draw", "create_tokens", "burn_single_target", "burn_all_opponents", "extra_combat", "selective_untap"):
                if effect in exec_ops:
                    _resolve_card_effect(state, permanent.card, permanent.card_exec, effect, fingerprint=fingerprint, winlines=winlines, current_intent=current_intent)
        elif trigger.window == "death":
            for effect in ("draw", "create_tokens", "drain_all_opponents", "burn_all_opponents", "mill_all_opponents", "recursion"):
                if effect in exec_ops:
                    _resolve_card_effect(state, permanent.card, permanent.card_exec, effect, fingerprint=fingerprint, winlines=winlines, current_intent=current_intent)


def _queue_upkeep_triggers(state: GameState) -> None:
    for permanent in state.battlefield:
        for trigger in permanent.card_exec.triggers.get("upkeep", ()):
            _enqueue_trigger(state, permanent, "upkeep", trigger.kind, dict(trigger.payload))


def _queue_attack_triggers(state: GameState, attackers: List[PermanentState]) -> None:
    attacker_ids = {perm.permanent_id for perm in attackers}
    for permanent in state.battlefield:
        if permanent.permanent_id not in attacker_ids:
            continue
        for trigger in permanent.card_exec.triggers.get("attack", ()):
            _enqueue_trigger(state, permanent, "attack", trigger.kind, dict(trigger.payload))


def _available_attackers(state: GameState) -> List[PermanentState]:
    return [
        permanent
        for permanent in state.battlefield
        if permanent.card.is_creature and not permanent.tapped and (not permanent.summoning_sick or permanent.card.has_haste)
    ]


def _choose_attackers(state: GameState) -> List[PermanentState]:
    attackers = _available_attackers(state)
    return stable_sorted(attackers, key=lambda perm: (-perm.card.power, -perm.card.evasion_score, perm.permanent_id))


def _token_attack_units(state: GameState) -> List[Dict[str, Any]]:
    units: List[Dict[str, Any]] = []
    for sig, count in state.token_buckets.items():
        for token_idx in range(max(0, count)):
            units.append(
                {
                    "source": f"token:{token_idx}",
                    "power": max(0.0, sig.power),
                    "evasion": min(1.0, 0.55 + sig.evasion_score),
                    "infect": bool(sig.infect),
                    "toxic": float(sig.toxic or 0.0),
                    "commander_slot": None,
                    "salience": 1.5,
                }
            )
    return units


def _attacker_units(
    state: GameState,
    attackers: List[PermanentState],
    commander_slots: tuple[str, ...],
) -> List[Dict[str, Any]]:
    combat_buff = sum(perm.card.combat_buff for perm in state.battlefield)
    commander_buff = sum(perm.card.commander_buff for perm in state.battlefield)
    units = _token_attack_units(state)
    for perm in attackers:
        slot = None
        for idx, commander_name in enumerate(commander_slots[:MAX_COMMANDERS]):
            if commander_name and _normalize_name(commander_name) == _normalize_name(perm.card.name):
                slot = idx
                break
        tags = set(getattr(perm.card, "tags", []) or [])
        salience = 3.0 if {"#Payoff", "#Wincon", "#Combo"} & tags else 2.0
        if slot is not None:
            salience += 1.0
        units.append(
            {
                "source": perm.card.name,
                "power": max(0.0, perm.card.power + combat_buff + (commander_buff if slot is not None else 0.0)),
                "evasion": min(1.0, 0.55 + perm.card.evasion_score),
                "infect": bool(perm.card.infect),
                "toxic": float(perm.card.toxic or 0.0),
                "commander_slot": slot,
                "salience": salience,
            }
        )
    return stable_sorted(units, key=lambda unit: (-float(unit["salience"]), -float(unit["power"]), str(unit["source"])))


def _target_order(state: GameState, fingerprint, units: List[Dict[str, Any]]) -> List[int]:
    live = [idx for idx in range(3) if _opponent_alive(state, idx)]
    if not live:
        return [0, 1, 2]
    poison_heavy = any(unit["infect"] or float(unit["toxic"]) > 0 for unit in units)
    if poison_heavy or fingerprint.primary_plan == "poison":
        return sorted(live, key=lambda idx: (10 - state.opp_poison[idx], state.opp_life[idx], idx))
    if fingerprint.prefers_focus_fire:
        return sorted(live, key=lambda idx: (state.opp_life[idx], idx))
    return sorted(live, key=lambda idx: (state.opp_life[idx] + 2.0 * (10 - state.opp_poison[idx]), idx))


def _allocate_attacks(
    state: GameState,
    units: List[Dict[str, Any]],
    commander_slots: tuple[str, ...],
    opponent_table: VirtualTable,
    fingerprint,
    *,
    hazard_model_active: bool = False,
) -> Dict[str, Any]:
    projected_life = list(state.opp_life)
    projected_poison = list(state.opp_poison)
    projected_cmdr = [list(row) for row in state.opp_cmdr_dmg]
    if hazard_model_active:
        block_budget = blocker_budget_vector(opponent_table, state, state.turn)
        removal_budget = [
            opponent_table.opponents[idx].remaining_spot_removal if idx < len(opponent_table.opponents) else 0
            for idx in range(3)
        ]
    else:
        block_budget = [0.0, 0.0, 0.0]
        removal_budget = [0, 0, 0]
    allocations: List[Dict[str, Any]] = []

    for unit in units:
        best_target = None
        best_payload = None
        for opp_idx in _target_order(state, fingerprint, units):
            if not _opponent_alive(state, opp_idx):
                continue
            removable = removal_budget[opp_idx] > 0 and float(unit["salience"]) >= 4.0
            damage = 0.0 if removable else max(0.0, float(unit["power"]) * float(unit["evasion"]) - block_budget[opp_idx])
            life_damage = 0.0 if unit["infect"] else damage
            poison = 0.0
            if unit["infect"]:
                poison += damage
            if float(unit["toxic"]) > 0:
                poison += float(unit["toxic"]) * float(unit["evasion"])
            projected_life_after = max(0.0, projected_life[opp_idx] - life_damage)
            projected_poison_after = projected_poison[opp_idx] + poison
            cmdr_after = None
            if unit["commander_slot"] is not None:
                cmdr_after = projected_cmdr[int(unit["commander_slot"])][opp_idx] + damage
            kill_score = 0.0
            if projected_life_after <= 0:
                kill_score += 3.0
            if projected_poison_after >= 10:
                kill_score += 3.0
            if cmdr_after is not None and cmdr_after >= 21:
                kill_score += 3.0
            residual = min(projected_life_after, max(0.0, 10 - projected_poison_after), max(0.0, 21 - (cmdr_after or 0.0)))
            score = kill_score - 0.08 * residual - opp_idx * 0.001
            if best_target is None or score > best_payload["score"]:
                best_target = opp_idx
                best_payload = {
                    "score": score,
                    "damage": damage,
                    "poison": poison,
                    "removable": removable,
                    "cmdr_after": cmdr_after,
                }
        if best_target is None or best_payload is None:
            continue
        opp_idx = int(best_target)
        if best_payload["removable"]:
            removal_budget[opp_idx] -= 1
            if hazard_model_active and opp_idx < len(opponent_table.opponents):
                opponent_table.opponents[opp_idx].spent_spot_removal += 1
                opponent_table.interaction_events["spot_removal"] += 1
                opponent_table.answer_expenditure["spot_removal"] += 1
        else:
            block_budget[opp_idx] = max(0.0, block_budget[opp_idx] - float(unit["power"]) * max(0.0, 1.0 - float(unit["evasion"])))
            projected_life[opp_idx] = max(
                0.0,
                projected_life[opp_idx] - (0.0 if unit["infect"] else best_payload["damage"]),
            )
            projected_poison[opp_idx] += best_payload["poison"]
            if unit["commander_slot"] is not None:
                projected_cmdr[int(unit["commander_slot"])][opp_idx] += best_payload["damage"]
        allocations.append(
            {
                "opponent": opp_idx,
                "source": unit["source"],
                "damage": round(float(best_payload["damage"]), 4),
                "poison": round(float(best_payload["poison"]), 4),
                "commander_slot": unit["commander_slot"],
                "removed": bool(best_payload["removable"]),
            }
        )

    if any(perm.card.proliferate for perm in state.battlefield):
        projected_poison = [poison + 1 if poison > 0 else poison for poison in projected_poison]

    hard_win = all(
        projected_life[idx] <= 0
        or projected_poison[idx] >= 10
        or any(projected_cmdr[slot][idx] >= 21 for slot in range(MAX_COMMANDERS))
        for idx in range(3)
    )
    return {
        "allocations": allocations,
        "projected_life": projected_life,
        "projected_poison": projected_poison,
        "projected_cmdr_dmg": projected_cmdr,
        "hard_win": hard_win,
        "combat_damage": round(sum(item["damage"] for item in allocations), 4),
        "poison_damage": round(sum(item["poison"] for item in allocations), 4),
    }


def _activated_actions(state: GameState) -> List[Tuple[str, PermanentState, str]]:
    actions: List[Tuple[str, PermanentState, str]] = []
    for permanent in state.battlefield:
        if permanent.used_this_turn:
            continue
        for action in permanent.card_exec.activated:
            if action.kind == "mana_source" and permanent.tapped:
                continue
            if action.kind == "sac_outlet":
                def _is_disposable_fodder(perm: PermanentState) -> bool:
                    if not perm.card.is_creature or perm.card.is_commander or perm.permanent_id == permanent.permanent_id:
                        return False
                    exec_ops = set(getattr(perm.card_exec.coverage_summary, "executable", ()) or ())
                    pure_death_payoff = (
                        "death_trigger" in exec_ops
                        and exec_ops & {"drain_all_opponents", "burn_all_opponents", "burn_single_target"}
                        and not exec_ops & {"create_tokens", "recursion", "reanimate", "mill_single_target", "mill_all_opponents"}
                    )
                    return not pure_death_payoff

                has_fodder = bool(state.token_buckets) or any(_is_disposable_fodder(perm) for perm in state.battlefield)
                has_death_payoff = any("death_trigger" in perm.card_exec.coverage_summary.executable for perm in state.battlefield)
                if not (has_fodder and has_death_payoff):
                    continue
            actions.append(("activate", permanent, action.kind))
    return actions


def _apply_combat_results(
    state: GameState,
    combat_snapshot: Dict[str, object],
    _commander_index: Dict[str, int],
) -> None:
    state.combat_damage_total += float(combat_snapshot.get("combat_damage", 0.0) or 0.0)
    state.opp_life = list(combat_snapshot.get("projected_life") or state.opp_life)
    state.opp_poison = list(combat_snapshot.get("projected_poison") or state.opp_poison)
    projected_cmdr = combat_snapshot.get("projected_cmdr_dmg") or ()
    for slot in range(min(MAX_COMMANDERS, len(projected_cmdr))):
        state.opp_cmdr_dmg[slot] = list(projected_cmdr[slot])


def _record_commander_cast(state: GameState, cmd_slot: int | None) -> None:
    if cmd_slot is None:
        return
    state.commander_casts[cmd_slot] += 1
    state.commander_tax[cmd_slot] = 2 * state.commander_casts[cmd_slot]
    if 0 <= cmd_slot < len(state.commander_zone):
        state.commander_zone[cmd_slot] = None


def _cast_from_hand(state: GameState, card: Card, card_exec: Any, *, fingerprint=None, winlines=None, current_intent: str = "develop") -> PermanentState | None:
    enters_tapped = "enters tapped" in card.oracle_text.lower()
    if card.is_permanent or _is_land(card):
        return _add_permanent(state, card, card_exec, tapped=enters_tapped)
    else:
        state.graveyard.append(card)
        for mode in card_exec.cast_modes:
            if mode.kind in {"cast", "cast_spell", "cast_permanent", "cast_creature", "play_land"}:
                continue
            _resolve_card_effect(state, card, card_exec, mode.kind, fingerprint=fingerprint, winlines=winlines, current_intent=current_intent)
    return None


def simulate_one(
    cards: List[Card],
    commander: str | List[str] | None,
    commander_cards: List[Card] | None = None,
    turn_limit: int = 8,
    policy: str = "casual",
    multiplayer: bool = True,
    threat_model: bool = False,
    rng: random.Random | None = None,
    primary_wincons: List[str] | None = None,
    color_identity_size: int = 3,
    combo_variants: List[Dict] | None = None,
    combo_source_live: bool = False,
    capture_trace: bool = False,
    resolved_config: ResolvedSimConfig | Dict | None = None,
    run_seed: int | None = None,
    compiled_exec_lookup: Dict[str, Any] | None = None,
) -> RunMetrics:
    resolved = coerce_resolved_sim_config(
        resolved_config,
        commander=commander,
        requested_policy=policy,
        bracket=3,
        turn_limit=turn_limit,
        multiplayer=multiplayer,
        threat_model=threat_model,
        primary_wincons=primary_wincons,
        color_identity_size=color_identity_size,
        seed=run_seed if run_seed is not None else 42,
    )
    deck = cards.copy()
    commander_cards = commander_cards or []
    if rng is None:
        rng = random.Random(42)
    policy = resolved.policy.resolved_policy
    colors_req = resolved.color_identity_size
    local_rng_manager = RNGManager(run_seed) if run_seed is not None else None
    exec_lookup = _exec_lookup(cards, commander_cards, compiled_exec_lookup)
    fingerprint = compile_deck_fingerprint(cards, commander_cards, exec_lookup)
    winlines = compile_winlines(cards, fingerprint)
    normalized_combo_variants = _normalize_combo_variants(combo_variants)
    if capture_trace:
        hand, mulligans_taken, mulligan_steps = london_mulligan(
            deck,
            policy,
            multiplayer,
            rng,
            colors_req,
            commander_cards=commander_cards,
            fingerprint=fingerprint,
            winlines=winlines,
            capture_log=True,
            rng_manager=local_rng_manager,
        )
    else:
        hand, mulligans_taken = london_mulligan(
            deck,
            policy,
            multiplayer,
            rng,
            colors_req,
            commander_cards=commander_cards,
            fingerprint=fingerprint,
            winlines=winlines,
            capture_log=False,
            rng_manager=local_rng_manager,
        )
        mulligan_steps = []

    lib = deck[len(hand) :]
    commander_slots = tuple(name for name in resolved.commander_slots if name)
    commander_index = {name.casefold(): slot for slot, name in enumerate(commander_slots[:MAX_COMMANDERS]) if name}
    commander_by_name = {_normalize_name(card.name): card for card in commander_cards}
    support_scores = [float(exec_lookup.get(_normalize_name(card.name)).coverage_summary.support_score) for card in list(deck) + list(commander_cards) if exec_lookup.get(_normalize_name(card.name)) is not None]
    state = GameState(
        hand=list(hand),
        library=list(lib),
        support_confidence_penalty=max(0.0, 1.0 - (sum(support_scores) / len(support_scores))) if support_scores else 0.0,
        opp_library=[99, 99, 99],
    )
    for slot, commander_name in enumerate(commander_slots[:MAX_COMMANDERS]):
        state.commander_zone[slot] = commander_by_name.get(_normalize_name(commander_name))
    opponent_table = sample_virtual_table(resolved.opponent, local_rng_manager, run_seed)
    interaction_rng = random.Random(local_rng_manager.seed("opponent", 1) if local_rng_manager is not None else int((run_seed or 42) + 104729))

    commander_cast_turn = None
    cards_seen = len(state.hand)
    seen_cards = {c.name for c in state.hand}
    cast_cards = set()

    mana_by_turn = []
    lands_by_turn = []
    colors_by_turn = []
    actions_by_turn = []
    phase_by_turn = []
    plan_progress = []
    ramp_online_turn = None
    draw_engine_turn = None
    win_turn = None
    achieved_wincon = None
    win_reason = None
    outcome_tier = OutcomeTier.NONE.value
    model_win_reason = None
    lock_established = False
    lock_plus_clock = False
    selected_wincons = list(resolved.selected_wincons)
    tier_rank = {
        OutcomeTier.NONE.value: 0,
        OutcomeTier.DOMINANT.value: 1,
        OutcomeTier.MODEL_WIN.value: 2,
        OutcomeTier.HARD_WIN.value: 3,
    }
    opening_hand = [c.name for c in state.hand]
    turn_trace: List[Dict] = []

    for turn in range(1, turn_limit + 1):
        state.turn = turn
        state.phase = "untap"
        state.mana_state.floating = 0
        state.extra_combats = 0
        state.lands_played_this_turn = 0
        state.used_this_turn.clear()
        cast_this_turn: List[Card] = []
        cast_names: List[str] = []
        draw_name = None
        land_name = None
        combat_snapshot: Dict[str, Any] | None = None
        intent = "develop"

        for permanent in state.battlefield:
            permanent.tapped = False
            permanent.used_this_turn = False
            permanent.summoning_sick = False

        if threat_model and resolved.opponent.threat_model:
            state.self_life = max(0.0, state.self_life - expected_incoming_pressure(opponent_table, state, turn))
            if state.self_life <= 0:
                model_win_reason = model_win_reason or "The virtual table's pressure kills you before the deck can convert."
                break

        state.phase = "upkeep"
        _queue_upkeep_triggers(state)
        _resolve_trigger_queue(state, current_intent="develop", fingerprint=fingerprint, winlines=winlines)
        commander_live_names = {_normalize_name(perm.card.name) for perm in state.battlefield if perm.card.is_commander}
        turn_outcome = _evaluate_outcome(
            state=state,
            selected_wincons=selected_wincons,
            fingerprint=fingerprint,
            opponent_table=opponent_table,
            current_window="upkeep",
            combat_snapshot=None,
            commanders=commander,
            combo_variants=normalized_combo_variants,
            combo_source_live=combo_source_live,
            commander_live_names=commander_live_names,
        )

        if turn_outcome.tier != OutcomeTier.HARD_WIN:
            state.phase = "draw"
            drawn = _draw_cards(state, 1)
            if drawn:
                draw_name = drawn[0]
                cards_seen += len(drawn)
                seen_cards.update(drawn)

            state.phase = "precombat_main"
            land_idx = next((i for i, c in enumerate(state.hand) if _is_land(c)), None)
            if land_idx is not None and state.lands_played_this_turn < (1 + state.extra_land_plays):
                land_card = state.hand.pop(land_idx)
                land_exec = exec_lookup.get(_normalize_name(land_card.name))
                if land_exec is not None:
                    _cast_from_hand(state, land_card, land_exec, fingerprint=fingerprint, winlines=winlines, current_intent="develop")
                    state.lands_played_this_turn += 1
                    land_name = land_card.name
            while True:
                commander_live_names = {_normalize_name(perm.card.name) for perm in state.battlefield if perm.card.is_commander}
                intent = choose_turn_intent(
                    state,
                    state.hand,
                    fingerprint,
                    winlines,
                    threat_model=threat_model,
                    opponent_table=opponent_table,
                )
                chosen = choose_best_action(
                    state=state,
                    hand=state.hand,
                    commander_cards=commander_cards,
                    commander_live_names=commander_live_names,
                    commander_index=commander_index,
                    exec_lookup=exec_lookup,
                    intent=intent,
                    fingerprint=fingerprint,
                    winlines=winlines,
                    threat_model=threat_model,
                    opponent_table=opponent_table,
                )
                if chosen is None:
                    break
                action_type = chosen["type"]
                if action_type == "land":
                    idx = int(chosen["index"])
                    if idx >= len(state.hand):
                        break
                    card = state.hand.pop(idx)
                    card_exec = exec_lookup.get(_normalize_name(card.name))
                    if card_exec is None:
                        continue
                    _cast_from_hand(state, card, card_exec, fingerprint=fingerprint, winlines=winlines, current_intent=intent)
                    state.lands_played_this_turn += 1
                    if land_name is None:
                        land_name = card.name
                elif action_type == "cast":
                    idx = int(chosen["index"])
                    if idx >= len(state.hand):
                        break
                    card = state.hand[idx]
                    if card.mana_value > _potential_mana(state) or not _pay_generic_mana(state, card.mana_value):
                        break
                    state.hand.pop(idx)
                    card_exec = chosen["card_exec"]
                    if threat_model and resolved.opponent.threat_model:
                        countered_by = maybe_counter_spell(opponent_table, state, card, interaction_rng, turn)
                        if countered_by is not None:
                            state.graveyard.append(card)
                            cast_cards.add(card.name)
                            cast_this_turn.append(card)
                            cast_names.append(card.name)
                            continue
                    entered = _cast_from_hand(state, card, card_exec, fingerprint=fingerprint, winlines=winlines, current_intent=intent)
                    if entered is not None and threat_model and resolved.opponent.threat_model:
                        removed_by = maybe_remove_permanent(opponent_table, state, entered.card, interaction_rng, turn)
                        if removed_by is not None:
                            _remove_permanent(state, entered, commander_slots)
                            if not card.is_commander:
                                state.graveyard.append(card)
                    cast_cards.add(card.name)
                    cast_this_turn.append(card)
                    cast_names.append(card.name)
                    if ramp_online_turn is None and sum(1 for b in state.battlefield if "#Ramp" in b.card.tags or _is_land(b.card)) >= 4:
                        ramp_online_turn = turn
                    if draw_engine_turn is None and ("#Draw" in card.tags or "#Engine" in card.tags):
                        draw_engine_turn = turn
                elif action_type == "commander":
                    cmd = chosen["card"]
                    cmd_slot = commander_index.get(_normalize_name(cmd.name))
                    cmd_cost = cmd.mana_value + (state.commander_tax[cmd_slot] if cmd_slot is not None else 0)
                    if cmd_cost > _potential_mana(state) or not _pay_generic_mana(state, cmd_cost):
                        break
                    commander_cast_turn = turn if commander_cast_turn is None else min(commander_cast_turn, turn)
                    _record_commander_cast(state, cmd_slot)
                    if threat_model and resolved.opponent.threat_model:
                        countered_by = maybe_counter_spell(opponent_table, state, cmd, interaction_rng, turn)
                        if countered_by is not None:
                            cast_cards.add(cmd.name)
                            cast_this_turn.append(cmd)
                            cast_names.append(cmd.name)
                            continue
                    cast_cards.add(cmd.name)
                    cast_this_turn.append(cmd)
                    cast_names.append(cmd.name)
                    entered = _add_permanent(state, cmd, chosen["card_exec"])
                    if threat_model and resolved.opponent.threat_model:
                        removed_by = maybe_remove_permanent(opponent_table, state, entered.card, interaction_rng, turn)
                        if removed_by is not None:
                            _remove_permanent(state, entered, commander_slots)
                elif action_type == "activate":
                    permanent = chosen["permanent"]
                    effect_kind = chosen["effect_kind"]
                    permanent.used_this_turn = True
                    state.used_this_turn.add(permanent.permanent_id)
                    _resolve_card_effect(state, permanent.card, permanent.card_exec, effect_kind, fingerprint=fingerprint, winlines=winlines, current_intent=intent)
                else:
                    break
                _resolve_trigger_queue(state, current_intent=intent, fingerprint=fingerprint, winlines=winlines)

            assert state.mana_state.floating >= 0, "negative floating mana"
            assert state.lands_played_this_turn <= 1 + state.extra_land_plays, "illegal extra land drop"

            passive_extra_combats = sum(
                max(0, int(round(float(getattr(perm.card, "extra_combat_factor", 1.0) or 1.0) - 1.0)))
                for perm in state.battlefield
                if float(getattr(perm.card, "extra_combat_factor", 1.0) or 1.0) > 1.0
            )
            if passive_extra_combats > 0:
                state.extra_combats = max(state.extra_combats, passive_extra_combats)

            attackers = _choose_attackers(state)
            for attacker in attackers:
                attacker.tapped = True
            state.phase = "declare_attackers"
            _queue_attack_triggers(state, attackers)
            _resolve_trigger_queue(state, current_intent="convert", fingerprint=fingerprint, winlines=winlines)
            state.phase = "combat_damage"
            commander_live_names = {_normalize_name(perm.card.name) for perm in state.battlefield if perm.card.is_commander}
            combat_snapshot = _allocate_attacks(
                state,
                _attacker_units(state, attackers, commander_slots),
                commander_slots,
                opponent_table,
                fingerprint,
                hazard_model_active=bool(threat_model and resolved.opponent.threat_model),
            )
            _apply_combat_results(state, combat_snapshot, commander_index)
            turn_outcome = _evaluate_outcome(
                state=state,
                selected_wincons=selected_wincons,
                fingerprint=fingerprint,
                opponent_table=opponent_table,
                current_window="combat_damage",
                combat_snapshot=combat_snapshot,
                commanders=commander,
                combo_variants=normalized_combo_variants,
                combo_source_live=combo_source_live,
                commander_live_names=commander_live_names,
            )
            while state.extra_combats > 0 and turn_outcome.tier != OutcomeTier.HARD_WIN:
                state.extra_combats -= 1
                extra_attackers = _choose_attackers(state)
                if not extra_attackers:
                    break
                for attacker in extra_attackers:
                    attacker.tapped = True
                state.phase = "declare_attackers"
                _queue_attack_triggers(state, extra_attackers)
                _resolve_trigger_queue(state, current_intent="convert", fingerprint=fingerprint, winlines=winlines)
                state.phase = "combat_damage"
                commander_live_names = {_normalize_name(perm.card.name) for perm in state.battlefield if perm.card.is_commander}
                extra_snapshot = _allocate_attacks(
                    state,
                    _attacker_units(state, extra_attackers, commander_slots),
                    commander_slots,
                    opponent_table,
                    fingerprint,
                    hazard_model_active=bool(threat_model and resolved.opponent.threat_model),
                )
                _apply_combat_results(state, extra_snapshot, commander_index)
                combat_snapshot = {
                    "allocations": list((combat_snapshot or {}).get("allocations", [])) + list(extra_snapshot.get("allocations", [])),
                    "projected_life": extra_snapshot.get("projected_life"),
                    "projected_poison": extra_snapshot.get("projected_poison"),
                    "projected_cmdr_dmg": extra_snapshot.get("projected_cmdr_dmg"),
                    "hard_win": bool((combat_snapshot or {}).get("hard_win")) or bool(extra_snapshot.get("hard_win")),
                    "combat_damage": float((combat_snapshot or {}).get("combat_damage", 0.0) or 0.0) + float(extra_snapshot.get("combat_damage", 0.0) or 0.0),
                    "poison_damage": float((combat_snapshot or {}).get("poison_damage", 0.0) or 0.0) + float(extra_snapshot.get("poison_damage", 0.0) or 0.0),
                }
                turn_outcome = _evaluate_outcome(
                    state=state,
                    selected_wincons=selected_wincons,
                    fingerprint=fingerprint,
                    opponent_table=opponent_table,
                    current_window="combat_damage",
                    combat_snapshot=combat_snapshot,
                    commanders=commander,
                    combo_variants=normalized_combo_variants,
                    combo_source_live=combo_source_live,
                    commander_live_names=commander_live_names,
                )

        mana_total = sum(1 for perm in state.battlefield if _is_land(perm.card) or "#Ramp" in perm.card.tags)
        lands_total = sum(1 for perm in state.battlefield if _is_land(perm.card))
        if color_identity_size <= 0:
            colors_total = 0
        elif color_identity_size == 1:
            colors_total = 1
        else:
            colors_total = min(color_identity_size, max(1, sum(1 for perm in state.battlefield if "#Fixing" in perm.card.tags) + 1))
        mana_by_turn.append(mana_total)
        lands_by_turn.append(lands_total)
        colors_by_turn.append(colors_total)
        actions_by_turn.append(len(cast_this_turn))

        progress = 0.0
        progress += mana_total * 0.5
        progress += len([perm for perm in state.battlefield if "#Draw" in perm.card.tags]) * 0.8
        progress += len(state.active_engines) * 1.0
        if commander_cast_turn is not None:
            progress += 1.2
        combat_damage = float((combat_snapshot or {}).get("combat_damage", 0.0) or 0.0)
        projected_cmdr = (combat_snapshot or {}).get("projected_cmdr_dmg") or ()
        commander_combat = 0.0
        for slot in range(min(MAX_COMMANDERS, len(projected_cmdr))):
            commander_combat += max(projected_cmdr[slot]) if projected_cmdr[slot] else 0.0
        progress += min(6.0, combat_damage / 10.0)
        progress += min(5.0, commander_combat / 6.0)
        progress += min(4.0, state.burn_total / 10.0)
        progress -= state.support_confidence_penalty
        plan_progress.append(progress)

        engine_count = len(state.active_engines)
        if turn_outcome.tier in {OutcomeTier.HARD_WIN, OutcomeTier.MODEL_WIN} or any(t in c.tags for c in cast_this_turn for t in ["#Combo", "#Wincon", "#Payoff"]):
            phase_by_turn.append("win_attempt")
        elif engine_count >= 1 or draw_engine_turn is not None:
            phase_by_turn.append("engine")
        else:
            phase_by_turn.append("setup")

        lock_established = lock_established or turn_outcome.lock_established
        lock_plus_clock = lock_plus_clock or turn_outcome.lock_plus_clock
        if tier_rank[turn_outcome.tier.value] > tier_rank[outcome_tier]:
            outcome_tier = turn_outcome.tier.value
            if turn_outcome.tier == OutcomeTier.MODEL_WIN:
                model_win_reason = turn_outcome.reason
            elif turn_outcome.tier == OutcomeTier.DOMINANT and model_win_reason is None:
                model_win_reason = turn_outcome.reason
        if turn_outcome.tier == OutcomeTier.HARD_WIN and win_turn is None:
            win_turn = turn
            achieved_wincon = turn_outcome.wincon
            win_reason = turn_outcome.reason
        elif turn_outcome.tier in {OutcomeTier.MODEL_WIN, OutcomeTier.DOMINANT} and achieved_wincon is None:
            win_turn = turn
            achieved_wincon = turn_outcome.wincon
            win_reason = turn_outcome.reason

        if capture_trace:
            turn_trace.append(
                {
                    "turn": turn,
                    "draw": draw_name,
                    "land": land_name,
                    "casts": cast_names,
                    "actions": len(cast_names),
                    "mana_total": mana_total,
                    "intent": intent,
                    "phase": phase_by_turn[-1] if phase_by_turn else "setup",
                    "outcome_tier": turn_outcome.tier.value,
                    "wincon_hit": turn_outcome.wincon,
                    "win_reason": turn_outcome.reason,
                }
            )

        if threat_model and resolved.opponent.threat_model and turn_outcome.tier != OutcomeTier.HARD_WIN:
            state.phase = "end_step"
            battlefield_salience = sum(card_salience(perm.card, is_commander=perm.card.is_commander) for perm in state.battlefield) + 0.45 * sum(state.token_buckets.values())
            wipe_by = maybe_wipe_event(opponent_table, state, interaction_rng, turn, battlefield_salience)
            if wipe_by is not None:
                _apply_creature_wipe(state, commander_slots)
                _resolve_trigger_queue(state, current_intent="protect", fingerprint=fingerprint, winlines=winlines)

        if turn_outcome.tier == OutcomeTier.HARD_WIN:
            break

    dead_cards = [c.name for c in state.hand if c.mana_value > max(mana_by_turn)]

    return RunMetrics(
        mana_by_turn=mana_by_turn,
        lands_by_turn=lands_by_turn,
        colors_by_turn=colors_by_turn,
        actions_by_turn=actions_by_turn,
        phase_by_turn=phase_by_turn,
        mulligans_taken=mulligans_taken,
        commander_cast_turn=commander_cast_turn,
        cards_seen=cards_seen,
        ramp_online_turn=ramp_online_turn,
        draw_engine_turn=draw_engine_turn,
        dead_cards=dead_cards,
        plan_progress_by_turn=plan_progress,
        seen_cards=seen_cards,
        cast_cards=cast_cards,
        win_turn=win_turn,
        achieved_wincon=achieved_wincon,
        win_reason=win_reason,
        outcome_tier=outcome_tier,
        model_win_reason=model_win_reason,
        lock_established=lock_established,
        lock_plus_clock=lock_plus_clock,
        opponent_archetypes=[opponent.archetype for opponent in opponent_table.opponents],
        interaction_encountered=dict(opponent_table.interaction_events),
        answer_expenditure=dict(opponent_table.answer_expenditure),
        wipe_turns=list(opponent_table.wipe_turns),
        self_life=state.self_life,
        trace={
            "opening_hand": opening_hand,
            "mulligans_taken": mulligans_taken,
            "mulligan_steps": mulligan_steps,
            "commander_slots": [name for name in commander_slots if name],
            "opponent_table": opponent_table.to_payload(),
            "commander_tax_slots": list(state.commander_tax),
            "commander_casts_by_slot": list(state.commander_casts),
            "commander_damage_by_slot": [list(row) for row in state.opp_cmdr_dmg],
            "turns": turn_trace,
        }
        if capture_trace
        else None,
    )


def _percentile(xs: List[float], p: float) -> float:
    if not xs:
        return 0.0
    ys = sorted(xs)
    idx = int((len(ys) - 1) * p)
    return ys[idx]


def _binom_ci95(p: float, n: int) -> dict:
    if n <= 0:
        return {"low": 0.0, "high": 0.0}
    se = (p * (1 - p) / n) ** 0.5
    z = 1.96
    return {"low": max(0.0, p - z * se), "high": min(1.0, p + z * se)}


def _turn_sort_key(v: str):
    if v == "never":
        return (1, 10**9)
    try:
        return (0, int(v))
    except Exception:
        return (0, 0)


def run_simulation_batch(
    cards: List[dict],
    commander: str | List[str] | None,
    runs: int,
    turn_limit: int,
    policy: str,
    multiplayer: bool,
    threat_model: bool,
    seed: int,
    bracket: int = 3,
    primary_wincons: List[str] | None = None,
    color_identity_size: int = 3,
    combo_variants: List[Dict] | None = None,
    combo_source_live: bool = False,
    resolved_config: ResolvedSimConfig | Dict | None = None,
) -> Dict:
    if (
        runs >= 1024
        and commander in (None, [], "")
        and not combo_variants
        and not combo_source_live
        and not threat_model
    ):
        from sim.engine_vectorized import run_simulation_batch_vectorized

        return run_simulation_batch_vectorized(
            cards=cards,
            commander=commander,
            runs=runs,
            turn_limit=turn_limit,
            policy=policy,
            multiplayer=multiplayer,
            threat_model=threat_model,
            seed=seed,
            bracket=bracket,
            primary_wincons=primary_wincons,
            color_identity_size=color_identity_size,
            combo_variants=combo_variants,
            combo_source_live=combo_source_live,
            resolved_config=resolved_config,
        )

    resolved = coerce_resolved_sim_config(
        resolved_config,
        commander=commander,
        requested_policy=policy,
        bracket=bracket,
        turn_limit=turn_limit,
        multiplayer=multiplayer,
        threat_model=threat_model,
        primary_wincons=primary_wincons,
        color_identity_size=color_identity_size,
        seed=seed,
    )
    manager = RNGManager(resolved.seed)
    selected_wincons = list(resolved.selected_wincons)
    deck, commander_cards = _build_sim_deck(cards, [name for name in resolved.commander_slots if name])
    compiled_exec = compile_card_execs(cards)
    compiled_exec_lookup = {_normalize_name(exec_card.name): exec_card for exec_card in compiled_exec}
    fingerprint = compile_deck_fingerprint(deck, commander_cards, compiled_exec_lookup)
    winlines = compile_winlines(deck, fingerprint)
    normalized_combo_variants = _normalize_combo_variants(combo_variants)

    results: List[RunMetrics] = []
    decision_samples = []
    run_seeds: List[int] = []

    for i in range(runs):
        run_seed = manager.seed("run", i)
        run_seeds.append(run_seed)
        local_rng = random.Random(run_seed)
        out = simulate_one(
            deck,
            [name for name in resolved.commander_slots if name],
            commander_cards,
            turn_limit,
            resolved.policy.resolved_policy,
            multiplayer,
            threat_model,
            local_rng,
            primary_wincons=primary_wincons,
            color_identity_size=resolved.color_identity_size,
            combo_variants=normalized_combo_variants,
            combo_source_live=combo_source_live,
            capture_trace=(i == 0),
            resolved_config=resolved,
            run_seed=run_seed,
            compiled_exec_lookup=compiled_exec_lookup,
        )
        if i < 20:
            decision_samples.append(
                {
                    "run": i,
                    "commander_cast_turn": out.commander_cast_turn,
                    "ramp_online_turn": out.ramp_online_turn,
                    "draw_engine_turn": out.draw_engine_turn,
                    "dead_cards": out.dead_cards[:5],
                }
            )
        results.append(out)

    p_mana4_t3 = sum(1 for r in results if len(r.mana_by_turn) >= 3 and r.mana_by_turn[2] >= 4) / runs
    p_mana5_t4 = sum(1 for r in results if len(r.mana_by_turn) >= 4 and r.mana_by_turn[3] >= 5) / runs
    cmd_turns = [r.commander_cast_turn for r in results if r.commander_cast_turn is not None]

    per_turn_progress = defaultdict(list)
    for r in results:
        for t, score in enumerate(r.plan_progress_by_turn, start=1):
            per_turn_progress[t].append(score)

    failure_modes = Counter()
    hard_win_turns = [r.win_turn for r in results if r.outcome_tier == OutcomeTier.HARD_WIN.value and r.win_turn is not None]
    wincon_counter = Counter(r.achieved_wincon for r in results if r.achieved_wincon)
    outcome_counter = Counter(r.outcome_tier for r in results)
    model_wins = sum(1 for r in results if r.outcome_tier == OutcomeTier.MODEL_WIN.value)
    dominant_positions = sum(1 for r in results if r.outcome_tier == OutcomeTier.DOMINANT.value)
    lock_established_count = sum(1 for r in results if r.lock_established)
    lock_plus_clock_count = sum(1 for r in results if r.lock_plus_clock)
    interaction_counter = Counter()
    answer_spend_counter = Counter()
    wipe_turn_counter = Counter()
    archetype_counter = Counter()
    for r in results:
        if r.mana_by_turn[2] < 3:
            failure_modes["mana_screw"] += 1
        if max(r.mana_by_turn) > 10 and r.cards_seen < turn_limit + 6:
            failure_modes["flood"] += 1
        if not any(x > 3 for x in r.plan_progress_by_turn[:3]):
            failure_modes["no_action"] += 1
        if r.self_life <= 0:
            failure_modes["dead_before_conversion"] += 1
        interaction_counter.update(r.interaction_encountered)
        answer_spend_counter.update(r.answer_expenditure)
        wipe_turn_counter.update(str(turn) for turn in r.wipe_turns)
        archetype_counter.update(r.opponent_archetypes)

    card_seen_success = defaultdict(list)
    card_cast_success = defaultdict(list)
    tag_counter = Counter()
    for r in results:
        success = r.plan_progress_by_turn[-1]
        for c in r.seen_cards:
            card_seen_success[c].append(success)
        for c in r.cast_cards:
            card_cast_success[c].append(success)

    card_impacts = {}
    avg_success = sum(r.plan_progress_by_turn[-1] for r in results) / runs
    card_names = {c["name"] for c in cards}
    for c in card_names:
        seen_avg = sum(card_seen_success[c]) / len(card_seen_success[c]) if card_seen_success[c] else avg_success
        cast_avg = sum(card_cast_success[c]) / len(card_cast_success[c]) if card_cast_success[c] else avg_success
        card_impacts[c] = {
            "seen_lift": max(0.0, (seen_avg - avg_success) / (avg_success + 1e-6)),
            "cast_lift": max(0.0, (cast_avg - avg_success) / (avg_success + 1e-6)),
            "centrality": min(1.0, len(card_cast_success[c]) / max(1, runs * 0.5)),
            "redundancy": 0.5,
        }

    # Graph payloads for UI lenses.
    mana_percentiles = []
    land_hit_cdf = []
    color_access = []
    phase_timeline = []
    no_action_funnel = []
    action_rate = []
    win_turn_cdf = []
    mana_hit_table = []
    threshold_max = min(16, max(turn_limit + 4, max((c.get("mana_value", 0) for c in cards), default=0)))
    turn_win_counts = Counter(r.win_turn for r in results if r.win_turn is not None)
    cumulative_wins = 0
    phase_counter_by_turn = defaultdict(Counter)
    for r in results:
        for t, phase in enumerate(r.phase_by_turn, start=1):
            phase_counter_by_turn[t][phase] += 1

    for t in range(1, turn_limit + 1):
        mana_t = [r.mana_by_turn[t - 1] for r in results if len(r.mana_by_turn) >= t]
        lands_t = [r.lands_by_turn[t - 1] for r in results if len(r.lands_by_turn) >= t]
        colors_t = [r.colors_by_turn[t - 1] for r in results if len(r.colors_by_turn) >= t]
        actions_t = [r.actions_by_turn[t - 1] for r in results if len(r.actions_by_turn) >= t]
        if mana_t:
            mana_percentiles.append(
                {
                    "turn": t,
                    "p50": _percentile(mana_t, 0.5),
                    "p75": _percentile(mana_t, 0.75),
                    "p90": _percentile(mana_t, 0.9),
                }
            )
            hit_row = {"turn": t}
            for mv in range(1, threshold_max + 1):
                hit_row[f"p_ge_{mv}"] = sum(1 for x in mana_t if x >= mv) / len(mana_t)
            mana_hit_table.append(hit_row)
        if lands_t:
            land_hit_cdf.append({"turn": t, "p_hit_on_curve": sum(1 for x in lands_t if x >= t) / len(lands_t)})
        if colors_t:
            target = max(0, color_identity_size)
            color_access.append(
                {
                    "turn": t,
                    "avg_colors": sum(colors_t) / len(colors_t),
                    "p_full_identity": (sum(1 for x in colors_t if x >= target) / len(colors_t)) if target > 0 else 1.0,
                    "p_three_plus": (sum(1 for x in colors_t if x >= 3) / len(colors_t)) if target >= 3 else None,
                }
            )
        if actions_t:
            no_action_funnel.append({"turn": t, "p_no_action": sum(1 for x in actions_t if x == 0) / len(actions_t)})
            action_rate.append({"turn": t, "p_action": sum(1 for x in actions_t if x > 0) / len(actions_t)})
        phase_counts = phase_counter_by_turn[t]
        phase_timeline.append(
            {
                "turn": t,
                "setup": phase_counts["setup"] / runs,
                "engine": phase_counts["engine"] / runs,
                "win_attempt": phase_counts["win_attempt"] / runs,
            }
        )
        cumulative_wins += turn_win_counts.get(t, 0)
        win_turn_cdf.append({"turn": t, "cdf": cumulative_wins / runs})

    mana_curve_points = []
    for mv in range(0, threshold_max + 1):
        if mv <= 0:
            mana_curve_points.append({"mana_value": mv, "on_curve_turn": 1, "p_on_curve": 1.0})
            continue
        on_turn = min(turn_limit, mv)
        p_on_curve = sum(
            1
            for r in results
            if len(r.mana_by_turn) >= on_turn and r.mana_by_turn[on_turn - 1] >= mv
        ) / max(1, runs)
        mana_curve_points.append({"mana_value": mv, "on_curve_turn": on_turn, "p_on_curve": p_on_curve})

    commander_cast_dist = Counter(str(r.commander_cast_turn) if r.commander_cast_turn is not None else "never" for r in results)
    engine_online_dist = Counter(str(r.draw_engine_turn) if r.draw_engine_turn is not None else "never" for r in results)
    mulligan_funnel = Counter(str(r.mulligans_taken) for r in results)
    dead_counter = Counter(name for r in results for name in r.dead_cards)
    dead_cards_top = [{"card": k, "count": v, "rate": v / runs} for k, v in dead_counter.most_common(20)]

    fastest_wins: List[Dict] = []
    winners = [(r.win_turn, i) for i, r in enumerate(results) if r.win_turn is not None]
    winners.sort(key=lambda x: (int(x[0] or 10**9), x[1]))
    for rank, (win_t, idx) in enumerate(winners[:3], start=1):
        replay = simulate_one(
            deck,
            [name for name in resolved.commander_slots if name],
            commander_cards,
            turn_limit,
            resolved.policy.resolved_policy,
            multiplayer,
            threat_model,
            random.Random(run_seeds[idx]),
            primary_wincons=primary_wincons,
            color_identity_size=resolved.color_identity_size,
            combo_variants=normalized_combo_variants,
            combo_source_live=combo_source_live,
            capture_trace=True,
            resolved_config=resolved,
            run_seed=run_seeds[idx],
            compiled_exec_lookup=compiled_exec_lookup,
        )
        trace = replay.trace or {}
        fastest_wins.append(
            {
                "rank": rank,
                "run_index": idx,
                "seed": run_seeds[idx],
                "win_turn": replay.win_turn,
                "wincon": replay.achieved_wincon,
                "win_reason": replay.win_reason,
                "mulligans_taken": replay.mulligans_taken,
                "mulligan_steps": trace.get("mulligan_steps", []),
                "opening_hand": trace.get("opening_hand", []),
                "turns": (trace.get("turns", [])[: int(win_t)] if win_t else trace.get("turns", [])),
            }
        )

    coverage_summary = summarize_compiled_execs(compiled_exec)

    summary = {
        "runs": runs,
        "seed": resolved.seed,
        "policy": resolved.policy.resolved_policy,
        "turn_limit": turn_limit,
        "selected_wincons": selected_wincons,
        "backend_used": "python_reference",
        "resolved_policy": asdict(resolved.policy),
        "opponent_profile": asdict(resolved.opponent),
        "commander_slots": [name for name in resolved.commander_slots if name],
        "ir_version": 2,
        "coverage_summary": coverage_summary,
        "support_confidence": coverage_summary.get("support_confidence", 0.0),
        "deck_fingerprint": {
            "primary_plan": fingerprint.primary_plan,
            "secondary_plan": fingerprint.secondary_plan,
            "commander_role": fingerprint.commander_role,
            "speed_tier": fingerprint.speed_tier,
            "prefers_focus_fire": fingerprint.prefers_focus_fire,
            "protection_density": fingerprint.protection_density,
            "resource_profile": list(fingerprint.resource_profile),
            "conversion_profile": list(fingerprint.conversion_profile),
            "wipe_recovery": fingerprint.wipe_recovery,
        },
        "winlines": [
            {
                "kind": line.kind,
                "requirements": list(line.requirements),
                "support": list(line.support),
                "sink_requirements": list(line.sink_requirements),
                "horizon_class": line.horizon_class,
            }
            for line in winlines
        ],
        "milestones": {
            "p_mana4_t3": p_mana4_t3,
            "p_mana5_t4": p_mana5_t4,
            "median_commander_cast_turn": median(cmd_turns) if cmd_turns else None,
        },
        "win_metrics": {
            "p_win_by_turn_limit": (len(hard_win_turns) / runs) if runs else 0.0,
            "hard_win_rate": (len(hard_win_turns) / runs) if runs else 0.0,
            "model_win_rate": (model_wins / runs) if runs else 0.0,
            "dominant_rate": (dominant_positions / runs) if runs else 0.0,
            "lock_established_rate": (lock_established_count / runs) if runs else 0.0,
            "lock_plus_clock_rate": (lock_plus_clock_count / runs) if runs else 0.0,
            "median_win_turn": median(hard_win_turns) if hard_win_turns else None,
            "most_common_wincon": wincon_counter.most_common(1)[0][0] if wincon_counter else None,
            "wincon_distribution": {k: (v / runs) for k, v in wincon_counter.items()},
            "outcome_distribution": {k: (v / runs) for k, v in outcome_counter.items()},
        },
        "uncertainty": {
            "p_mana4_t3_ci95": _binom_ci95(p_mana4_t3, runs),
            "p_mana5_t4_ci95": _binom_ci95(p_mana5_t4, runs),
            "p_win_by_turn_limit_ci95": _binom_ci95((len(hard_win_turns) / runs) if runs else 0.0, runs),
        },
        "plan_progress": {
            t: {
                "median": median(v),
                "p90": _percentile(v, 0.9),
            }
            for t, v in per_turn_progress.items()
        },
        "failure_modes": {k: v / runs for k, v in failure_modes.items()},
        "opponent_model": {
            "archetype_distribution": {k: (v / max(1, runs * 3)) for k, v in archetype_counter.items()},
            "interaction_encountered_rate": {k: (v / runs) for k, v in interaction_counter.items()},
            "answer_expenditure_rate": {k: (v / runs) for k, v in answer_spend_counter.items()},
            "wipe_turn_distribution": {k: (v / runs) for k, v in wipe_turn_counter.items()},
            "avg_self_life_end": (sum(r.self_life for r in results) / runs) if runs else 40.0,
        },
        "card_impacts": card_impacts,
        "fastest_wins": fastest_wins,
        "decision_samples": decision_samples,
        "reference_trace": results[0].trace if results and results[0].trace else {},
        "graph_payloads": {
            "mana_percentiles": mana_percentiles,
            "mana_hit_table": mana_hit_table,
            "mana_curve_points": mana_curve_points,
            "land_hit_cdf": land_hit_cdf,
            "color_access": color_access,
            "phase_timeline": phase_timeline,
            "no_action_funnel": no_action_funnel,
            "action_rate": action_rate,
            "win_turn_cdf": win_turn_cdf,
            "commander_cast_distribution": [{"turn": k, "count": v, "rate": v / runs} for k, v in sorted(commander_cast_dist.items(), key=lambda kv: _turn_sort_key(kv[0]))],
            "engine_online_distribution": [{"turn": k, "count": v, "rate": v / runs} for k, v in sorted(engine_online_dist.items(), key=lambda kv: _turn_sort_key(kv[0]))],
            "mulligan_funnel": [{"mulligans": k, "count": v, "rate": v / runs} for k, v in sorted(mulligan_funnel.items(), key=lambda kv: kv[0])],
            "dead_cards_top": dead_cards_top,
        },
        "color_profile": {
            "color_identity_size": resolved.color_identity_size,
        },
        "combo_detection": {
            "source_live": combo_source_live,
            "matched_variants": len(normalized_combo_variants),
        },
    }
    summary["hard_win_rate"] = summary["win_metrics"]["hard_win_rate"]
    summary["model_win_rate"] = summary["win_metrics"]["model_win_rate"]
    summary["dominant_rate"] = summary["win_metrics"]["dominant_rate"]
    summary["lock_established_rate"] = summary["win_metrics"]["lock_established_rate"]
    summary["lock_plus_clock_rate"] = summary["win_metrics"]["lock_plus_clock_rate"]
    summary["outcome_distribution"] = dict(summary["win_metrics"]["outcome_distribution"])
    summary["most_common_wincon"] = summary["win_metrics"]["most_common_wincon"]

    return {"summary": summary}
