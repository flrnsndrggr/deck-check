from __future__ import annotations

import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from statistics import median
from typing import Dict, List, Tuple


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
    trace: Dict | None = None


def _normalize_name(name: str | None) -> str:
    return (name or "").strip().lower()


def _build_sim_deck(cards: List[dict], commander: str | None) -> tuple[List[Card], Card | None]:
    commander_key = _normalize_name(commander)
    commander_card: Card | None = None
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
        is_commander = commander_key and _normalize_name(c.get("name")) == commander_key

        if is_commander and (section == "commander" or commander_card is None):
            commander_card = card
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

    return deck, commander_card


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
            keys.add(key)
            cards.append(str(name).strip())
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


def _live_combo_reason(
    combo_variants: List[Dict],
    battlefield: List[Card],
    commander: str | None,
    commander_live: bool,
) -> str | None:
    if not combo_variants:
        return None
    live_cards = {_normalize_name(card.name) for card in battlefield}
    if commander and commander_live:
        live_cards.add(_normalize_name(commander))
    for variant in combo_variants:
        if variant["keys"].issubset(live_cards):
            card_list = ", ".join(variant["cards"])
            return f"All required cards for the CommanderSpellbook combo are live: {card_list}."
    return None


def _combat_metrics(
    battlefield: List[Card],
    cast_this_turn: List[Card],
    commander_card: Card | None,
    commander_live: bool,
) -> Dict[str, float]:
    summoning_names = {c.name for c in cast_this_turn if not c.has_haste}
    attackers = [c for c in battlefield if c.is_creature and (c.has_haste or c.name not in summoning_names)]
    combat_buff = sum(c.combat_buff for c in battlefield)
    commander_buff = sum(c.commander_buff for c in battlefield)
    token_attack_power = sum(
        c.token_attack_power
        for c in battlefield
        if c.has_haste or c.name not in summoning_names
    )
    token_bodies = sum(
        c.token_bodies
        for c in battlefield
        if c.has_haste or c.name not in summoning_names
    )
    extra_combat = max([1.0] + [c.extra_combat_factor for c in battlefield])
    base_power = sum(max(0.0, c.power) for c in attackers)
    body_count = len(attackers) + token_bodies
    avg_evasion = (sum(c.evasion_score for c in attackers) / len(attackers)) if attackers else 0.0
    evasion_factor = min(1.0, 0.55 + avg_evasion)
    combat_damage = max(0.0, (base_power + token_attack_power + combat_buff * body_count) * extra_combat * evasion_factor)

    commander_damage = 0.0
    poison_damage = 0.0
    if commander_card and commander_live:
        commander_evasion = min(1.0, 0.55 + commander_card.evasion_score)
        commander_attack = max(0.0, commander_card.power + commander_buff + combat_buff)
        commander_damage = commander_attack * extra_combat * commander_evasion

    for attacker in attackers:
        if attacker.infect:
            poison_damage += max(0.0, attacker.power) * extra_combat * min(1.0, 0.55 + attacker.evasion_score)
        if attacker.toxic > 0:
            poison_damage += attacker.toxic * extra_combat * min(1.0, 0.55 + attacker.evasion_score)
    if poison_damage > 0 and any(c.proliferate for c in cast_this_turn):
        poison_damage += 1.0

    return {
        "combat_damage": combat_damage,
        "commander_damage": commander_damage,
        "poison_damage": poison_damage,
    }


