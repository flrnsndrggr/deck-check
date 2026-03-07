from __future__ import annotations

import pytest

from sim.config import resolve_sim_config
from sim.engine import run_simulation_batch as run_python
from sim.engine_vectorized import run_simulation_batch_vectorized as run_vectorized
from sim_benchmark_fixtures import SIM_BENCHMARK_FIXTURES, SimBenchmarkFixture


PARITY_FIXTURES = [
    fixture
    for fixture in SIM_BENCHMARK_FIXTURES.values()
    if fixture.parity_supported
]


def _commander_arg(fixture: SimBenchmarkFixture) -> str | list[str] | None:
    if not fixture.commanders:
        return None
    if len(fixture.commanders) == 1:
        return fixture.commanders[0]
    return list(fixture.commanders)


def _resolved_payload(
    fixture: SimBenchmarkFixture,
    *,
    seed: int,
    policy: str,
    threat_model: bool = False,
) -> dict:
    return resolve_sim_config(
        commander=_commander_arg(fixture),
        requested_policy=policy,
        bracket=3,
        turn_limit=8,
        multiplayer=True,
        threat_model=threat_model,
        primary_wincons=None,
        color_identity_size=max(1, len(fixture.commanders)),
        seed=seed,
    ).to_payload()


def _run_kwargs(
    fixture: SimBenchmarkFixture,
    *,
    seed: int,
    runs: int,
    policy: str = "optimized",
    threat_model: bool = False,
) -> dict:
    return {
        "cards": fixture.cards,
        "commander": _commander_arg(fixture),
        "runs": runs,
        "turn_limit": 8,
        "policy": policy,
        "multiplayer": True,
        "threat_model": threat_model,
        "seed": seed,
        "resolved_config": _resolved_payload(
            fixture,
            seed=seed,
            policy=policy,
            threat_model=threat_model,
        ),
    }


@pytest.mark.parametrize("fixture", PARITY_FIXTURES, ids=lambda fixture: fixture.slug)
def test_supported_fixture_reference_trace_prefix_matches(fixture: SimBenchmarkFixture):
    kwargs = _run_kwargs(fixture, seed=17, runs=8, policy="optimized", threat_model=False)
    py = run_python(**kwargs)["summary"]
    vec = run_vectorized(**kwargs, batch_size=64)["summary"]

    py_trace = py["reference_trace"]
    vec_trace = vec["reference_trace"]

    assert py["commander_slots"] == vec["commander_slots"] == list(fixture.commanders)
    assert py_trace["opening_hand"] == vec_trace["opening_hand"]
    assert py_trace["mulligans_taken"] == vec_trace["mulligans_taken"]
    assert py_trace["turns"][0]["land"] == vec_trace["turns"][0]["land"]
    assert py_trace["turns"][0]["casts"] == vec_trace["turns"][0]["casts"]


@pytest.mark.parametrize("fixture", PARITY_FIXTURES, ids=lambda fixture: fixture.slug)
def test_supported_fixture_distribution_parity_band(fixture: SimBenchmarkFixture):
    kwargs = _run_kwargs(fixture, seed=91, runs=192, policy="optimized", threat_model=False)
    py = run_python(**kwargs)["summary"]
    vec = run_vectorized(**kwargs, batch_size=96)["summary"]

    assert abs(py["milestones"]["p_mana4_t3"] - vec["milestones"]["p_mana4_t3"]) <= 0.12
    assert abs(py["milestones"]["p_mana5_t4"] - vec["milestones"]["p_mana5_t4"]) <= 0.12

    py_cmd = py["milestones"].get("median_commander_cast_turn")
    vec_cmd = vec["milestones"].get("median_commander_cast_turn")
    if py_cmd is None or vec_cmd is None:
        assert py_cmd == vec_cmd
    else:
        assert abs(py_cmd - vec_cmd) <= 1


def test_auto_policy_resolves_once_for_both_backends():
    fixture = SIM_BENCHMARK_FIXTURES["artifact_combo"]
    kwargs = _run_kwargs(fixture, seed=29, runs=32, policy="auto", threat_model=False)

    py = run_python(**kwargs)["summary"]
    vec = run_vectorized(**kwargs, batch_size=64)["summary"]

    assert py["resolved_policy"]["resolved_policy"] == vec["resolved_policy"]["resolved_policy"]
    assert py["reference_trace"]["opening_hand"] == vec["reference_trace"]["opening_hand"]
    assert py["reference_trace"]["mulligans_taken"] == vec["reference_trace"]["mulligans_taken"]


def test_multi_commander_slots_exist_in_both_backends():
    fixture = SIM_BENCHMARK_FIXTURES["multi_commander"]
    kwargs = _run_kwargs(fixture, seed=5, runs=24, policy="optimized", threat_model=False)

    py = run_python(**kwargs)["summary"]
    vec = run_vectorized(**kwargs, batch_size=64)["summary"]

    assert py["commander_slots"] == list(fixture.commanders)
    assert vec["commander_slots"] == list(fixture.commanders)
    assert py["reference_trace"]["commander_slots"] == list(fixture.commanders)
    assert vec["reference_trace"]["commander_slots"] == list(fixture.commanders)
