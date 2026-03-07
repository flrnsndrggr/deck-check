from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from statistics import median
from typing import Dict, List

import numpy as np

from sim.config import (
    MAX_COMMANDERS,
    ResolvedSimConfig,
    coerce_resolved_sim_config,
    normalize_selected_wincons,
)
from sim.ir import compile_card_execs, summarize_compiled_execs
from sim.rng import RNGManager
from sim.tiebreak import stable_sorted


@dataclass
class _DeckArrays:
    names: List[str]
    mana_value: np.ndarray
    power: np.ndarray
    is_land: np.ndarray
    is_ramp: np.ndarray
    is_fast_mana: np.ndarray
    is_early_action: np.ndarray
    is_fixing: np.ndarray
    is_permanent: np.ndarray
    is_creature: np.ndarray
    is_artifact: np.ndarray
    is_draw: np.ndarray
    is_engine: np.ndarray
    is_payoff: np.ndarray
    is_wincon: np.ndarray
    is_combo: np.ndarray
    is_tutor: np.ndarray
    is_setup: np.ndarray
    is_removal: np.ndarray
    is_counter: np.ndarray
    is_stax: np.ndarray
    has_haste: np.ndarray
    evasion_score: np.ndarray
    combat_buff: np.ndarray
    commander_buff: np.ndarray
    token_attack_power: np.ndarray
    token_bodies: np.ndarray
    extra_combat_factor: np.ndarray
    infect: np.ndarray
    toxic: np.ndarray
    proliferate: np.ndarray
    burn_value: np.ndarray
    repeatable_burn: np.ndarray
    mill_value: np.ndarray
    repeatable_mill: np.ndarray
    alt_win_code: np.ndarray


def _normalize_name(name: str | None) -> str:
    return (name or "").strip().lower()


_ALT_WIN_CODE = {
    None: 0,
    "": 0,
    "generic": 0,
    "life40": 2,
    "artifacts20": 3,
    "creatures20": 4,
    "graveyard20": 5,
    "library2": 6,
    "library0": 7,
    "hand0": 8,
    "life1": 9,
}


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


def _percentile(xs: np.ndarray, p: float) -> float:
    if xs.size == 0:
        return 0.0
    idx = int((xs.size - 1) * p)
    return float(np.sort(xs)[idx])


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


def _separate_sim_cards(cards: List[dict], commander: str | List[str] | None) -> tuple[List[dict], List[dict]]:
    commander_keys = {
        _normalize_name(name)
        for name in ([commander] if isinstance(commander, str) else list(commander or []))
        if _normalize_name(str(name))
    }
    main_cards: List[dict] = []
    commander_cards: List[dict] = []

    for card in cards:
        name = str(card.get("name", "")).strip()
        section = str(card.get("section", "deck") or "deck").strip().lower()
        is_commander = _normalize_name(name) in commander_keys

        if is_commander and (section == "commander" or not any(_normalize_name(existing.get("name")) == _normalize_name(name) for existing in commander_cards)):
            commander_cards.append(card)
            if section != "deck":
                continue
        if section != "deck":
            continue
        if is_commander:
            continue
        main_cards.append(card)

    return main_cards, commander_cards


def _normalize_combo_variants(combo_variants: List[Dict] | None) -> List[Dict]:
    normalized: List[Dict] = []
    for variant in combo_variants or []:
        raw_cards = variant.get("cards") or []
        cards = []
        keys = set()
        for name in raw_cards:
            key = _normalize_name(str(name))
            if not key:
                continue
            cards.append(str(name).strip())
            keys.add(key)
        if not keys:
            continue
        normalized.append(
            {
                "variant_id": str(variant.get("variant_id") or ""),
                "cards": cards,
                "keys": keys,
            }
        )
    return normalized


def _prepare_combo_requirements(deck_names: List[str], combo_variants: List[Dict], commander: str | List[str] | None) -> List[Dict]:
    if not combo_variants:
        return []
    commander_keys = {
        _normalize_name(name)
        for name in ([commander] if isinstance(commander, str) else list(commander or []))
        if _normalize_name(str(name))
    }
    name_to_indices: Dict[str, List[int]] = defaultdict(list)
    for idx, name in enumerate(deck_names):
        name_to_indices[_normalize_name(name)].append(idx)

    requirements: List[Dict] = []
    for variant in combo_variants:
        groups = []
        required_commanders: set[str] = set()
        valid = True
        for key in variant["keys"]:
            if key in commander_keys:
                required_commanders.add(key)
                continue
            idxs = name_to_indices.get(key, [])
            if not idxs:
                valid = False
                break
            groups.append(np.array(idxs, dtype=np.int32))
        if valid:
            requirements.append(
                {
                    "cards": variant["cards"],
                    "groups": groups,
                    "required_commanders": required_commanders,
                }
            )
    return requirements


def _detect_live_combo_hits(
    on_battlefield: np.ndarray,
    commander_cast_turn: np.ndarray,
    combo_requirements: List[Dict],
    commander_names: List[str | None],
) -> tuple[np.ndarray, np.ndarray]:
    batch_n = on_battlefield.shape[0]
    hit_mask = np.zeros(batch_n, dtype=bool)
    reasons = np.array([""] * batch_n, dtype=object)
    if not combo_requirements:
        return hit_mask, reasons

    for requirement in combo_requirements:
        requirement_hit = np.ones(batch_n, dtype=bool)
        for idxs in requirement["groups"]:
            requirement_hit &= on_battlefield[:, idxs].any(axis=1)
        required_commanders = requirement.get("required_commanders") or set()
        if required_commanders:
            for commander_name in required_commanders:
                slot = next((idx for idx, name in enumerate(commander_names) if _normalize_name(name) == commander_name), None)
                if slot is None:
                    requirement_hit &= False
                    continue
                requirement_hit &= commander_cast_turn[:, slot] > 0
        new_hit = requirement_hit & ~hit_mask
        if new_hit.any():
            hit_mask[new_hit] = True
            reasons[new_hit] = (
                "All required cards for the CommanderSpellbook combo are live: "
                + ", ".join(requirement["cards"])
                + "."
            )
    return hit_mask, reasons


