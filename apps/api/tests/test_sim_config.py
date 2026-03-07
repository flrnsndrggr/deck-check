from sim.config import build_commander_slots, resolve_sim_config
from sim.rng import RNGManager


def test_resolve_sim_config_normalizes_auto_once():
    resolved = resolve_sim_config(
        commander=["Partner A", "Partner B"],
        requested_policy="auto",
        bracket=5,
        turn_limit=8,
        multiplayer=True,
        threat_model=True,
        primary_wincons=["Combo"],
        color_identity_size=4,
        seed=42,
    )

    assert resolved.policy.resolved_policy == "cedh"
    assert resolved.commander_slots == ("Partner A", "Partner B")
    assert resolved.selected_wincons == ("Combo",)


def test_rng_manager_named_streams_are_deterministic_and_partitioned():
    rng_a = RNGManager(42)
    rng_b = RNGManager(42)

    assert rng_a.seed("mulligan", 1) == rng_b.seed("mulligan", 1)
    assert rng_a.seed("mulligan", 1) != rng_a.seed("draws", 1)
    assert rng_a.permutation("mulligan", 10, 0).tolist() == rng_b.permutation("mulligan", 10, 0).tolist()


def test_build_commander_slots_caps_at_two():
    assert build_commander_slots(["A", "B", "C"]) == ("A", "B")