def _alt_win_ready(
    battlefield: List[Card],
    turn: int,
    cast_this_turn: List[Card],
    library_size: int,
    graveyard_count: int,
) -> str | None:
    artifact_count = sum(1 for c in battlefield if "artifact" in c.type_line.lower())
    creature_count = sum(1 for c in battlefield if c.is_creature) + int(sum(c.token_bodies for c in battlefield))
    current_cast = {c.name for c in cast_this_turn}
    for card in battlefield:
        if not card.alt_win_kind:
            continue
        text = card.oracle_text.lower()
        if card.alt_win_kind == "generic" and card.name in current_cast:
            return f"{card.name} has explicit 'you win the game' text and resolved this turn."
        if "at the beginning of your upkeep" in text and card.name in current_cast:
            continue
        if card.alt_win_kind == "life40" and turn >= 2:
            return f"{card.name} checks 40-or-more life, which goldfish preserves by default."
        if card.alt_win_kind == "artifacts20" and artifact_count >= 20:
            return f"{card.name} saw 20 or more artifacts on board."
        if card.alt_win_kind == "creatures20" and creature_count >= 20:
            return f"{card.name} saw 20 or more creatures on board."
        if card.alt_win_kind == "graveyard20" and graveyard_count >= 20:
            return f"{card.name} saw 20 or more cards in graveyard."
        if card.alt_win_kind == "library2" and library_size <= 2:
            return f"{card.name} reduced the library to two or fewer cards."
        if card.alt_win_kind == "library0" and library_size <= 0:
            return f"{card.name} emptied the library."
    return None


def _is_land(card: Card) -> bool:
    return "#Land" in card.tags


def _is_fast_mana(card: Card) -> bool:
    return "#FastMana" in card.tags or "#Ramp" in card.tags and card.mana_value <= 2


def _is_early_action(card: Card) -> bool:
    return card.mana_value <= 2 and any(t in card.tags for t in ["#Ramp", "#Draw", "#Setup"])


def _keep_hand(hand: List[Card], policy: str, colors_required: int, mulligans_taken: int, multiplayer: bool) -> bool:
    lands = sum(1 for c in hand if _is_land(c))
    early = any(_is_early_action(c) for c in hand)
    fast_mana = any(_is_fast_mana(c) for c in hand)

    if policy in {"cedh", "cEDH-like speed"}:
        if lands == 1 and fast_mana and early:
            return True
        return 1 <= lands <= 4 and (early or fast_mana)

    keep = 2 <= lands <= 5 and early
    if colors_required >= 3:
        keep = keep and any("#Fixing" in c.tags for c in hand if _is_land(c) or "#Ramp" in c.tags)
    return keep


def london_mulligan(
    deck: List[Card],
    policy: str,
    multiplayer: bool,
    rng: random.Random,
    colors_required: int,
    capture_log: bool = False,
) -> tuple[list[Card], int] | tuple[list[Card], int, List[Dict]]:
    mulligans = 0
    steps: List[Dict] = []
    while True:
        rng.shuffle(deck)
        hand7 = deck[:7]
        keep = _keep_hand(hand7, policy, colors_required, mulligans, multiplayer)
        if capture_log:
            steps.append(
                {
                    "attempt": mulligans,
                    "hand": [c.name for c in hand7],
                    "kept": keep,
                }
            )
        if keep:
            bottoms = mulligans
            if multiplayer and mulligans == 1:
                bottoms = 0
            hand = hand7[: max(0, 7 - bottoms)]
            if capture_log and steps:
                steps[-1]["bottom_count"] = bottoms
                steps[-1]["kept_hand"] = [c.name for c in hand]
            if capture_log:
                return hand, mulligans, steps
            return hand, mulligans
        mulligans += 1
        if mulligans >= 3:
            bottoms = mulligans
            if multiplayer and mulligans == 1:
                bottoms = 0
            hand = hand7[: max(0, 7 - bottoms)]
            if capture_log and steps:
                steps[-1]["bottom_count"] = bottoms
                steps[-1]["kept_hand"] = [c.name for c in hand]
            if capture_log:
                return hand, mulligans, steps
            return hand, mulligans


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
        return ["Combo", "Alt Win", "Poison", "Commander Damage", "Drain/Burn", "Mill", "Control Lock", "Combat"]
    return primary_wincons