def _expand_deck(cards: List[dict]) -> _DeckArrays:
    names: List[str] = []
    mana_values: List[int] = []
    powers: List[float] = []
    flags = {
        "is_land": [],
        "is_ramp": [],
        "is_fast_mana": [],
        "is_early_action": [],
        "is_fixing": [],
        "is_permanent": [],
        "is_creature": [],
        "is_artifact": [],
        "is_draw": [],
        "is_engine": [],
        "is_payoff": [],
        "is_wincon": [],
        "is_combo": [],
        "is_tutor": [],
        "is_setup": [],
        "is_removal": [],
        "is_counter": [],
        "is_stax": [],
        "has_haste": [],
        "infect": [],
        "proliferate": [],
    }
    evasion_scores: List[float] = []
    combat_buffs: List[float] = []
    commander_buffs: List[float] = []
    token_attack_powers: List[float] = []
    token_bodies: List[float] = []
    extra_combats: List[float] = []
    toxics: List[float] = []
    burn_values: List[float] = []
    repeatable_burns: List[float] = []
    mill_values: List[float] = []
    repeatable_mills: List[float] = []
    alt_win_codes: List[int] = []

    for c in cards:
        qty = int(c.get("qty", 1))
        name = str(c.get("name", "")).strip()
        tags = set(c.get("tags", []) or [])
        mv = int(c.get("mana_value", 2))
        power = float(c.get("power") or 0.0)
        is_land = "#Land" in tags
        is_ramp = "#Ramp" in tags
        is_fixing = "#Fixing" in tags and (is_land or is_ramp)
        is_fast = "#FastMana" in tags or (is_ramp and mv <= 2)
        is_early_action = mv <= 2 and bool(tags & {"#Ramp", "#Draw", "#Setup"})
        is_permanent = bool(c.get("is_permanent", False))
        is_creature = bool(c.get("is_creature", False))
        is_artifact = "artifact" in str(c.get("type_line") or "").lower()
        has_haste = bool(c.get("has_haste", False))
        infect = bool(c.get("infect", False))
        proliferate = bool(c.get("proliferate", False))
        evasion = float(c.get("evasion_score") or 0.0)
        combat_buff = float(c.get("combat_buff") or 0.0)
        commander_buff = float(c.get("commander_buff") or 0.0)
        token_power = float(c.get("token_attack_power") or 0.0)
        token_body_count = float(c.get("token_bodies") or 0.0)
        extra_combat = float(c.get("extra_combat_factor") or 1.0)
        toxic = float(c.get("toxic") or 0.0)
        burn_value = float(c.get("burn_value") or 0.0)
        repeatable_burn = float(c.get("repeatable_burn") or 0.0)
        mill_value = float(c.get("mill_value") or 0.0)
        repeatable_mill = float(c.get("repeatable_mill") or 0.0)
        alt_win_code = _ALT_WIN_CODE.get(c.get("alt_win_kind"), 0)

        for _ in range(max(1, qty)):
            names.append(name)
            mana_values.append(mv)
            powers.append(power)
            flags["is_land"].append(is_land)
            flags["is_ramp"].append(is_ramp)
            flags["is_fast_mana"].append(is_fast)
            flags["is_early_action"].append(is_early_action)
            flags["is_fixing"].append(is_fixing)
            flags["is_permanent"].append(is_permanent)
            flags["is_creature"].append(is_creature)
            flags["is_artifact"].append(is_artifact)
            flags["is_draw"].append("#Draw" in tags)
            flags["is_engine"].append("#Engine" in tags)
            flags["is_payoff"].append("#Payoff" in tags)
            flags["is_wincon"].append("#Wincon" in tags)
            flags["is_combo"].append("#Combo" in tags)
            flags["is_tutor"].append("#Tutor" in tags)
            flags["is_setup"].append("#Setup" in tags)
            flags["is_removal"].append("#Removal" in tags)
            flags["is_counter"].append("#Counter" in tags)
            flags["is_stax"].append("#Stax" in tags)
            flags["has_haste"].append(has_haste)
            flags["infect"].append(infect)
            flags["proliferate"].append(proliferate)
            evasion_scores.append(evasion)
            combat_buffs.append(combat_buff)
            commander_buffs.append(commander_buff)
            token_attack_powers.append(token_power)
            token_bodies.append(token_body_count)
            extra_combats.append(extra_combat)
            toxics.append(toxic)
            burn_values.append(burn_value)
            repeatable_burns.append(repeatable_burn)
            mill_values.append(mill_value)
            repeatable_mills.append(repeatable_mill)
            alt_win_codes.append(alt_win_code)

    return _DeckArrays(
        names=names,
        mana_value=np.array(mana_values, dtype=np.int16),
        power=np.array(powers, dtype=np.float32),
        is_land=np.array(flags["is_land"], dtype=bool),
        is_ramp=np.array(flags["is_ramp"], dtype=bool),
        is_fast_mana=np.array(flags["is_fast_mana"], dtype=bool),
        is_early_action=np.array(flags["is_early_action"], dtype=bool),
        is_fixing=np.array(flags["is_fixing"], dtype=bool),
        is_permanent=np.array(flags["is_permanent"], dtype=bool),
        is_creature=np.array(flags["is_creature"], dtype=bool),
        is_artifact=np.array(flags["is_artifact"], dtype=bool),
        is_draw=np.array(flags["is_draw"], dtype=bool),
        is_engine=np.array(flags["is_engine"], dtype=bool),
        is_payoff=np.array(flags["is_payoff"], dtype=bool),
        is_wincon=np.array(flags["is_wincon"], dtype=bool),
        is_combo=np.array(flags["is_combo"], dtype=bool),
        is_tutor=np.array(flags["is_tutor"], dtype=bool),
        is_setup=np.array(flags["is_setup"], dtype=bool),
        is_removal=np.array(flags["is_removal"], dtype=bool),
        is_counter=np.array(flags["is_counter"], dtype=bool),
        is_stax=np.array(flags["is_stax"], dtype=bool),
        has_haste=np.array(flags["has_haste"], dtype=bool),
        evasion_score=np.array(evasion_scores, dtype=np.float32),
        combat_buff=np.array(combat_buffs, dtype=np.float32),
        commander_buff=np.array(commander_buffs, dtype=np.float32),
        token_attack_power=np.array(token_attack_powers, dtype=np.float32),
        token_bodies=np.array(token_bodies, dtype=np.float32),
        extra_combat_factor=np.array(extra_combats, dtype=np.float32),
        infect=np.array(flags["infect"], dtype=bool),
        toxic=np.array(toxics, dtype=np.float32),
        proliferate=np.array(flags["proliferate"], dtype=bool),
        burn_value=np.array(burn_values, dtype=np.float32),
        repeatable_burn=np.array(repeatable_burns, dtype=np.float32),
        mill_value=np.array(mill_values, dtype=np.float32),
        repeatable_mill=np.array(repeatable_mills, dtype=np.float32),
        alt_win_code=np.array(alt_win_codes, dtype=np.int16),
    )


def _evaluate_keep(hand_idx: np.ndarray, deck: _DeckArrays, policy: str, colors_required: int) -> np.ndarray:
    lands = deck.is_land[hand_idx].sum(axis=1)
    early = deck.is_early_action[hand_idx].any(axis=1)
    fast_mana = deck.is_fast_mana[hand_idx].any(axis=1)
    fixing = deck.is_fixing[hand_idx].any(axis=1)

    if policy in {"cedh", "cEDH-like speed"}:
        one_land_fast = (lands == 1) & fast_mana & early
        return one_land_fast | ((lands >= 1) & (lands <= 4) & (early | fast_mana))

    keep = (lands >= 2) & (lands <= 5) & early
    if colors_required >= 3:
        keep &= fixing
    return keep


