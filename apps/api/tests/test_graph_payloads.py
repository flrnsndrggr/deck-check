from sim.engine import run_simulation_batch


def _sample_cards():
    cards = [{"qty": 1, "name": f"Land{i}", "tags": ["#Land", "#Fixing"], "mana_value": 0} for i in range(37)]
    cards += [{"qty": 1, "name": f"Ramp{i}", "tags": ["#Ramp"], "mana_value": 2} for i in range(14)]
    cards += [{"qty": 1, "name": f"Engine{i}", "tags": ["#Draw", "#Engine"], "mana_value": 3} for i in range(12)]
    cards += [{"qty": 1, "name": f"Pay{i}", "tags": ["#Payoff", "#Wincon"], "mana_value": 5} for i in range(37)]
    return cards[:100]


def test_graph_payload_shapes_and_bounds():
    out = run_simulation_batch(
        cards=_sample_cards(),
        commander=None,
        runs=400,
        turn_limit=8,
        policy="optimized",
        multiplayer=True,
        threat_model=True,
        seed=42,
    )
    gp = out["summary"]["graph_payloads"]
    assert gp["mana_percentiles"]
    assert gp["land_hit_cdf"]
    assert gp["phase_timeline"]
    assert gp["win_turn_cdf"]
    assert gp["mulligan_funnel"]
    assert all(0 <= x["p_hit_on_curve"] <= 1 for x in gp["land_hit_cdf"])
    assert all(0 <= x["cdf"] <= 1 for x in gp["win_turn_cdf"])
    assert all(0 <= x["setup"] <= 1 and 0 <= x["engine"] <= 1 and 0 <= x["win_attempt"] <= 1 for x in gp["phase_timeline"])


def test_win_turn_cdf_monotonic():
    out = run_simulation_batch(
        cards=_sample_cards(),
        commander=None,
        runs=250,
        turn_limit=8,
        policy="optimized",
        multiplayer=True,
        threat_model=False,
        seed=99,
    )
    vals = [x["cdf"] for x in out["summary"]["graph_payloads"]["win_turn_cdf"]]
    assert all(vals[i] <= vals[i + 1] for i in range(len(vals) - 1))
