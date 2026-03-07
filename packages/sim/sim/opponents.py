from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Literal, Sequence

from sim.config import OpponentProfile
from sim.rng import RNGManager

OpponentArchetype = Literal["goldfish", "aggro", "midrange", "control", "combo"]


@dataclass(frozen=True)
class OpponentArchetypeTemplate:
    archetype: OpponentArchetype
    life_pressure: float
    blocker_density: float
    spot_removal_budget: int
    counter_budget: int
    wipe_budget: int
    artifact_hate_chance: float
    graveyard_hate_chance: float
    threat_tolerance: float
    wipe_window: tuple[int, int]


@dataclass
class VirtualOpponent:
    archetype: OpponentArchetype
    life_pressure: float
    blocker_density: float
    spot_removal_budget: int
    counter_budget: int
    wipe_budget: int
    artifact_hate_chance: float
    graveyard_hate_chance: float
    threat_tolerance: float
    wipe_window_start: int
    wipe_window_end: int
    spent_spot_removal: int = 0
    spent_counter: int = 0
    spent_wipe: int = 0

    @property
    def remaining_spot_removal(self) -> int:
        return max(0, self.spot_removal_budget - self.spent_spot_removal)

    @property
    def remaining_counter(self) -> int:
        return max(0, self.counter_budget - self.spent_counter)

    @property
    def remaining_wipe(self) -> int:
        return max(0, self.wipe_budget - self.spent_wipe)

    def to_payload(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class VirtualTable:
    opponents: list[VirtualOpponent]
    base_table_noise: float
    interaction_events: dict[str, int] = field(
        default_factory=lambda: {
            "counter": 0,
            "spot_removal": 0,
            "wipe": 0,
            "artifact_hate": 0,
            "graveyard_hate": 0,
        }
    )
    answer_expenditure: dict[str, int] = field(
        default_factory=lambda: {
            "counter": 0,
            "spot_removal": 0,
            "wipe": 0,
        }
    )
    wipe_turns: list[int] = field(default_factory=list)

    def to_payload(self) -> Dict[str, Any]:
        return {
            "opponents": [opponent.to_payload() for opponent in self.opponents],
            "base_table_noise": self.base_table_noise,
            "interaction_events": dict(self.interaction_events),
            "answer_expenditure": dict(self.answer_expenditure),
            "wipe_turns": list(self.wipe_turns),
        }


_ARCHETYPE_TEMPLATES: dict[OpponentArchetype, OpponentArchetypeTemplate] = {
    "goldfish": OpponentArchetypeTemplate("goldfish", 0.0, 0.0, 0, 0, 0, 0.0, 0.0, 1.0, (0, 0)),
    "aggro": OpponentArchetypeTemplate("aggro", 0.95, 0.35, 1, 0, 0, 0.08, 0.06, 0.72, (5, 7)),
    "midrange": OpponentArchetypeTemplate("midrange", 0.68, 0.6, 2, 0, 1, 0.16, 0.15, 0.58, (5, 8)),
    "control": OpponentArchetypeTemplate("control", 0.34, 0.45, 2, 2, 1, 0.22, 0.18, 0.28, (4, 7)),
    "combo": OpponentArchetypeTemplate("combo", 0.45, 0.22, 1, 1, 0, 0.06, 0.1, 0.22, (0, 0)),
}

_PROFILE_WEIGHTS: dict[str, dict[OpponentArchetype, float]] = {
    "goldfish": {"goldfish": 1.0},
    "casual_table": {"aggro": 0.28, "midrange": 0.42, "control": 0.15, "combo": 0.15},
    "optimized_table": {"aggro": 0.2, "midrange": 0.35, "control": 0.25, "combo": 0.2},
    "high_power_table": {"aggro": 0.15, "midrange": 0.2, "control": 0.3, "combo": 0.35},
}


def _weighted_choice(rng: random.Random, weights: dict[OpponentArchetype, float]) -> OpponentArchetype:
    items = list(weights.items())
    total = sum(max(0.0, weight) for _name, weight in items)
    if total <= 0:
        return "goldfish"
    needle = rng.random() * total
    acc = 0.0
    for archetype, weight in items:
        acc += max(0.0, weight)
        if needle <= acc:
            return archetype
    return items[-1][0]


def _blend(template_value: float, base_value: float, rng: random.Random, jitter: float = 0.08) -> float:
    return max(0.0, ((template_value * 0.65) + (base_value * 0.35)) * rng.uniform(1.0 - jitter, 1.0 + jitter))


def sample_virtual_table(profile: OpponentProfile, rng_manager: RNGManager | None, seed: int | None = None) -> VirtualTable:
    if not profile.multiplayer or not profile.threat_model:
        template = _ARCHETYPE_TEMPLATES["goldfish"]
        return VirtualTable(
            opponents=[
                VirtualOpponent(
                    archetype=template.archetype,
                    life_pressure=template.life_pressure,
                    blocker_density=template.blocker_density,
                    spot_removal_budget=template.spot_removal_budget,
                    counter_budget=template.counter_budget,
                    wipe_budget=template.wipe_budget,
                    artifact_hate_chance=template.artifact_hate_chance,
                    graveyard_hate_chance=template.graveyard_hate_chance,
                    threat_tolerance=template.threat_tolerance,
                    wipe_window_start=0,
                    wipe_window_end=0,
                )
                for _ in range(3)
            ],
            base_table_noise=0.0,
        )

    opponent_seed = rng_manager.seed("opponent", 0) if rng_manager is not None else int(seed or 0) + 7919
    rng = random.Random(opponent_seed)
    weights = _PROFILE_WEIGHTS.get(profile.profile_id, _PROFILE_WEIGHTS["optimized_table"])
    opponents: list[VirtualOpponent] = []
    for _ in range(3):
        archetype = _weighted_choice(rng, weights)
        template = _ARCHETYPE_TEMPLATES[archetype]
        spot_budget = max(0, int(round((template.spot_removal_budget * 0.65) + (profile.spot_removal_budget * 0.35) + rng.uniform(-0.35, 0.35))))
        counter_budget = max(0, int(round((template.counter_budget * 0.7) + (profile.counter_budget * 0.3) + rng.uniform(-0.25, 0.25))))
        wipe_budget = max(0, int(round((template.wipe_budget * 0.65) + (profile.wipe_budget * 0.35) + rng.uniform(-0.25, 0.25))))
        wipe_window = template.wipe_window
        if wipe_budget > 0 and wipe_window != (0, 0):
            start = max(3, wipe_window[0] + rng.randint(-1, 1))
            end = max(start, wipe_window[1] + rng.randint(-1, 1))
        else:
            start = 0
            end = 0
        opponents.append(
            VirtualOpponent(
                archetype=archetype,
                life_pressure=_blend(template.life_pressure, profile.life_pressure, rng),
                blocker_density=_blend(template.blocker_density, profile.blocker_density, rng),
                spot_removal_budget=spot_budget,
                counter_budget=counter_budget,
                wipe_budget=wipe_budget,
                artifact_hate_chance=_blend(template.artifact_hate_chance, 0.0, rng, jitter=0.22),
                graveyard_hate_chance=_blend(template.graveyard_hate_chance, 0.0, rng, jitter=0.22),
                threat_tolerance=min(1.0, _blend(template.threat_tolerance, profile.threat_tolerance, rng)),
                wipe_window_start=start,
                wipe_window_end=end,
            )
        )
    return VirtualTable(opponents=opponents, base_table_noise=profile.table_noise)


def live_indices(table: VirtualTable, state: Any) -> list[int]:
    out: list[int] = []
    for idx in range(min(3, len(table.opponents))):
        lethal_commander = False
        cmdr_dmg = getattr(state, "opp_cmdr_dmg", ())
        for slot in range(min(len(cmdr_dmg), 2)):
            try:
                if cmdr_dmg[slot][idx] >= 21:
                    lethal_commander = True
                    break
            except Exception:
                continue
        if state.opp_life[idx] > 0 and state.opp_poison[idx] < 10 and state.opp_library[idx] > 0 and not lethal_commander:
            out.append(idx)
    return out


def table_noise(table: VirtualTable, state: Any) -> float:
    alive = max(1, len(live_indices(table, state)))
    return max(0.05, min(0.95, table.base_table_noise + 0.04 * (alive - 1)))


def card_salience(card: Any, *, is_commander: bool = False) -> float:
    tags = set(getattr(card, "tags", []) or [])
    salience = 1.0
    if {"#Combo", "#Wincon"} & tags:
        salience = 5.0
    elif {"#Payoff", "#Engine"} & tags:
        salience = 4.0
    elif {"#Protection", "#Counter", "#Tutor"} & tags:
        salience = 3.0
    elif {"#Draw", "#Ramp", "#Setup"} & tags:
        salience = 2.0
    if is_commander:
        salience = min(5.0, salience + 0.6)
    return salience


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def response_probability(
    opponent: VirtualOpponent,
    *,
    salience: float,
    turn: int,
    table_noise_value: float,
    answer_kind: Literal["counter", "spot_removal", "wipe"],
) -> float:
    remaining = {
        "counter": opponent.remaining_counter,
        "spot_removal": opponent.remaining_spot_removal,
        "wipe": opponent.remaining_wipe,
    }[answer_kind]
    total = {
        "counter": max(1, opponent.counter_budget),
        "spot_removal": max(1, opponent.spot_removal_budget),
        "wipe": max(1, opponent.wipe_budget),
    }[answer_kind]
    if remaining <= 0:
        return 0.0
    turn_pressure = 0.18 if turn >= 5 else -0.08
    kind_bias = {
        "counter": 0.18 if opponent.archetype in {"control", "combo"} else -0.08,
        "spot_removal": 0.12 if opponent.archetype in {"midrange", "control"} else -0.02,
        "wipe": 0.1 if opponent.archetype in {"midrange", "control"} else -0.12,
    }[answer_kind]
    budget_factor = remaining / total
    x = (salience - opponent.threat_tolerance - table_noise_value + turn_pressure + kind_bias) * 1.25
    return max(0.0, min(0.97, _sigmoid(x) * budget_factor))


def expected_incoming_pressure(table: VirtualTable, state: Any, turn: int) -> float:
    total = 0.0
    for idx in live_indices(table, state):
        opponent = table.opponents[idx]
        curve = 0.85 + 0.11 * turn
        if opponent.archetype == "aggro":
            curve = 1.05 + 0.14 * turn
        elif opponent.archetype == "control":
            curve = 0.45 + 0.07 * turn
        elif opponent.archetype == "combo":
            curve = 0.55 + 0.08 * turn
        total += max(0.0, opponent.life_pressure * curve)
    return round(total, 4)


def blocker_budget_vector(table: VirtualTable, state: Any, turn: int) -> list[float]:
    out: list[float] = []
    for idx in range(3):
        if idx >= len(table.opponents) or idx not in live_indices(table, state):
            out.append(0.0)
            continue
        opponent = table.opponents[idx]
        out.append(round(max(0.0, opponent.blocker_density * (1.1 + 0.6 * turn)), 4))
    return out


def maybe_counter_spell(table: VirtualTable, state: Any, card: Any, rng: random.Random, turn: int) -> int | None:
    salience = card_salience(card, is_commander=bool(getattr(card, "is_commander", False)))
    noise = table_noise(table, state)
    for idx in live_indices(table, state):
        opponent = table.opponents[idx]
        p = response_probability(opponent, salience=salience, turn=turn, table_noise_value=noise, answer_kind="counter")
        if p > 0 and rng.random() < p:
            opponent.spent_counter += 1
            table.interaction_events["counter"] += 1
            table.answer_expenditure["counter"] += 1
            return idx
    return None


def maybe_remove_permanent(table: VirtualTable, state: Any, card: Any, rng: random.Random, turn: int) -> int | None:
    salience = card_salience(card, is_commander=bool(getattr(card, "is_commander", False)))
    noise = table_noise(table, state)
    tags = set(getattr(card, "tags", []) or [])
    for idx in live_indices(table, state):
        opponent = table.opponents[idx]
        p = response_probability(opponent, salience=salience, turn=turn, table_noise_value=noise, answer_kind="spot_removal")
        if "#Artifacts" in tags:
            p += opponent.artifact_hate_chance * 0.35
        if {"#Recursion", "#Reanimator"} & tags:
            p += opponent.graveyard_hate_chance * 0.35
        if p > 0 and rng.random() < min(0.98, p):
            opponent.spent_spot_removal += 1
            table.interaction_events["spot_removal"] += 1
            table.answer_expenditure["spot_removal"] += 1
            if "#Artifacts" in tags:
                table.interaction_events["artifact_hate"] += 1
            if {"#Recursion", "#Reanimator"} & tags:
                table.interaction_events["graveyard_hate"] += 1
            return idx
    return None


def maybe_wipe_event(table: VirtualTable, state: Any, rng: random.Random, turn: int, battlefield_salience: float) -> int | None:
    if battlefield_salience <= 0:
        return None
    noise = table_noise(table, state)
    for idx in live_indices(table, state):
        opponent = table.opponents[idx]
        if opponent.remaining_wipe <= 0:
            continue
        if opponent.wipe_window_start and not (opponent.wipe_window_start <= turn <= opponent.wipe_window_end):
            continue
        p = response_probability(
            opponent,
            salience=min(5.0, 2.6 + battlefield_salience * 0.35),
            turn=turn,
            table_noise_value=noise,
            answer_kind="wipe",
        )
        if rng.random() < p:
            opponent.spent_wipe += 1
            table.interaction_events["wipe"] += 1
            table.answer_expenditure["wipe"] += 1
            table.wipe_turns.append(turn)
            return idx
    return None
