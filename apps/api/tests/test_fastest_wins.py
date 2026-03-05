from sim.engine import run_simulation_batch as run_python
from sim.engine_vectorized import run_simulation_batch_vectorized as run_vectorized


def _sample_cards():
    cards = [{"qty": 1, "name": f"Land{i}", "tags": ["#Land", "#Fixing"], "mana_value": 0} for i in range(38)]
    cards += [{"qty": 1, "name": f"Ramp{i}", "tags": ["#Ramp", "#FastMana"], "mana_value": 1} for i in range(10)]
    cards += [{"qty": 1, "name": f"Engine{i}", "tags": ["#Draw", "#Engine"], "mana_value": 2} for i in range(12)]
    cards += [{"qty": 1, "name": f"Pay{i}", "tags": ["#Payoff", "#Wincon"], "mana_value": 3} for i in range(40)]
    return cards[:100]


def _assert_fastest_shape(summary: dict):
    fw = summary.get("fastest_wins", [])
    assert isinstance(fw, list)
    assert len(fw) <= 3
    for i, row in enumerate(fw, start=1):
        assert row.get("rank") == i
        assert isinstance(row.get("opening_hand", []), list)
        assert isinstance(row.get("mulligan_steps", []), list)
        assert isinstance(row.get("turns", []), list)
        if row.get("turns"):
            turn1 = row["turns"][0]
            assert "turn" in turn1
            assert "casts" in turn1


def test_python_backend_exposes_fastest_wins():
    out = run_python(
        cards=_sample_cards(),
        commander=None,
        runs=600,
        turn_limit=8,
        policy="optimized",
        multiplayer=True,
        threat_model=False,
        seed=42,
    )
    _assert_fastest_shape(out["summary"])


def test_vectorized_backend_exposes_fastest_wins():
    out = run_vectorized(
        cards=_sample_cards(),
        commander=None,
        runs=600,
        turn_limit=8,
        policy="optimized",
        multiplayer=True,
        threat_model=False,
        seed=42,
        batch_size=256,
    )
    _assert_fastest_shape(out["summary"])