def _detect_wincon_for_turn(
    selected_wincons: List[str],
    cast_this_turn: List[Card],
    battlefield: List[Card],
    turn: int,
    commander_cast_turn: int | None,
    mana_total: int,
    commander: str | None = None,
    commander_live: bool = False,
    commander_card: Card | None = None,
    combo_variants: List[Dict] | None = None,
    combo_source_live: bool = False,
    library_size: int = 0,
    graveyard_count: int = 0,
    combat_damage_total: float = 0.0,
    commander_damage_total: float = 0.0,
    poison_total: float = 0.0,
    burn_total: float = 0.0,
    mill_total: float = 0.0,
) -> Tuple[str | None, str | None]:
    cast_tags = {t for c in cast_this_turn for t in c.tags}
    battlefield_tags = {t for c in battlefield for t in c.tags}
    engine_count = sum(1 for c in battlefield if "#Engine" in c.tags)
    payoff_count = sum(1 for c in battlefield if "#Payoff" in c.tags or "#Wincon" in c.tags)
    combo_count = sum(1 for c in battlefield if "#Combo" in c.tags)
    combo_cast_count = sum(1 for c in cast_this_turn if "#Combo" in c.tags)
    tutor_cast = any("#Tutor" in c.tags for c in cast_this_turn)
    wincon_cast = any("#Wincon" in c.tags for c in cast_this_turn)

    for w in selected_wincons:
        if w == "Combo":
            if combo_source_live:
                live_reason = _live_combo_reason(combo_variants or [], battlefield, commander, commander_live)
                if live_reason:
                    return w, live_reason
            else:
                direct_combo_close = combo_cast_count >= 1 and wincon_cast and payoff_count >= 2 and turn >= 5
                assembled_combo_shell = (
                    (combo_cast_count >= 1 or tutor_cast)
                    and combo_count >= 2
                    and payoff_count >= 3
                    and engine_count >= 1
                    and mana_total >= 7
                    and turn >= 6
                )
                if direct_combo_close:
                    return w, "Combo piece plus explicit win piece resolved with enough support already in play."
                if assembled_combo_shell:
                    return w, "Multiple combo and payoff pieces with an active engine crossed the deterministic combo threshold."
        if w == "Combat":
            metrics = _combat_metrics(battlefield, cast_this_turn, commander_card, commander_live)
            if (combat_damage_total >= 90) or (metrics["combat_damage"] >= 36 and turn >= 5):
                return w, f"Projected combat pressure reached {combat_damage_total:.1f} effective damage."
        if w == "Commander Damage":
            if commander_cast_turn is not None and commander_damage_total >= 21:
                return w, f"Projected commander damage reached {commander_damage_total:.1f}."
        if w == "Poison":
            if poison_total >= 10:
                return w, f"Projected poison counters reached {poison_total:.1f}."
        if w == "Drain/Burn":
            if burn_total >= 40:
                return w, f"Noncombat damage/life-loss lines reached {burn_total:.1f} damage."
        if w == "Mill":
            if mill_total >= 90:
                return w, f"Mill lines reached {mill_total:.1f} cards."
        if w == "Control Lock":
            if turn >= 6 and engine_count >= 2 and ("#Counter" in battlefield_tags or "#Stax" in battlefield_tags):
                return w, "Lock pieces and engines combined into a board state opponents are unlikely to beat."
        if w == "Alt Win":
            alt_reason = _alt_win_ready(battlefield, turn, cast_this_turn, library_size, graveyard_count)
            if alt_reason:
                return w, alt_reason
    return None, None


