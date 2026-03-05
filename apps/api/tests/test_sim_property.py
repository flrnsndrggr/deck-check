from hypothesis import HealthCheck, given, settings, strategies as st
import random

from sim.engine import Card, simulate_one


@settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow])
@given(st.lists(st.sampled_from(["#Land", "#Ramp", "#Draw", "#Setup", "#Payoff"]), min_size=100, max_size=100))
def test_simulation_invariants(tags):
    deck = []
    for i, t in enumerate(tags):
        mv = 0 if t == "#Land" else 2
        deck.append(Card(name=f"C{i}", tags=[t], mana_value=mv))
    rng = random.Random(42)
    out = simulate_one(deck, commander=None, turn_limit=6, policy="casual", multiplayer=True, threat_model=False, rng=rng)
    assert all(m >= 0 for m in out.mana_by_turn)
