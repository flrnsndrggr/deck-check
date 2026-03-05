import time

from sim.engine import run_simulation_batch


def test_simulation_10k_runs_performance():
    cards = [{"qty": 1, "name": f"Land{i}", "tags": ["#Land"], "mana_value": 0} for i in range(40)]
    cards += [{"qty": 1, "name": f"Spell{i}", "tags": ["#Ramp", "#Draw"], "mana_value": 2} for i in range(60)]

    start = time.perf_counter()
    out = run_simulation_batch(cards=cards, commander=None, runs=10000, turn_limit=6, policy="auto", multiplayer=True, threat_model=False, seed=42)
    elapsed = time.perf_counter() - start

    assert out["summary"]["runs"] == 10000
    assert elapsed < 8.0
