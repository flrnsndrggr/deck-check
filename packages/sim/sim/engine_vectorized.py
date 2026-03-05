from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from statistics import median
from typing import Dict, List

import numpy as np


@dataclass
class _DeckArrays:
    names: List[str]
    mana_value: np.ndarray
    is_land: np.ndarray
    is_ramp: np.ndarray
    is_fast_mana: np.ndarray
    is_early_action: np.ndarray
    is_fixing: np.ndarray
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


def _policy_alias(policy: str, bracket: int) -> str:
    if policy == "auto":
        if bracket >= 5:
            return "cedh"
        if bracket <= 2:
            return "casual"
        return "optimized"
    return policy


def _normalize_wincons(primary_wincons: List[str] | None) -> List[str]:
    if not primary_wincons:
        return ["Combat", "Combo", "Commander Damage", "Control Lock", "Alt Win"]
    return primary_wincons


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


def _expand_deck(cards: List[dict]) -> _DeckArrays:
    names: List[str] = []
    mana_values: List[int] = []
    flags = {
        "is_land": [],
        "is_ramp": [],
        "is_fast_mana": [],
        "is_early_action": [],
        "is_fixing": [],
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
    }

    for c in cards:
        qty = int(c.get("qty", 1))
        name = str(c.get("name", "")).strip()
        tags = set(c.get("tags", []) or [])
        mv = int(c.get("mana_value", 2))
        is_land = "#Land" in tags
        is_ramp = "#Ramp" in tags
        is_fixing = "#Fixing" in tags and (is_land or is_ramp)
        is_fast = "#FastMana" in tags or (is_ramp and mv <= 2)
        is_early_action = mv <= 2 and bool(tags & {"#Ramp", "#Draw", "#Setup"})

        for _ in range(max(1, qty)):
            names.append(name)
            mana_values.append(mv)
            flags["is_land"].append(is_land)
            flags["is_ramp"].append(is_ramp)
            flags["is_fast_mana"].append(is_fast)
            flags["is_early_action"].append(is_early_action)
            flags["is_fixing"].append(is_fixing)
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

    return _DeckArrays(
        names=names,
        mana_value=np.array(mana_values, dtype=np.int16),
        is_land=np.array(flags["is_land"], dtype=bool),
        is_ramp=np.array(flags["is_ramp"], dtype=bool),
        is_fast_mana=np.array(flags["is_fast_mana"], dtype=bool),
        is_early_action=np.array(flags["is_early_action"], dtype=bool),
        is_fixing=np.array(flags["is_fixing"], dtype=bool),
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
    rng: np.random.Generator,
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
        cand_orders = np.argsort(rng.random((unresolved.size, deck_size)), axis=1).astype(np.int16)
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
            on_battlefield[r, c] = True

    return chosen_any


def run_simulation_batch_vectorized(
    cards: List[dict],
    commander: str | None,
    runs: int,
    turn_limit: int,
    policy: str,
    multiplayer: bool,
    threat_model: bool,
    seed: int,
    bracket: int = 3,
    primary_wincons: List[str] | None = None,
    color_identity_size: int = 3,
    batch_size: int = 512,
) -> Dict:
    if runs <= 0:
        return {"summary": {"runs": 0}}

    policy = _policy_alias(policy, bracket)
    selected_wincons = _normalize_wincons(primary_wincons)
    colors_req = max(0, int(color_identity_size))

    deck = _expand_deck(cards)
    deck_size = deck.mana_value.size
    if deck_size == 0:
        return {"summary": {"runs": runs, "seed": seed, "policy": policy, "turn_limit": turn_limit}}

    rng = np.random.default_rng(int(seed))
    cmd_mana_value = None
    if commander:
        for i, n in enumerate(deck.names):
            if n == commander:
                cmd_mana_value = int(deck.mana_value[i])
                break

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

    decision_samples = []
    dead_counter = Counter()
    run_offset = 0

    turn_idx = np.arange(1, turn_limit + 1, dtype=np.int16)

    while run_offset < runs:
        batch_n = min(batch_size, runs - run_offset)
        orders, hand_sizes, mulligans, mulligan_logs = _roll_openers(rng, deck, batch_n, policy, multiplayer, colors_req)
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

        commander_cast_turn = np.zeros(batch_n, dtype=np.int16)
        draw_engine_turn = np.zeros(batch_n, dtype=np.int16)
        ramp_online_turn = np.zeros(batch_n, dtype=np.int16)
        win_turn = np.zeros(batch_n, dtype=np.int16)
        achieved_wincon = np.array([""] * batch_n, dtype=object)

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
            )
            if ramp_casted.any():
                cast_tutor_turn |= False

            # 3) draw stage
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
            )
            new_draw = (draw_engine_turn == 0) & draw_casted
            draw_engine_turn[new_draw] = turn

            # 4) commander cast stage
            if commander and cmd_mana_value is not None:
                should_cast = ((policy in {"commander-centric", "optimized", "casual"}) and turn >= 3) or (
                    policy == "hold commander" and turn >= 5
                )
                if should_cast:
                    cmd_cost = int(cmd_mana_value)
                    can_cmd = (commander_cast_turn == 0) & (available_mana >= cmd_cost)
                    if can_cmd.any():
                        available_mana[can_cmd] -= cmd_cost
                        commander_cast_turn[can_cmd] = turn

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
            )
            new_cast = cast_mask & ~pre_cast
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
                    # Keep usage deterministic; cast only in rows with event.
                    reverted = ~threat_event
                    if reverted.any():
                        delta = cast_mask & ~pre_cast_int
                        cast_mask[reverted] = pre_cast_int[reverted]
                        in_hand[reverted] |= delta[reverted]
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
            progress = mana_total * 0.5 + draw_count * 0.8 + engine_count * 1.0 + np.where(commander_cast_turn > 0, 1.2, 0.0)
            plan_progress[:, t] = progress

            is_win_phase = cast_payoff_turn
            is_engine_phase = (~is_win_phase) & ((engine_count >= 1) | (draw_engine_turn > 0))
            is_setup_phase = ~is_win_phase & ~is_engine_phase
            phase_win[:, t] = is_win_phase
            phase_engine[:, t] = is_engine_phase
            phase_setup[:, t] = is_setup_phase

            # Win detection in selected order.
            payoff_count = (on_battlefield & (deck.is_payoff | deck.is_wincon)[np.newaxis, :]).sum(axis=1)
            counter_or_stax = (on_battlefield & (deck.is_counter | deck.is_stax)[np.newaxis, :]).any(axis=1)
            unresolved = win_turn == 0
            for w in selected_wincons:
                if not unresolved.any():
                    break
                if w == "Combo":
                    cond = cast_combo_turn | (cast_tutor_turn & (payoff_count >= 2) & (turn >= 4))
                elif w == "Combat":
                    cond = (turn >= 5) & (payoff_count >= 2)
                elif w == "Commander Damage":
                    cond = (commander_cast_turn > 0) & (turn >= (commander_cast_turn + 2)) & (mana_total >= 6)
                elif w == "Control Lock":
                    cond = (turn >= 6) & (engine_count >= 2) & counter_or_stax
                elif w == "Alt Win":
                    cond = cast_wincon_turn & (turn >= 5)
                else:
                    cond = np.zeros(batch_n, dtype=bool)

                hit = unresolved & cond
                if hit.any():
                    win_turn[hit] = turn
                    achieved_wincon[hit] = w
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
                decision_samples.append(
                    {
                        "run": int(global_run),
                        "commander_cast_turn": int(commander_cast_turn[i]) if commander_cast_turn[i] > 0 else None,
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
    cmd_turn = np.concatenate(all_commander_turn)
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

    p_mana4_t3 = float((mana[:, 2] >= 4).mean()) if turn_limit >= 3 else 0.0
    p_mana5_t4 = float((mana[:, 3] >= 5).mean()) if turn_limit >= 4 else 0.0
    cmd_turns = [int(x) for x in cmd_turn if x > 0]

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

    commander_cast_dist = Counter([str(int(x)) if x > 0 else "never" for x in cmd_turn])
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

        opening_names = [deck.names[j] for j in np.where(opening_masks[idx])[0].tolist()]
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
                }
            )

        fastest_wins.append(
            {
                "rank": rank,
                "run_index": int(idx),
                "seed_token": f"{seed}:{idx}",
                "win_turn": wt,
                "wincon": str(achieved[idx]) if achieved[idx] else None,
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

    summary = {
        "runs": runs,
        "seed": int(seed),
        "policy": policy,
        "turn_limit": turn_limit,
        "backend_used": "vectorized",
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
            "color_identity_size": color_identity_size,
        },
    }

    return {"summary": summary}