def simulate_one(
    cards: List[Card],
    commander: str | None,
    commander_card: Card | None = None,
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
) -> RunMetrics:
    deck = cards.copy()
    if rng is None:
        rng = random.Random(42)
    policy = _policy_alias(policy, 3)
    colors_req = max(0, color_identity_size)
    if capture_trace:
        hand, mulligans_taken, mulligan_steps = london_mulligan(
            deck,
            policy,
            multiplayer,
            rng,
            colors_req,
            capture_log=True,
        )
    else:
        hand, mulligans_taken = london_mulligan(
            deck,
            policy,
            multiplayer,
            rng,
            colors_req,
            capture_log=False,
        )
        mulligan_steps = []

    lib = deck[7:]
    battlefield: List[Card] = []
    mana_sources = 0
    lands_played_this_turn = 0
    commander_tax = 0
    commander_cast_turn = None
    commander_live = False
    graveyard_count = 0
    combat_damage_total = 0.0
    commander_damage_total = 0.0
    poison_total = 0.0
    burn_total = 0.0
    mill_total = 0.0
    cards_seen = len(hand)
    seen_cards = {c.name for c in hand}
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
    selected_wincons = _normalize_wincons(primary_wincons)
    opening_hand = [c.name for c in hand]
    turn_trace: List[Dict] = []

    for turn in range(1, turn_limit + 1):
        cast_this_turn: List[Card] = []
        cast_names: List[str] = []
        draw_name = None
        land_name = None
        lands_played_this_turn = 0
        if lib:
            draw = lib.pop(0)
            hand.append(draw)
            cards_seen += 1
            seen_cards.add(draw.name)
            draw_name = draw.name

        # 1) land drop
        land_idx = next((i for i, c in enumerate(hand) if _is_land(c)), None)
        if land_idx is not None and lands_played_this_turn == 0:
            land_card = hand.pop(land_idx)
            battlefield.append(land_card)
            lands_played_this_turn += 1
            land_name = land_card.name

        available_mana = sum(1 for c in battlefield if _is_land(c) or "#Ramp" in c.tags)

        # 2) fast mana/ramp
        playable = [i for i, c in enumerate(hand) if c.mana_value <= available_mana]
        ordered = sorted(playable, key=lambda i: (0 if _is_fast_mana(hand[i]) else 1, hand[i].mana_value))
        for i in reversed(ordered):
            c = hand[i]
            if c.mana_value <= available_mana and ("#Ramp" in c.tags or "#FastMana" in c.tags):
                available_mana -= c.mana_value
                hand.pop(i)
                if c.is_permanent:
                    battlefield.append(c)
                else:
                    graveyard_count += 1
                cast_cards.add(c.name)
                cast_this_turn.append(c)
                cast_names.append(c.name)
                if ramp_online_turn is None and sum(1 for b in battlefield if "#Ramp" in b.tags or _is_land(b)) >= 4:
                    ramp_online_turn = turn

        # 3) draw engines
        for i in range(len(hand) - 1, -1, -1):
            c = hand[i]
            if c.mana_value <= available_mana and "#Draw" in c.tags:
                available_mana -= c.mana_value
                hand.pop(i)
                if c.is_permanent:
                    battlefield.append(c)
                else:
                    graveyard_count += 1
                cast_cards.add(c.name)
                cast_this_turn.append(c)
                cast_names.append(c.name)
                if draw_engine_turn is None:
                    draw_engine_turn = turn

        # 4) cast commander based on policy
        if commander and commander_cast_turn is None:
            cmd = commander_card
            if cmd:
                cmd_cost = cmd.mana_value + commander_tax
                should_cast = (policy in {"commander-centric", "optimized", "casual"} and turn >= 3) or (
                    policy == "hold commander" and turn >= 5
                )
                if should_cast and cmd_cost <= available_mana:
                    available_mana -= cmd_cost
                    commander_cast_turn = turn
                    commander_live = True
                    cast_names.append(commander)

        # 5/6) play plan pieces
        for i in range(len(hand) - 1, -1, -1):
            c = hand[i]
            if c.mana_value <= available_mana and any(t in c.tags for t in ["#Payoff", "#Engine", "#Setup", "#Tutor", "#Wincon", "#Combo"]):
                available_mana -= c.mana_value
                hand.pop(i)
                if c.is_permanent:
                    battlefield.append(c)
                else:
                    graveyard_count += 1
                cast_cards.add(c.name)
                cast_this_turn.append(c)
                cast_names.append(c.name)

        # 7) optional threat model for interaction usage
        if threat_model and turn >= 2 and rng.random() < 0.25:
            for i in range(len(hand) - 1, -1, -1):
                c = hand[i]
                if c.mana_value <= available_mana and any(t in c.tags for t in ["#Removal", "#Counter"]):
                    available_mana -= c.mana_value
                    cast_cards.add(c.name)
                    hand.pop(i)
                    if not c.is_permanent:
                        graveyard_count += 1
                    cast_this_turn.append(c)
                    cast_names.append(c.name)
                    break

        # Invariants
        assert available_mana >= 0, "negative mana produced"
        assert lands_played_this_turn <= 1, "illegal extra land drop"

        mana_total = sum(1 for c in battlefield if _is_land(c) or "#Ramp" in c.tags)
        lands_total = sum(1 for c in battlefield if _is_land(c))
        if color_identity_size <= 0:
            colors_total = 0
        elif color_identity_size == 1:
            colors_total = 1
        else:
            colors_total = min(color_identity_size, max(1, sum(1 for c in battlefield if "#Fixing" in c.tags) + 1))
        mana_by_turn.append(mana_total)
        lands_by_turn.append(lands_total)
        colors_by_turn.append(colors_total)
        actions_by_turn.append(len(cast_this_turn))

        progress = 0.0
        progress += mana_total * 0.5
        progress += len([c for c in battlefield if "#Draw" in c.tags]) * 0.8
        progress += len([c for c in battlefield if "#Engine" in c.tags]) * 1.0
        if commander_cast_turn is not None:
            progress += 1.2
        combat_snapshot = _combat_metrics(battlefield, cast_this_turn, commander_card, commander_live)
        progress += min(6.0, combat_snapshot["combat_damage"] / 10.0)
        progress += min(5.0, combat_snapshot["commander_damage"] / 6.0)
        progress += min(4.0, burn_total / 10.0)
        plan_progress.append(progress)

        cast_name_set = {c.name for c in cast_this_turn}
        combat_damage_total += combat_snapshot["combat_damage"]
        commander_damage_total += combat_snapshot["commander_damage"]
        poison_total += combat_snapshot["poison_damage"]
        burn_total += sum(c.burn_value for c in cast_this_turn) + sum(c.repeatable_burn for c in battlefield if c.name not in cast_name_set)
        mill_total += sum(c.mill_value for c in cast_this_turn) + sum(c.repeatable_mill for c in battlefield if c.name not in cast_name_set)

        engine_count = len([c for c in battlefield if "#Engine" in c.tags])
        if any(t in c.tags for c in cast_this_turn for t in ["#Combo", "#Wincon", "#Payoff"]):
            phase_by_turn.append("win_attempt")
        elif engine_count >= 1 or draw_engine_turn is not None:
            phase_by_turn.append("engine")
        else:
            phase_by_turn.append("setup")

        wincon_hit = None
        wincon_reason = None
        if win_turn is None:
            wincon_hit, wincon_reason = _detect_wincon_for_turn(
                selected_wincons=selected_wincons,
                cast_this_turn=cast_this_turn,
                battlefield=battlefield,
                turn=turn,
                commander_cast_turn=commander_cast_turn,
                mana_total=mana_total,
                commander=commander,
                commander_live=commander_live,
                commander_card=commander_card,
                combo_variants=combo_variants,
                combo_source_live=combo_source_live,
                library_size=len(lib),
                graveyard_count=graveyard_count,
                combat_damage_total=combat_damage_total,
                commander_damage_total=commander_damage_total,
                poison_total=poison_total,
                burn_total=burn_total,
                mill_total=mill_total,
            )
            if wincon_hit is not None:
                win_turn = turn
                achieved_wincon = wincon_hit
                win_reason = wincon_reason

        if capture_trace:
            turn_trace.append(
                {
                    "turn": turn,
                    "draw": draw_name,
                    "land": land_name,
                    "casts": cast_names,
                    "actions": len(cast_names),
                    "mana_total": mana_total,
                    "phase": phase_by_turn[-1] if phase_by_turn else "setup",
                    "wincon_hit": wincon_hit,
                    "win_reason": wincon_reason,
                }
            )

    dead_cards = [c.name for c in hand if c.mana_value > max(mana_by_turn)]

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
        trace={
            "opening_hand": opening_hand,
            "mulligan_steps": mulligan_steps,
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
    combo_variants: List[Dict] | None = None,
    combo_source_live: bool = False,
) -> Dict:
    rng = random.Random(seed)
    selected_wincons = _normalize_wincons(primary_wincons)
    deck, commander_card = _build_sim_deck(cards, commander)
    normalized_combo_variants = _normalize_combo_variants(combo_variants)

    results: List[RunMetrics] = []
    decision_samples = []
    run_seeds: List[int] = []

    for i in range(runs):
        run_seed = rng.randint(0, 2**31 - 1)
        run_seeds.append(run_seed)
        local_rng = random.Random(run_seed)
        out = simulate_one(
            deck,
            commander,
            commander_card,
            turn_limit,
            policy,
            multiplayer,
            threat_model,
            local_rng,
            primary_wincons=primary_wincons,
            color_identity_size=color_identity_size,
            combo_variants=normalized_combo_variants,
            combo_source_live=combo_source_live,
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
    win_turns = [r.win_turn for r in results if r.win_turn is not None]
    wincon_counter = Counter(r.achieved_wincon for r in results if r.achieved_wincon)
    for r in results:
        if r.mana_by_turn[2] < 3:
            failure_modes["mana_screw"] += 1
        if max(r.mana_by_turn) > 10 and r.cards_seen < turn_limit + 6:
            failure_modes["flood"] += 1
        if not any(x > 3 for x in r.plan_progress_by_turn[:3]):
            failure_modes["no_action"] += 1

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
            commander,
            commander_card,
            turn_limit,
            policy,
            multiplayer,
            threat_model,
            random.Random(run_seeds[idx]),
            primary_wincons=primary_wincons,
            color_identity_size=color_identity_size,
            combo_variants=normalized_combo_variants,
            combo_source_live=combo_source_live,
            capture_trace=True,
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

    summary = {
        "runs": runs,
        "seed": seed,
        "policy": policy,
        "turn_limit": turn_limit,
        "selected_wincons": selected_wincons,
        "milestones": {
            "p_mana4_t3": p_mana4_t3,
            "p_mana5_t4": p_mana5_t4,
            "median_commander_cast_turn": median(cmd_turns) if cmd_turns else None,
        },
        "win_metrics": {
            "p_win_by_turn_limit": (len(win_turns) / runs) if runs else 0.0,
            "median_win_turn": median(win_turns) if win_turns else None,
            "most_common_wincon": wincon_counter.most_common(1)[0][0] if wincon_counter else None,
            "wincon_distribution": {
                k: (v / runs)
                for k, v in wincon_counter.items()
            },
        },
        "uncertainty": {
            "p_mana4_t3_ci95": _binom_ci95(p_mana4_t3, runs),
            "p_mana5_t4_ci95": _binom_ci95(p_mana5_t4, runs),
            "p_win_by_turn_limit_ci95": _binom_ci95((len(win_turns) / runs) if runs else 0.0, runs),
        },
        "plan_progress": {
            t: {
                "median": median(v),
                "p90": _percentile(v, 0.9),
            }
            for t, v in per_turn_progress.items()
        },
        "failure_modes": {k: v / runs for k, v in failure_modes.items()},
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
        "combo_detection": {
            "source_live": combo_source_live,
            "matched_variants": len(normalized_combo_variants),
        },
    }

    return {"summary": summary}
