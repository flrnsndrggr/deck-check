from __future__ import annotations

import random

from hypothesis import HealthCheck, given, settings, strategies as st

from sim.engine import Card, run_simulation_batch as run_python, simulate_one
from sim.ir import CoverageSummary, DeckFingerprint, Winline
from sim.planner import choose_best_action
from sim.state import GameState
from sim_benchmark_fixtures import SIM_BENCHMARK_FIXTURES


class _Exec:
    def __init__(self, executable=(), support_score=1.0):
        self.coverage_summary = CoverageSummary(
            executable=tuple(executable),
            evaluative_only=(),
            unsupported=(),
            support_score=support_score,
        )
        self.activated = ()


@settings(max_examples=8, suppress_health_check=[HealthCheck.too_slow])
@given(st.lists(st.sampled_from(["#Land", "#Ramp", "#Draw", "#Setup", "#Payoff"]), min_size=100, max_size=100))
def test_simulation_invariants(tags):
    deck = []
    for i, tag in enumerate(tags):
        mv = 0 if tag == "#Land" else 2
        deck.append(Card(name=f"C{i}", tags=[tag], mana_value=mv))
    rng = random.Random(42)
    out = simulate_one(deck, commander=None, turn_limit=6, policy="casual", multiplayer=True, threat_model=False, rng=rng)
    assert all(m >= 0 for m in out.mana_by_turn)


def test_removing_opponent_hazard_does_not_reduce_solitaire_hard_win_rate():
    fixture = SIM_BENCHMARK_FIXTURES["artifact_combo"]
    commander = fixture.commanders[0]

    pure = run_python(
        cards=fixture.cards,
        commander=commander,
        runs=16,
        turn_limit=8,
        policy="optimized",
        multiplayer=True,
        threat_model=False,
        seed=19,
    )["summary"]
    pressured = run_python(
        cards=fixture.cards,
        commander=commander,
        runs=16,
        turn_limit=8,
        policy="optimized",
        multiplayer=True,
        threat_model=True,
        seed=19,
    )["summary"]

    assert pure["hard_win_rate"] >= pressured["hard_win_rate"]


def test_better_untapped_fixing_land_does_not_reduce_early_mana_access():
    base_cards = [
        {"qty": 1, "name": f"Tapped Fixer {idx}", "tags": ["#Land", "#Fixing"], "mana_value": 0, "type_line": "Land", "oracle_text": "Enters tapped."}
        for idx in range(12)
    ]
    upgraded_cards = [
        {"qty": 1, "name": "Untapped Fixer", "tags": ["#Land", "#Fixing"], "mana_value": 0, "type_line": "Land", "oracle_text": ""}
    ] + base_cards[1:]
    filler = [{"qty": 1, "name": f"Spell {idx}", "tags": ["#Ramp" if idx < 10 else "#Draw"], "mana_value": 2} for idx in range(88)]

    base = run_python(
        cards=base_cards + filler,
        commander=None,
        runs=16,
        turn_limit=6,
        policy="optimized",
        multiplayer=True,
        threat_model=False,
        seed=7,
        color_identity_size=2,
    )["summary"]
    upgraded = run_python(
        cards=upgraded_cards + filler,
        commander=None,
        runs=16,
        turn_limit=6,
        policy="optimized",
        multiplayer=True,
        threat_model=False,
        seed=7,
        color_identity_size=2,
    )["summary"]

    assert upgraded["milestones"]["p_mana4_t3"] >= base["milestones"]["p_mana4_t3"]


def test_hidden_library_order_does_not_change_pre_draw_action_choice():
    hand = [
        Card(name="Command Tower", tags=["#Land", "#Fixing"], mana_value=0, type_line="Land"),
        Card(name="Mind Stone", tags=["#Ramp"], mana_value=2, is_permanent=True, type_line="Artifact"),
        Card(name="Chart a Course", tags=["#Draw"], mana_value=2, type_line="Sorcery"),
    ]
    commander_cards = [
        Card(name="Engine Commander", tags=["#Engine"], mana_value=3, is_creature=True, is_permanent=True, is_commander=True)
    ]
    exec_lookup = {
        "mind stone": _Exec(executable=("mana_source",)),
        "chart a course": _Exec(executable=("draw",)),
        "engine commander": _Exec(executable=("draw",)),
    }
    fingerprint = DeckFingerprint(
        primary_plan="combat",
        secondary_plan=None,
        commander_role="engine",
        speed_tier="optimized",
        prefers_focus_fire=False,
        protection_density=0.0,
        resource_profile=("ramp",),
        conversion_profile=("combat",),
        wipe_recovery=0.0,
        support_confidence=1.0,
    )
    winlines = (Winline(kind="combat", requirements=("board_presence",), support=(), sink_requirements=(), horizon_class="soon"),)
    state_a = GameState(
        hand=list(hand),
        library=[Card(name="Library A"), Card(name="Library B")],
    )
    state_b = GameState(
        hand=list(hand),
        library=[Card(name="Library B"), Card(name="Library A")],
    )

    chosen_a = choose_best_action(
        state=state_a,
        hand=state_a.hand,
        commander_cards=commander_cards,
        commander_live_names=set(),
        commander_index={"engine commander": 0},
        exec_lookup=exec_lookup,
        intent="develop",
        fingerprint=fingerprint,
        winlines=winlines,
        threat_model=False,
        opponent_table=None,
    )
    chosen_b = choose_best_action(
        state=state_b,
        hand=state_b.hand,
        commander_cards=commander_cards,
        commander_live_names=set(),
        commander_index={"engine commander": 0},
        exec_lookup=exec_lookup,
        intent="develop",
        fingerprint=fingerprint,
        winlines=winlines,
        threat_model=False,
        opponent_table=None,
    )

    assert chosen_a is not None and chosen_b is not None
    assert chosen_a["type"] == chosen_b["type"]
    assert getattr(chosen_a.get("card"), "name", None) == getattr(chosen_b.get("card"), "name", None)
