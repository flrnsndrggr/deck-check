from sim.engine import run_simulation_batch as run_python
from sim.engine_vectorized import run_simulation_batch_vectorized as run_vectorized


def _sample_cards():
    cards = [{"qty": 1, "name": f"Land{i}", "tags": ["#Land", "#Fixing"], "mana_value": 0} for i in range(37)]
    cards += [{"qty": 1, "name": f"Ramp{i}", "tags": ["#Ramp"], "mana_value": 2} for i in range(14)]
    cards += [{"qty": 1, "name": f"Engine{i}", "tags": ["#Draw", "#Engine"], "mana_value": 3} for i in range(12)]
    cards += [{"qty": 1, "name": f"Pay{i}", "tags": ["#Payoff", "#Wincon"], "mana_value": 5} for i in range(37)]
    return cards[:100]


def test_vectorized_backend_metadata_and_determinism():
    kwargs = dict(
        cards=_sample_cards(),
        commander=None,
        runs=600,
        turn_limit=8,
        policy="optimized",
        multiplayer=True,
        threat_model=True,
        seed=42,
        batch_size=256,
    )
    a = run_vectorized(**kwargs)
    b = run_vectorized(**kwargs)
    sa = a["summary"]
    sb = b["summary"]
    assert sa["backend_used"] == "vectorized"
    assert sa["milestones"] == sb["milestones"]
    assert sa["failure_modes"] == sb["failure_modes"]


def test_vectorized_and_python_parity_band():
    kwargs = dict(
        cards=_sample_cards(),
        commander=None,
        runs=1200,
        turn_limit=8,
        policy="optimized",
        multiplayer=True,
        threat_model=False,
        seed=99,
    )
    py = run_python(**kwargs)["summary"]
    vec = run_vectorized(**kwargs, batch_size=256)["summary"]

    assert abs(py["milestones"]["p_mana4_t3"] - vec["milestones"]["p_mana4_t3"]) <= 0.08
    assert abs(py["milestones"]["p_mana5_t4"] - vec["milestones"]["p_mana5_t4"]) <= 0.08
    assert abs(py["failure_modes"]["no_action"] - vec["failure_modes"]["no_action"]) <= 0.12