def _roll_openers(
    run_seeds: np.ndarray,
    deck: _DeckArrays,
    batch_n: int,
    policy: str,
    multiplayer: bool,
    colors_required: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, List[List[dict]]]:
    deck_size = deck.mana_value.size
    final_orders = np.empty((batch_n, deck_size), dtype=np.int16)
    mulligans = np.zeros(batch_n, dtype=np.int8)
    hand_sizes = np.full(batch_n, 7, dtype=np.int8)
    mulligan_logs: List[List[dict]] = [[] for _ in range(batch_n)]

    unresolved = np.arange(batch_n, dtype=np.int32)
    attempt = 0
    while unresolved.size > 0:
        cand_orders = np.empty((unresolved.size, deck_size), dtype=np.int16)
        for local_idx, global_idx in enumerate(unresolved.tolist()):
            cand_orders[local_idx] = RNGManager(int(run_seeds[global_idx])).permutation("mulligan", deck_size, attempt)
        keeps = _evaluate_keep(cand_orders[:, :7], deck, policy, colors_required)
        for local_idx, global_idx in enumerate(unresolved.tolist()):
            mulligan_logs[global_idx].append(
                {
                    "attempt": int(attempt),
                    "hand_idx": cand_orders[local_idx, :7].astype(int).tolist(),
                    "kept": bool(keeps[local_idx]),
                }
            )
        if attempt >= 3:
            keeps[:] = True

        accepted_global = unresolved[keeps]
        if accepted_global.size:
            final_orders[accepted_global] = cand_orders[keeps]
            mulligans[accepted_global] = attempt
            bottoms = attempt
            if multiplayer and attempt == 1:
                bottoms = 0
            hand_sizes[accepted_global] = max(0, 7 - bottoms)
            accepted_local = np.where(keeps)[0]
            for g, l in zip(accepted_global.tolist(), accepted_local.tolist()):
                mulligan_logs[g][-1]["bottom_count"] = int(bottoms)
                mulligan_logs[g][-1]["kept_hand_idx"] = cand_orders[l, : int(hand_sizes[g])].astype(int).tolist()

        unresolved = unresolved[~keeps]
        attempt += 1

    return final_orders, hand_sizes, mulligans, mulligan_logs


def _cast_stage(
    role_mask: np.ndarray,
    stage_priority: np.ndarray,
    in_hand: np.ndarray,
    on_battlefield: np.ndarray,
    cast_mask: np.ndarray,
    available_mana: np.ndarray,
    mana_value: np.ndarray,
    actions_this_turn: np.ndarray,
    send_to_battlefield: bool = True,
    battlefield_mask: np.ndarray | None = None,
    max_loops: int = 24,
) -> np.ndarray:
    batch_n, deck_n = in_hand.shape
    large = 10**6
    rows = np.arange(batch_n, dtype=np.int32)
    chosen_any = np.zeros(batch_n, dtype=bool)

    for _ in range(max_loops):
        playable = in_hand & role_mask[np.newaxis, :] & (mana_value[np.newaxis, :] <= available_mana[:, np.newaxis])
        if not playable.any():
            break
        scores = np.where(playable, stage_priority[np.newaxis, :], large)
        chosen = scores.argmin(axis=1)
        min_scores = scores[rows, chosen]
        can_cast = min_scores < large
        if not can_cast.any():
            break

        r = rows[can_cast]
        c = chosen[can_cast]
        available_mana[r] -= mana_value[c]
        in_hand[r, c] = False
        cast_mask[r, c] = True
        actions_this_turn[r] += 1
        chosen_any[r] = True
        if send_to_battlefield:
            if battlefield_mask is None:
                on_battlefield[r, c] = True
            else:
                keep = battlefield_mask[c]
                if keep.any():
                    on_battlefield[r[keep], c[keep]] = True

    return chosen_any


