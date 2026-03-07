from __future__ import annotations

import random

from sim.config import OpponentProfile
from sim.opponents import (
    VirtualOpponent,
    VirtualTable,
    maybe_counter_spell,
    maybe_wipe_event,
    sample_virtual_table,
)
from sim.planner import choose_turn_intent
from sim.rng import RNGManager
from sim.state import GameState
from sim.ir import DeckFingerprint, Winline


class _Card:
    def __init__(self, name: str, tags: list[str] | None = None, is_commander: bool = False):
        self.name = name
        self.tags = tags or []
        self.is_commander = is_commander


def _optimized_profile() -> OpponentProfile:
    return OpponentProfile(
        profile_id="optimized_table",
        multiplayer=True,
        threat_model=True,
        life_pressure=0.55,
        blocker_density=0.45,
        spot_removal_budget=1,
        counter_budget=1,
        wipe_budget=1,
        table_noise=0.6,
        threat_tolerance=0.45,
    )


def test_sample_virtual_table_is_deterministic_for_same_seed():
    profile = _optimized_profile()
    first = sample_virtual_table(profile, RNGManager(42), 42)
    second = sample_virtual_table(profile, RNGManager(42), 42)

    assert [op.archetype for op in first.opponents] == [op.archetype for op in second.opponents]
    assert [op.spot_removal_budget for op in first.opponents] == [op.spot_removal_budget for op in second.opponents]
    assert [op.counter_budget for op in first.opponents] == [op.counter_budget for op in second.opponents]


def test_counter_budget_is_finite_and_spent():
    table = VirtualTable(
        opponents=[
            VirtualOpponent("control", 0.4, 0.3, 0, 1, 0, 0.0, 0.0, 0.1, 0, 0),
            VirtualOpponent("goldfish", 0.0, 0.0, 0, 0, 0, 0.0, 0.0, 1.0, 0, 0),
            VirtualOpponent("goldfish", 0.0, 0.0, 0, 0, 0, 0.0, 0.0, 1.0, 0, 0),
        ],
        base_table_noise=0.0,
    )
    state = GameState(turn=5)
    spell = _Card("Big Combo", ["#Combo", "#Wincon"])

    first = maybe_counter_spell(table, state, spell, random.Random(1), 5)
    second = maybe_counter_spell(table, state, spell, random.Random(1), 5)

    assert first == 0
    assert second is None
    assert table.answer_expenditure["counter"] == 1


def test_wipe_event_respects_window_and_budget():
    table = VirtualTable(
        opponents=[
            VirtualOpponent("control", 0.4, 0.3, 0, 0, 1, 0.0, 0.0, 0.1, 4, 6),
            VirtualOpponent("goldfish", 0.0, 0.0, 0, 0, 0, 0.0, 0.0, 1.0, 0, 0),
            VirtualOpponent("goldfish", 0.0, 0.0, 0, 0, 0, 0.0, 0.0, 1.0, 0, 0),
        ],
        base_table_noise=0.0,
    )
    state = GameState(turn=5)

    hit = maybe_wipe_event(table, state, random.Random(2), 5, battlefield_salience=6.0)
    miss = maybe_wipe_event(table, state, random.Random(2), 5, battlefield_salience=6.0)

    assert hit == 0
    assert miss is None
    assert table.answer_expenditure["wipe"] == 1
    assert table.wipe_turns == [5]


def test_choose_turn_intent_can_switch_to_race_under_pressure():
    state = GameState(turn=6, self_life=8.0)
    table = VirtualTable(
        opponents=[
            VirtualOpponent("aggro", 0.95, 0.35, 1, 0, 0, 0.0, 0.0, 0.7, 0, 0),
            VirtualOpponent("midrange", 0.7, 0.5, 1, 0, 1, 0.0, 0.0, 0.55, 5, 7),
            VirtualOpponent("goldfish", 0.0, 0.0, 0, 0, 0, 0.0, 0.0, 1.0, 0, 0),
        ],
        base_table_noise=0.55,
    )
    fingerprint = DeckFingerprint(
        primary_plan="combat",
        secondary_plan=None,
        commander_role="engine",
        speed_tier="optimized",
        prefers_focus_fire=False,
        protection_density=0.0,
        resource_profile=("ramp",),
        conversion_profile=("combat",),
        wipe_recovery=0.2,
        support_confidence=1.0,
    )
    winlines = (Winline(kind="combat", requirements=("board_presence",), support=(), sink_requirements=(), horizon_class="soon"),)

    intent = choose_turn_intent(
        state,
        hand=[_Card("Attacker", ["#Payoff"])],
        fingerprint=fingerprint,
        winlines=winlines,
        threat_model=True,
        opponent_table=table,
    )

    assert intent == "race"
