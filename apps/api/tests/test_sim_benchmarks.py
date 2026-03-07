from __future__ import annotations

import pytest

from sim.engine import _build_sim_deck, run_simulation_batch as run_python
from sim.ir import compile_card_execs
from sim.planner import compile_deck_fingerprint
from sim_benchmark_fixtures import SIM_BENCHMARK_FIXTURES, SimBenchmarkFixture


@pytest.mark.parametrize(
    "fixture",
    list(SIM_BENCHMARK_FIXTURES.values()),
    ids=lambda fixture: fixture.slug,
)
def test_benchmark_fixture_shape_and_primary_plan(fixture: SimBenchmarkFixture):
    assert sum(int(card.get("qty", 1)) for card in fixture.cards) == 100
    deck, commander_cards = _build_sim_deck(fixture.cards, list(fixture.commanders))
    exec_lookup = {card_exec.name.strip().lower(): card_exec for card_exec in compile_card_execs(fixture.cards)}
    fingerprint = compile_deck_fingerprint(deck, commander_cards, exec_lookup)

    assert fingerprint.primary_plan == fixture.expected_primary_plan


@pytest.mark.parametrize(
    "fixture",
    list(SIM_BENCHMARK_FIXTURES.values()),
    ids=lambda fixture: fixture.slug,
)
def test_benchmark_fixture_reference_backend_emits_coverage_and_outcomes(fixture: SimBenchmarkFixture):
    commander = list(fixture.commanders) if len(fixture.commanders) > 1 else fixture.commanders[0]
    summary = run_python(
        cards=fixture.cards,
        commander=commander,
        runs=3,
        turn_limit=8,
        policy="optimized",
        multiplayer=True,
        threat_model=False,
        seed=11,
    )["summary"]

    assert summary["ir_version"] == 2
    assert 0.0 <= summary["support_confidence"] <= 1.0
    assert "coverage_summary" in summary
    assert "outcome_distribution" in summary
    assert set(summary["outcome_distribution"].keys()) <= {"hard_win", "model_win", "dominant", "none"}


def test_text_dense_canary_reports_unsupported_effect_risk():
    fixture = SIM_BENCHMARK_FIXTURES["text_dense_canary"]
    summary = run_python(
        cards=fixture.cards,
        commander=fixture.commanders[0],
        runs=2,
        turn_limit=8,
        policy="optimized",
        multiplayer=True,
        threat_model=False,
        seed=23,
    )["summary"]

    coverage = summary["coverage_summary"]
    assert coverage["unsupported_effects"]
    assert summary["support_confidence"] < 1.0


def test_multi_commander_benchmark_preserves_slots():
    fixture = SIM_BENCHMARK_FIXTURES["multi_commander"]
    summary = run_python(
        cards=fixture.cards,
        commander=list(fixture.commanders),
        runs=2,
        turn_limit=8,
        policy="optimized",
        multiplayer=True,
        threat_model=False,
        seed=31,
    )["summary"]

    assert summary["commander_slots"] == list(fixture.commanders)