def run_simulation_batch_vectorized(
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
    batch_size: int = 512,
    resolved_config: ResolvedSimConfig | Dict | None = None,
) -> Dict:
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
    if runs <= 0:
        return {"summary": {"runs": 0}}

    policy = resolved.policy.resolved_policy
    selected_wincons = list(resolved.selected_wincons)
    colors_req = resolved.color_identity_size

    commander_names = [name for name in resolved.commander_slots if name]
    main_cards, commander_cards = _separate_sim_cards(cards, commander_names)
    deck = _expand_deck(main_cards)
    compiled_exec = compile_card_execs(cards)
    deck_size = deck.mana_value.size
    if deck_size == 0:
        return {"summary": {"runs": runs, "seed": seed, "policy": policy, "turn_limit": turn_limit}}

    run_seed_manager = RNGManager(resolved.seed)
    cmd_names: List[str | None] = list(resolved.commander_slots)
    cmd_mana_values = np.full(MAX_COMMANDERS, -1, dtype=np.int16)
    cmd_powers = np.zeros(MAX_COMMANDERS, dtype=np.float32)
    cmd_has_haste = np.zeros(MAX_COMMANDERS, dtype=bool)
    cmd_evasion = np.zeros(MAX_COMMANDERS, dtype=np.float32)
    commander_cards_by_name = {_normalize_name(str(card.get("name"))): card for card in commander_cards}
    for slot, commander_name in enumerate(cmd_names[:MAX_COMMANDERS]):
        if not commander_name:
            continue
        commander_card = commander_cards_by_name.get(_normalize_name(commander_name))
        if commander_card is None:
            continue
        cmd_mana_values[slot] = int(commander_card.get("mana_value", 0) or 0)
        cmd_powers[slot] = float(commander_card.get("power") or 0.0)
        cmd_has_haste[slot] = bool(commander_card.get("has_haste", False))
        cmd_evasion[slot] = float(commander_card.get("evasion_score") or 0.0)
    normalized_combo_variants = _normalize_combo_variants(combo_variants)
    combo_requirements = _prepare_combo_requirements(deck.names, normalized_combo_variants, commander_names)

    all_mana = []
    all_lands = []
    all_colors = []
    all_actions = []
    all_plan_progress = []
    all_phase_setup = []
    all_phase_engine = []
    all_phase_win = []
    all_mulligans = []
    all_commander_turn = []
    all_draw_engine_turn = []
    all_cards_seen = []
    all_seen_masks = []
    all_cast_masks = []
    all_opening_masks = []
    all_draw_idx = []
    all_land_idx = []
    all_cast_by_turn = []
    all_mulligan_logs: List[List[dict]] = []
    all_win_turn = []
    all_achieved = []
    all_win_reason = []

    decision_samples = []
    dead_counter = Counter()
    run_offset = 0

    turn_idx = np.arange(1, turn_limit + 1, dtype=np.int16)

    while run_offset < runs:
        batch_n = min(batch_size, runs - run_offset)
        run_seed_slice = np.array(
            [run_seed_manager.seed("run", run_offset + idx) for idx in range(batch_n)],
            dtype=np.int64,
        )
        orders, hand_sizes, mulligans, mulligan_logs = _roll_openers(run_seed_slice, deck, batch_n, policy, multiplayer, colors_req)
        positions = np.empty_like(orders)
        positions[np.arange(batch_n)[:, np.newaxis], orders] = np.arange(deck_size, dtype=np.int16)

        in_hand = np.zeros((batch_n, deck_size), dtype=bool)
        for r in range(batch_n):
            hs = int(hand_sizes[r])
            if hs > 0:
                in_hand[r, orders[r, :hs]] = True

        opening_mask = in_hand.copy()
        seen_mask = in_hand.copy()
        cast_mask = np.zeros((batch_n, deck_size), dtype=bool)
        on_battlefield = np.zeros((batch_n, deck_size), dtype=bool)
        library_pos = np.full(batch_n, 7, dtype=np.int16)
        cards_seen = hand_sizes.astype(np.int16).copy()
        draw_idx = np.full((batch_n, turn_limit), -1, dtype=np.int16)
        land_idx = np.full((batch_n, turn_limit), -1, dtype=np.int16)
        cast_by_turn = np.zeros((batch_n, turn_limit, deck_size), dtype=bool)

        commander_cast_turn = np.zeros((batch_n, MAX_COMMANDERS), dtype=np.int16)
        commander_tax = np.zeros((batch_n, MAX_COMMANDERS), dtype=np.int16)
        commander_casts = np.zeros((batch_n, MAX_COMMANDERS), dtype=np.int16)
        draw_engine_turn = np.zeros(batch_n, dtype=np.int16)
        ramp_online_turn = np.zeros(batch_n, dtype=np.int16)
        win_turn = np.zeros(batch_n, dtype=np.int16)
        achieved_wincon = np.array([""] * batch_n, dtype=object)
        achieved_reason = np.array([""] * batch_n, dtype=object)
        graveyard_count = np.zeros(batch_n, dtype=np.int16)
        combat_damage_total = np.zeros(batch_n, dtype=np.float32)
        commander_damage_total = np.zeros((batch_n, MAX_COMMANDERS, 3), dtype=np.float32)
        poison_total = np.zeros(batch_n, dtype=np.float32)
        burn_total = np.zeros(batch_n, dtype=np.float32)
        mill_total = np.zeros(batch_n, dtype=np.float32)

        mana_by_turn = np.zeros((batch_n, turn_limit), dtype=np.int16)
        lands_by_turn = np.zeros((batch_n, turn_limit), dtype=np.int16)
        colors_by_turn = np.zeros((batch_n, turn_limit), dtype=np.int16)
        actions_by_turn = np.zeros((batch_n, turn_limit), dtype=np.int16)
        phase_setup = np.zeros((batch_n, turn_limit), dtype=bool)
        phase_engine = np.zeros((batch_n, turn_limit), dtype=bool)
        phase_win = np.zeros((batch_n, turn_limit), dtype=bool)
        plan_progress = np.zeros((batch_n, turn_limit), dtype=np.float32)

        ramp_priority = np.where(deck.is_fast_mana, 0, 1000) + deck.mana_value
        draw_priority = deck.mana_value.astype(np.int32)
        plan_priority = np.where(deck.is_engine, 0, 50) + np.where(deck.is_setup, 10, 0) + np.where(deck.is_payoff | deck.is_wincon, 20, 0) + deck.mana_value
        interaction_priority = deck.mana_value.astype(np.int32)

        row_ids = np.arange(batch_n, dtype=np.int32)
        for t in range(turn_limit):
            cast_before_turn = cast_mask.copy()
            turn = t + 1
            actions_this_turn = np.zeros(batch_n, dtype=np.int16)
            cast_combo_turn = np.zeros(batch_n, dtype=bool)
            cast_tutor_turn = np.zeros(batch_n, dtype=bool)
            cast_wincon_turn = np.zeros(batch_n, dtype=bool)
            cast_payoff_turn = np.zeros(batch_n, dtype=bool)

            # Draw step
            can_draw = library_pos < deck_size
            if can_draw.any():
                r = row_ids[can_draw]
                c = orders[r, library_pos[r]]
                in_hand[r, c] = True
                seen_mask[r, c] = True
                draw_idx[r, t] = c
                library_pos[r] += 1
                cards_seen[r] += 1

            # Land drop
            land_playable = in_hand & deck.is_land[np.newaxis, :]
            if land_playable.any():
                masked_pos = np.where(land_playable, positions, deck_size + 10_000)
                choice = masked_pos.argmin(axis=1)
                can_land = masked_pos[row_ids, choice] < deck_size + 1
                if can_land.any():
                    r = row_ids[can_land]
                    c = choice[can_land]
                    in_hand[r, c] = False
                    on_battlefield[r, c] = True
                    land_idx[r, t] = c

            available_mana = (on_battlefield & (deck.is_land[np.newaxis, :] | deck.is_ramp[np.newaxis, :])).sum(axis=1).astype(np.int16)

            # 2) ramp stage
            pre_ramp_cast = cast_mask.copy()
            ramp_casted = _cast_stage(
                role_mask=(deck.is_ramp | deck.is_fast_mana),
                stage_priority=ramp_priority,
                in_hand=in_hand,
                on_battlefield=on_battlefield,
                cast_mask=cast_mask,
                available_mana=available_mana,
                mana_value=deck.mana_value,
                actions_this_turn=actions_this_turn,
                send_to_battlefield=True,
                battlefield_mask=deck.is_permanent,
            )
            ramp_delta = cast_mask & ~pre_ramp_cast
            graveyard_count += (ramp_delta & ~deck.is_permanent[np.newaxis, :]).sum(axis=1).astype(np.int16)
            if ramp_casted.any():
                cast_tutor_turn |= False

            # 3) draw stage
            pre_draw_cast = cast_mask.copy()
            draw_casted = _cast_stage(
                role_mask=deck.is_draw,
                stage_priority=draw_priority,
                in_hand=in_hand,
                on_battlefield=on_battlefield,
                cast_mask=cast_mask,
                available_mana=available_mana,
                mana_value=deck.mana_value,
                actions_this_turn=actions_this_turn,
                send_to_battlefield=True,
                battlefield_mask=deck.is_permanent,
            )
            draw_delta = cast_mask & ~pre_draw_cast
            graveyard_count += (draw_delta & ~deck.is_permanent[np.newaxis, :]).sum(axis=1).astype(np.int16)
            new_draw = (draw_engine_turn == 0) & draw_casted
            draw_engine_turn[new_draw] = turn

            # 4) commander cast stage
            should_cast = ((policy in {"commander-centric", "optimized", "casual"}) and turn >= 3) or (
                policy == "hold commander" and turn >= 5
            )
            if should_cast:
                commander_order = stable_sorted(
                    [
                        (slot, cmd_names[slot], int(cmd_mana_values[slot]))
                        for slot in range(MAX_COMMANDERS)
                        if cmd_names[slot] and cmd_mana_values[slot] >= 0
                    ],
                    key=lambda item: (item[2], str(item[1])),
                )
                for slot, _name, mana_value in commander_order:
                    cmd_cost = int(mana_value) + commander_tax[:, slot]
                    can_cmd = (commander_cast_turn[:, slot] == 0) & (available_mana >= cmd_cost)
                    if can_cmd.any():
                        available_mana[can_cmd] -= cmd_cost[can_cmd]
                        commander_cast_turn[can_cmd, slot] = turn
                        commander_casts[can_cmd, slot] += 1

            # 5/6) plan pieces
            plan_role = deck.is_payoff | deck.is_engine | deck.is_setup | deck.is_tutor | deck.is_wincon | deck.is_combo
            pre_cast = cast_mask.copy()
            _cast_stage(
                role_mask=plan_role,
                stage_priority=plan_priority,
                in_hand=in_hand,
                on_battlefield=on_battlefield,
                cast_mask=cast_mask,
                available_mana=available_mana,
                mana_value=deck.mana_value,
                actions_this_turn=actions_this_turn,
                send_to_battlefield=True,
                battlefield_mask=deck.is_permanent,
            )
            new_cast = cast_mask & ~pre_cast
            graveyard_count += (new_cast & ~deck.is_permanent[np.newaxis, :]).sum(axis=1).astype(np.int16)
            if new_cast.any():
                cast_combo_turn = (new_cast & deck.is_combo[np.newaxis, :]).any(axis=1)
                cast_tutor_turn = (new_cast & deck.is_tutor[np.newaxis, :]).any(axis=1)
                cast_wincon_turn = (new_cast & deck.is_wincon[np.newaxis, :]).any(axis=1)
                cast_payoff_turn = (new_cast & (deck.is_payoff | deck.is_wincon | deck.is_combo)[np.newaxis, :]).any(axis=1)

            # 7) optional interaction usage
            if threat_model and turn >= 2:
                threat_event = rng.random(batch_n) < 0.25
                if threat_event.any():
                    pre_cast_int = cast_mask.copy()
                    _cast_stage(
                        role_mask=(deck.is_removal | deck.is_counter),
                        stage_priority=interaction_priority,
                        in_hand=in_hand,
                        on_battlefield=on_battlefield,
                        cast_mask=cast_mask,
                        available_mana=available_mana,
                        mana_value=deck.mana_value,
                        actions_this_turn=actions_this_turn,
                        send_to_battlefield=False,
                        max_loops=1,
                    )
                    interaction_delta = cast_mask & ~pre_cast_int
                    graveyard_count += interaction_delta.sum(axis=1).astype(np.int16)
                    # Keep usage deterministic; cast only in rows with event.
                    reverted = ~threat_event
                    if reverted.any():
                        delta = cast_mask & ~pre_cast_int
                        cast_mask[reverted] = pre_cast_int[reverted]
                        in_hand[reverted] |= delta[reverted]
                        graveyard_count[reverted] -= delta[reverted].sum(axis=1).astype(np.int16)
                        actions_this_turn[reverted] -= delta[reverted].sum(axis=1).astype(np.int16)
                        # no mana rewind needed for reverted rows because we only use this for metrics downstream

            cast_by_turn[:, t, :] = cast_mask & ~cast_before_turn

            mana_total = (on_battlefield & (deck.is_land[np.newaxis, :] | deck.is_ramp[np.newaxis, :])).sum(axis=1).astype(np.int16)
            lands_total = (on_battlefield & deck.is_land[np.newaxis, :]).sum(axis=1).astype(np.int16)
            fixing_total = (on_battlefield & deck.is_fixing[np.newaxis, :]).sum(axis=1).astype(np.int16)

            if colors_req <= 0:
                colors_total = np.zeros(batch_n, dtype=np.int16)
            elif colors_req == 1:
                colors_total = np.ones(batch_n, dtype=np.int16)
            else:
                colors_total = np.minimum(colors_req, np.maximum(1, fixing_total + 1)).astype(np.int16)

            mana_by_turn[:, t] = mana_total
            lands_by_turn[:, t] = lands_total
            colors_by_turn[:, t] = colors_total
            actions_by_turn[:, t] = actions_this_turn

            engine_count = (on_battlefield & deck.is_engine[np.newaxis, :]).sum(axis=1)
            draw_count = (on_battlefield & deck.is_draw[np.newaxis, :]).sum(axis=1)
            current_turn_cast = cast_by_turn[:, t, :]
            summoning_sick = current_turn_cast & deck.is_creature[np.newaxis, :] & ~deck.has_haste[np.newaxis, :]
            attackers = on_battlefield & deck.is_creature[np.newaxis, :] & ~summoning_sick
            attacker_count = attackers.sum(axis=1).astype(np.float32)
            base_attack_power = (attackers * deck.power[np.newaxis, :]).sum(axis=1)
            combat_buff_total = (on_battlefield * deck.combat_buff[np.newaxis, :]).sum(axis=1)
            commander_buff_total = (on_battlefield * deck.commander_buff[np.newaxis, :]).sum(axis=1)
            eligible_token_sources = on_battlefield & ~(current_turn_cast & ~deck.has_haste[np.newaxis, :])
            token_power_total = (eligible_token_sources * deck.token_attack_power[np.newaxis, :]).sum(axis=1)
            token_bodies_total = (eligible_token_sources * deck.token_bodies[np.newaxis, :]).sum(axis=1)
            attack_body_count = attacker_count + token_bodies_total
            extra_combat = np.where(on_battlefield, deck.extra_combat_factor[np.newaxis, :], 1.0).max(axis=1)
            avg_evasion = np.divide(
                (attackers * deck.evasion_score[np.newaxis, :]).sum(axis=1),
                np.maximum(1.0, attacker_count),
            )
            evasion_factor = np.minimum(1.0, 0.55 + avg_evasion)
            combat_damage_turn = (base_attack_power + token_power_total + combat_buff_total * attack_body_count) * extra_combat * evasion_factor
            commander_damage_turn = np.zeros((batch_n, MAX_COMMANDERS), dtype=np.float32)
            for slot in range(MAX_COMMANDERS):
                if not cmd_names[slot] or cmd_mana_values[slot] < 0:
                    continue
                commander_can_attack = (commander_cast_turn[:, slot] > 0) & (
                    (commander_cast_turn[:, slot] < turn)
                    | ((commander_cast_turn[:, slot] == turn) & cmd_has_haste[slot])
                )
                commander_damage_turn[:, slot] = np.where(
                    commander_can_attack,
                    np.maximum(0.0, cmd_powers[slot] + commander_buff_total + combat_buff_total)
                    * extra_combat
                    * min(1.0, 0.55 + float(cmd_evasion[slot])),
                    0.0,
                )
            poison_turn = (
                ((attackers & deck.infect[np.newaxis, :]) * deck.power[np.newaxis, :]).sum(axis=1)
                + ((attackers * deck.toxic[np.newaxis, :]).sum(axis=1))
            ) * extra_combat * evasion_factor
            poison_turn += np.where((poison_total > 0) & (current_turn_cast & deck.proliferate[np.newaxis, :]).any(axis=1), 1.0, 0.0)
            burn_turn = (
                (current_turn_cast * deck.burn_value[np.newaxis, :]).sum(axis=1)
                + ((on_battlefield & ~current_turn_cast) * deck.repeatable_burn[np.newaxis, :]).sum(axis=1)
            )
            mill_turn = (
                (current_turn_cast * deck.mill_value[np.newaxis, :]).sum(axis=1)
                + ((on_battlefield & ~current_turn_cast) * deck.repeatable_mill[np.newaxis, :]).sum(axis=1)
            )
            progress = mana_total * 0.5 + draw_count * 0.8 + engine_count * 1.0 + np.where(commander_cast_turn.any(axis=1), 1.2, 0.0)
            progress += np.minimum(6.0, combat_damage_turn / 10.0)
            progress += np.minimum(5.0, commander_damage_turn.sum(axis=1) / 6.0)
            progress += np.minimum(4.0, burn_total / 10.0)
            plan_progress[:, t] = progress
            combat_damage_total += combat_damage_turn.astype(np.float32)
            commander_damage_total[:, :, 0] += commander_damage_turn.astype(np.float32)
            poison_total += poison_turn.astype(np.float32)
            burn_total += burn_turn.astype(np.float32)
            mill_total += mill_turn.astype(np.float32)

            is_win_phase = cast_payoff_turn
            is_engine_phase = (~is_win_phase) & ((engine_count >= 1) | (draw_engine_turn > 0))
            is_setup_phase = ~is_win_phase & ~is_engine_phase
            phase_win[:, t] = is_win_phase
            phase_engine[:, t] = is_engine_phase
            phase_setup[:, t] = is_setup_phase

            # Win detection in selected order.
            payoff_count = (on_battlefield & (deck.is_payoff | deck.is_wincon)[np.newaxis, :]).sum(axis=1)
            combo_count = (on_battlefield & deck.is_combo[np.newaxis, :]).sum(axis=1)
            counter_or_stax = (on_battlefield & (deck.is_counter | deck.is_stax)[np.newaxis, :]).any(axis=1)
            artifact_count = (on_battlefield & deck.is_artifact[np.newaxis, :]).sum(axis=1)
            creature_count = (on_battlefield & deck.is_creature[np.newaxis, :]).sum(axis=1).astype(np.float32) + token_bodies_total
            library_size = deck_size - library_pos
            hand_size = in_hand.sum(axis=1)
            unresolved = win_turn == 0
            for w in selected_wincons:
                if not unresolved.any():
                    break
                if w == "Combo":
                    if combo_source_live:
                        cond, reasons = _detect_live_combo_hits(on_battlefield, commander_cast_turn, combo_requirements, cmd_names)
                    else:
                        cond = (
                            (cast_combo_turn & cast_wincon_turn & (payoff_count >= 2) & (turn >= 5))
                            | (
                                (cast_combo_turn | cast_tutor_turn)
                                & (combo_count >= 2)
                                & (payoff_count >= 3)
                                & (engine_count >= 1)
                                & (mana_total >= 7)
                                & (turn >= 6)
                            )
                        )
                        reasons = np.where(
                            cast_combo_turn & cast_wincon_turn & (payoff_count >= 2) & (turn >= 5),
                            "Combo piece plus explicit win piece resolved with enough support already in play.",
                            "Multiple combo and payoff pieces with an active engine crossed the deterministic combo threshold.",
                        )
                elif w == "Combat":
                    cond = (combat_damage_total >= 90) | ((combat_damage_turn >= 36) & (turn >= 5))
                    reasons = np.array([f"Projected combat pressure reached {float(v):.1f} effective damage." for v in combat_damage_total], dtype=object)
                elif w == "Commander Damage":
                    commander_damage_peak = commander_damage_total.max(axis=(1, 2))
                    cond = commander_damage_peak >= 21
                    reasons = np.array([f"Projected commander damage reached {float(v):.1f}." for v in commander_damage_peak], dtype=object)
                elif w == "Poison":
                    cond = poison_total >= 10
                    reasons = np.array([f"Projected poison counters reached {float(v):.1f}." for v in poison_total], dtype=object)
                elif w == "Drain/Burn":
                    cond = burn_total >= 40
                    reasons = np.array([f"Noncombat damage/life-loss lines reached {float(v):.1f} damage." for v in burn_total], dtype=object)
                elif w == "Mill":
                    cond = mill_total >= 90
                    reasons = np.array([f"Mill lines reached {float(v):.1f} cards." for v in mill_total], dtype=object)
                elif w == "Control Lock":
                    cond = (turn >= 6) & (engine_count >= 2) & counter_or_stax
                    reasons = np.full(batch_n, "Lock pieces and engines combined into a board state opponents are unlikely to beat.", dtype=object)
                elif w == "Alt Win":
                    upkeep_alt = (
                        ((on_battlefield & ~current_turn_cast) & (deck.alt_win_code[np.newaxis, :] == 2)).any(axis=1)
                        | (((on_battlefield & ~current_turn_cast) & (deck.alt_win_code[np.newaxis, :] == 3)).any(axis=1) & (artifact_count >= 20))
                        | (((on_battlefield & ~current_turn_cast) & (deck.alt_win_code[np.newaxis, :] == 4)).any(axis=1) & (creature_count >= 20))
                        | (((on_battlefield & ~current_turn_cast) & (deck.alt_win_code[np.newaxis, :] == 5)).any(axis=1) & (graveyard_count >= 20))
                        | (((on_battlefield & ~current_turn_cast) & (deck.alt_win_code[np.newaxis, :] == 6)).any(axis=1) & (library_size <= 2))
                        | (((on_battlefield & ~current_turn_cast) & (deck.alt_win_code[np.newaxis, :] == 7)).any(axis=1) & (library_size <= 0))
                        | (((on_battlefield & ~current_turn_cast) & (deck.alt_win_code[np.newaxis, :] == 8)).any(axis=1) & (hand_size <= 0))
                    )
                    cond = upkeep_alt
                    reasons = np.full(batch_n, "A supported alternate-win condition is live.", dtype=object)
                else:
                    cond = np.zeros(batch_n, dtype=bool)
                    reasons = np.array([""] * batch_n, dtype=object)

                hit = unresolved & cond
                if hit.any():
                    win_turn[hit] = turn
                    achieved_wincon[hit] = w
                    achieved_reason[hit] = reasons[hit]
                    unresolved = win_turn == 0

            can_ramp = (ramp_online_turn == 0) & (mana_total >= 4)
            ramp_online_turn[can_ramp] = turn

        max_mana = mana_by_turn.max(axis=1)
        for i in range(batch_n):
            dead_idx = np.where(in_hand[i] & (deck.mana_value > max_mana[i]))[0]
            dead_names = [deck.names[j] for j in dead_idx.tolist()]
            dead_counter.update(dead_names)
            global_run = run_offset + i
            if global_run < 20:
                commander_turns = [int(turn_value) for turn_value in commander_cast_turn[i].tolist() if int(turn_value) > 0]
                decision_samples.append(
                    {
                        "run": int(global_run),
                        "commander_cast_turn": min(commander_turns) if commander_turns else None,
                        "ramp_online_turn": int(ramp_online_turn[i]) if ramp_online_turn[i] > 0 else None,
                        "draw_engine_turn": int(draw_engine_turn[i]) if draw_engine_turn[i] > 0 else None,
                        "dead_cards": dead_names[:5],
                    }
                )

        all_mana.append(mana_by_turn)
        all_lands.append(lands_by_turn)
        all_colors.append(colors_by_turn)
        all_actions.append(actions_by_turn)
        all_plan_progress.append(plan_progress)
        all_phase_setup.append(phase_setup)
        all_phase_engine.append(phase_engine)
        all_phase_win.append(phase_win)
        all_mulligans.append(mulligans)
        all_commander_turn.append(commander_cast_turn)
        all_draw_engine_turn.append(draw_engine_turn)
        all_cards_seen.append(cards_seen)
        all_seen_masks.append(seen_mask)
        all_cast_masks.append(cast_mask)
        all_opening_masks.append(opening_mask)
        all_draw_idx.append(draw_idx)
        all_land_idx.append(land_idx)
        all_cast_by_turn.append(cast_by_turn)
        all_mulligan_logs.extend(mulligan_logs)
        all_win_turn.append(win_turn)
        all_achieved.append(achieved_wincon)
        all_win_reason.append(achieved_reason)
        run_offset += batch_n

    mana = np.vstack(all_mana)
    lands = np.vstack(all_lands)
    colors = np.vstack(all_colors)
    actions = np.vstack(all_actions)
    progress = np.vstack(all_plan_progress)
    phase_setup = np.vstack(all_phase_setup)
    phase_engine = np.vstack(all_phase_engine)
    phase_win = np.vstack(all_phase_win)
    mulligans = np.concatenate(all_mulligans)
    cmd_turn = np.concatenate(all_commander_turn, axis=0)
    draw_engine_turn = np.concatenate(all_draw_engine_turn)
    cards_seen = np.concatenate(all_cards_seen)
    seen_masks = np.vstack(all_seen_masks)
    cast_masks = np.vstack(all_cast_masks)
    opening_masks = np.vstack(all_opening_masks)
    draw_idx_all = np.vstack(all_draw_idx)
    land_idx_all = np.vstack(all_land_idx)
    cast_by_turn_all = np.concatenate(all_cast_by_turn, axis=0)
    win_turn = np.concatenate(all_win_turn)
    achieved = np.concatenate(all_achieved)
    achieved_reason = np.concatenate(all_win_reason)

    p_mana4_t3 = float((mana[:, 2] >= 4).mean()) if turn_limit >= 3 else 0.0
    p_mana5_t4 = float((mana[:, 3] >= 5).mean()) if turn_limit >= 4 else 0.0
    per_run_cmd_turn = []
    for row in cmd_turn.tolist():
        turns = [int(x) for x in row if int(x) > 0]
        per_run_cmd_turn.append(min(turns) if turns else 0)
    cmd_turns = [turn for turn in per_run_cmd_turn if turn > 0]

    failure_modes = {
        "mana_screw": float((mana[:, min(2, turn_limit - 1)] < 3).mean()) if turn_limit >= 3 else 0.0,
        "flood": float(((mana.max(axis=1) > 10) & (cards_seen < (turn_limit + 6))).mean()),
        "no_action": float((~(progress[:, : min(3, turn_limit)] > 3).any(axis=1)).mean()),
    }

    avg_success = float(progress[:, -1].mean()) if progress.size else 0.0
    card_impacts = {}
    name_to_idx = defaultdict(list)
    for i, n in enumerate(deck.names):
        name_to_idx[n].append(i)
    for name, idxs in name_to_idx.items():
        idx_arr = np.array(idxs, dtype=np.int32)
        seen_name = seen_masks[:, idx_arr].any(axis=1)
        cast_name = cast_masks[:, idx_arr].any(axis=1)
        seen_avg = float(progress[seen_name, -1].mean()) if seen_name.any() else avg_success
        cast_avg = float(progress[cast_name, -1].mean()) if cast_name.any() else avg_success
        centrality = min(1.0, float(cast_name.sum()) / max(1.0, runs * 0.5))
        card_impacts[name] = {
            "seen_lift": max(0.0, (seen_avg - avg_success) / (avg_success + 1e-6)),
            "cast_lift": max(0.0, (cast_avg - avg_success) / (avg_success + 1e-6)),
            "centrality": centrality,
            "redundancy": 0.5,
        }

    win_turns = [int(x) for x in win_turn if x > 0]
    wincon_counter = Counter([str(x) for x in achieved if x])
    turn_win_counts = Counter(win_turns)
    cumulative = 0

    mana_percentiles = []
    land_hit_cdf = []
    color_access = []
    phase_timeline = []
    no_action_funnel = []
    action_rate = []
    win_turn_cdf = []
    mana_hit_table = []

    for t in range(turn_limit):
        tnum = int(turn_idx[t])
        mana_t = mana[:, t].astype(float)
        land_t = lands[:, t]
        color_t = colors[:, t]
        action_t = actions[:, t]
        mana_percentiles.append(
            {
                "turn": tnum,
                "p50": _percentile(mana_t, 0.5),
                "p75": _percentile(mana_t, 0.75),
                "p90": _percentile(mana_t, 0.9),
            }
        )
        land_hit_cdf.append({"turn": tnum, "p_hit_on_curve": float((land_t >= tnum).mean())})
        color_access.append(
            {
                "turn": tnum,
                "avg_colors": float(color_t.mean()),
                "p_full_identity": float((color_t >= colors_req).mean()) if colors_req > 0 else 1.0,
                "p_three_plus": float((color_t >= 3).mean()) if colors_req >= 3 else None,
            }
        )
        no_action_funnel.append({"turn": tnum, "p_no_action": float((action_t == 0).mean())})
        action_rate.append({"turn": tnum, "p_action": float((action_t > 0).mean())})
        phase_timeline.append(
            {
                "turn": tnum,
                "setup": float(phase_setup[:, t].mean()),
                "engine": float(phase_engine[:, t].mean()),
                "win_attempt": float(phase_win[:, t].mean()),
            }
        )
        threshold_max = int(min(16, max(turn_limit + 4, int(deck.mana_value.max()) if deck.mana_value.size else 0)))
        hit_row = {"turn": tnum}
        for mv in range(1, threshold_max + 1):
            hit_row[f"p_ge_{mv}"] = float((mana[:, t] >= mv).mean())
        mana_hit_table.append(hit_row)
        cumulative += turn_win_counts.get(tnum, 0)
        win_turn_cdf.append({"turn": tnum, "cdf": cumulative / runs})

    mana_curve_points = []
    for mv in range(0, threshold_max + 1):
        if mv <= 0:
            mana_curve_points.append({"mana_value": mv, "on_curve_turn": 1, "p_on_curve": 1.0})
            continue
        on_turn = min(turn_limit, mv)
        p_on_curve = float((mana[:, on_turn - 1] >= mv).mean())
        mana_curve_points.append({"mana_value": mv, "on_curve_turn": on_turn, "p_on_curve": p_on_curve})

    commander_cast_dist = Counter(str(turn) if turn > 0 else "never" for turn in per_run_cmd_turn)
    engine_online_dist = Counter([str(int(x)) if x > 0 else "never" for x in draw_engine_turn])
    mulligan_funnel = Counter([str(int(x)) for x in mulligans])
    dead_cards_top = [{"card": k, "count": v, "rate": v / runs} for k, v in dead_counter.most_common(20)]

    fastest_wins = []
    winner_idx = [i for i, wt in enumerate(win_turn.tolist()) if int(wt) > 0]
    winner_idx.sort(key=lambda i: (int(win_turn[i]), i))
    for rank, idx in enumerate(winner_idx[:3], start=1):
        wt = int(win_turn[idx])
        mull_steps = []
        for step in (all_mulligan_logs[idx] if idx < len(all_mulligan_logs) else []):
            row = {
                "attempt": int(step.get("attempt", 0)),
                "hand": [deck.names[j] for j in step.get("hand_idx", []) if 0 <= int(j) < len(deck.names)],
                "kept": bool(step.get("kept", False)),
            }
            if "bottom_count" in step:
                row["bottom_count"] = int(step.get("bottom_count", 0))
            if "kept_hand_idx" in step:
                row["kept_hand"] = [deck.names[j] for j in step.get("kept_hand_idx", []) if 0 <= int(j) < len(deck.names)]
            mull_steps.append(row)

        kept_indices = []
        if idx < len(all_mulligan_logs) and all_mulligan_logs[idx]:
            kept_indices = all_mulligan_logs[idx][-1].get("kept_hand_idx", [])
        opening_names = [deck.names[j] for j in kept_indices if 0 <= int(j) < len(deck.names)]
        turn_rows = []
        for t in range(min(turn_limit, wt if wt > 0 else turn_limit)):
            draw_name = None
            land_name = None
            if int(draw_idx_all[idx, t]) >= 0:
                draw_name = deck.names[int(draw_idx_all[idx, t])]
            if int(land_idx_all[idx, t]) >= 0:
                land_name = deck.names[int(land_idx_all[idx, t])]
            cast_names = [deck.names[j] for j in np.where(cast_by_turn_all[idx, t])[0].tolist()]
            if bool(phase_win[idx, t]):
                phase = "win_attempt"
            elif bool(phase_engine[idx, t]):
                phase = "engine"
            else:
                phase = "setup"
            turn_rows.append(
                {
                    "turn": int(t + 1),
                    "draw": draw_name,
                    "land": land_name,
                    "casts": cast_names,
                    "actions": int(actions[idx, t]),
                    "mana_total": int(mana[idx, t]),
                    "phase": phase,
                    "wincon_hit": str(achieved[idx]) if wt == (t + 1) and achieved[idx] else None,
                    "win_reason": str(achieved_reason[idx]) if wt == (t + 1) and achieved_reason[idx] else None,
                }
            )

        fastest_wins.append(
            {
                "rank": rank,
                "run_index": int(idx),
                "seed_token": f"{seed}:{idx}",
                "win_turn": wt,
                "wincon": str(achieved[idx]) if achieved[idx] else None,
                "win_reason": str(achieved_reason[idx]) if achieved_reason[idx] else None,
                "mulligans_taken": int(mulligans[idx]),
                "mulligan_steps": mull_steps,
                "opening_hand": opening_names,
                "turns": turn_rows,
            }
        )

    per_turn_progress = {
        int(t + 1): {
            "median": float(median(progress[:, t].tolist())),
            "p90": _percentile(progress[:, t], 0.9),
        }
        for t in range(turn_limit)
    }

    reference_trace = {}
    if runs > 0 and len(all_mulligan_logs) > 0:
        kept_indices = all_mulligan_logs[0][-1].get("kept_hand_idx", []) if all_mulligan_logs[0] else []
        opening_names = [deck.names[j] for j in kept_indices if 0 <= int(j) < len(deck.names)]
        turn_rows = []
        for t in range(turn_limit):
            draw_name = deck.names[int(draw_idx_all[0, t])] if int(draw_idx_all[0, t]) >= 0 else None
            land_name = deck.names[int(land_idx_all[0, t])] if int(land_idx_all[0, t]) >= 0 else None
            cast_names = [deck.names[j] for j in np.where(cast_by_turn_all[0, t])[0].tolist()]
            if bool(phase_win[0, t]):
                phase = "win_attempt"
            elif bool(phase_engine[0, t]):
                phase = "engine"
            else:
                phase = "setup"
            turn_rows.append(
                {
                    "turn": int(t + 1),
                    "draw": draw_name,
                    "land": land_name,
                    "casts": cast_names,
                    "actions": int(actions[0, t]),
                    "mana_total": int(mana[0, t]),
                    "phase": phase,
                }
            )
        reference_trace = {
            "opening_hand": opening_names,
            "mulligans_taken": int(mulligans[0]) if mulligans.size else 0,
            "mulligan_steps": [
                {
                    "attempt": int(step.get("attempt", 0)),
                    "hand": [deck.names[j] for j in step.get("hand_idx", []) if 0 <= int(j) < len(deck.names)],
                    "kept": bool(step.get("kept", False)),
                    **({"bottom_count": int(step.get("bottom_count", 0))} if "bottom_count" in step else {}),
                    **(
                        {
                            "kept_hand": [
                                deck.names[j]
                                for j in step.get("kept_hand_idx", [])
                                if 0 <= int(j) < len(deck.names)
                            ]
                        }
                        if "kept_hand_idx" in step
                        else {}
                    ),
                }
                for step in (all_mulligan_logs[0] or [])
            ],
            "commander_slots": [name for name in cmd_names if name],
            "commander_tax_slots": [0] * MAX_COMMANDERS,
            "commander_casts_by_slot": [1 if int(value) > 0 else 0 for value in cmd_turn[0].tolist()] if cmd_turn.size else [0] * MAX_COMMANDERS,
            "commander_damage_by_slot": [[0.0] * 3 for _ in range(MAX_COMMANDERS)],
            "turns": turn_rows,
        }

    coverage_summary = summarize_compiled_execs(compiled_exec)

    summary = {
        "runs": runs,
        "seed": int(resolved.seed),
        "policy": policy,
        "turn_limit": turn_limit,
        "selected_wincons": selected_wincons,
        "backend_used": "vectorized",
        "resolved_policy": asdict(resolved.policy),
        "opponent_profile": asdict(resolved.opponent),
        "commander_slots": [name for name in resolved.commander_slots if name],
        "ir_version": 2,
        "coverage_summary": coverage_summary,
        "support_confidence": coverage_summary.get("support_confidence", 0.0),
        "batch_size": int(batch_size),
        "vectorization_stats": {
            "deck_size": int(deck_size),
            "batches": int((runs + batch_size - 1) // batch_size),
            "runs": int(runs),
        },
        "milestones": {
            "p_mana4_t3": p_mana4_t3,
            "p_mana5_t4": p_mana5_t4,
            "median_commander_cast_turn": median(cmd_turns) if cmd_turns else None,
        },
        "win_metrics": {
            "p_win_by_turn_limit": (len(win_turns) / runs) if runs else 0.0,
            "median_win_turn": median(win_turns) if win_turns else None,
            "most_common_wincon": wincon_counter.most_common(1)[0][0] if wincon_counter else None,
            "wincon_distribution": {k: (v / runs) for k, v in wincon_counter.items()},
        },
        "uncertainty": {
            "p_mana4_t3_ci95": _binom_ci95(p_mana4_t3, runs),
            "p_mana5_t4_ci95": _binom_ci95(p_mana5_t4, runs),
            "p_win_by_turn_limit_ci95": _binom_ci95((len(win_turns) / runs) if runs else 0.0, runs),
        },
        "plan_progress": per_turn_progress,
        "failure_modes": failure_modes,
        "card_impacts": card_impacts,
        "fastest_wins": fastest_wins,
        "decision_samples": decision_samples,
        "reference_trace": reference_trace,
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

    return {"summary": summary}
