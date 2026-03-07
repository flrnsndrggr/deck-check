from sim.engine import _build_sim_deck, run_simulation_batch as run_python
from sim.engine_vectorized import run_simulation_batch_vectorized as run_vectorized


def _combo_shell_cards():
    return [
        {"qty": 1, "name": "Combo Commander", "section": "commander", "tags": ["#CommanderSynergy"], "mana_value": 3},
        {"qty": 1, "name": "Land A", "section": "deck", "tags": ["#Land"], "mana_value": 0},
        {"qty": 1, "name": "Land B", "section": "deck", "tags": ["#Land"], "mana_value": 0},
        {"qty": 1, "name": "Land C", "section": "deck", "tags": ["#Land"], "mana_value": 0},
        {"qty": 1, "name": "Land D", "section": "deck", "tags": ["#Land"], "mana_value": 0},
        {"qty": 1, "name": "Fast Setup", "section": "deck", "tags": ["#Ramp", "#Setup"], "mana_value": 1},
        {"qty": 1, "name": "Piece One", "section": "deck", "tags": ["#Combo"], "mana_value": 1, "is_permanent": True},
        {"qty": 1, "name": "Piece Two", "section": "deck", "tags": ["#Combo"], "mana_value": 1, "is_permanent": True},
        {"qty": 1, "name": "Piece Three", "section": "deck", "tags": ["#Combo", "#Payoff", "#Wincon"], "mana_value": 1, "is_permanent": True},
    ]


def _combat_shell_cards():
    return [
        {"qty": 1, "name": "Land A", "section": "deck", "tags": ["#Land"], "mana_value": 0},
        {"qty": 1, "name": "Land B", "section": "deck", "tags": ["#Land"], "mana_value": 0},
        {"qty": 1, "name": "Land C", "section": "deck", "tags": ["#Land"], "mana_value": 0},
        {"qty": 1, "name": "Land D", "section": "deck", "tags": ["#Land"], "mana_value": 0},
        {"qty": 1, "name": "Fast Setup", "section": "deck", "tags": ["#Ramp", "#Setup"], "mana_value": 1, "is_permanent": True},
        {"qty": 1, "name": "Big Attacker", "section": "deck", "tags": ["#Payoff"], "mana_value": 2, "is_permanent": True, "is_creature": True, "power": 12, "evasion_score": 0.6},
        {"qty": 1, "name": "Overrun Engine", "section": "deck", "tags": ["#Payoff", "#Engine"], "mana_value": 2, "is_permanent": True, "combat_buff": 6},
        {"qty": 1, "name": "Extra Combat", "section": "deck", "tags": ["#Payoff"], "mana_value": 2, "is_permanent": True, "extra_combat_factor": 2.0},
    ]


def _voltron_shell_cards():
    return [
        {"qty": 1, "name": "Voltron Commander", "section": "commander", "tags": ["#Voltron", "#CommanderSynergy"], "mana_value": 3, "is_permanent": True, "is_creature": True, "power": 7, "evasion_score": 0.6},
        {"qty": 1, "name": "Land A", "section": "deck", "tags": ["#Land"], "mana_value": 0},
        {"qty": 1, "name": "Land B", "section": "deck", "tags": ["#Land"], "mana_value": 0},
        {"qty": 1, "name": "Land C", "section": "deck", "tags": ["#Land"], "mana_value": 0},
        {"qty": 1, "name": "Land D", "section": "deck", "tags": ["#Land"], "mana_value": 0},
        {"qty": 1, "name": "Fast Setup", "section": "deck", "tags": ["#Ramp", "#Setup"], "mana_value": 1, "is_permanent": True},
        {"qty": 1, "name": "Sword of Big Hits", "section": "deck", "tags": ["#Voltron", "#Protection"], "mana_value": 2, "is_permanent": True, "commander_buff": 5},
        {"qty": 1, "name": "Second Combat", "section": "deck", "tags": ["#Voltron"], "mana_value": 2, "is_permanent": True, "extra_combat_factor": 2.0},
    ]


def test_commander_is_excluded_from_shuffled_sim_deck():
    deck, commander_cards = _build_sim_deck(_combo_shell_cards(), "Combo Commander")

    assert len(commander_cards) == 1
    assert commander_cards[0].name == "Combo Commander"
    assert all(card.name != "Combo Commander" for card in deck)
    assert len(deck) == 8


def test_partner_commanders_are_both_excluded_from_shuffled_sim_deck():
    cards = [
        {"qty": 1, "name": "Partner A", "section": "commander", "tags": ["#CommanderSynergy"], "mana_value": 2},
        {"qty": 1, "name": "Partner B", "section": "commander", "tags": ["#CommanderSynergy"], "mana_value": 3},
        {"qty": 1, "name": "Land A", "section": "deck", "tags": ["#Land"], "mana_value": 0},
        {"qty": 97, "name": "Filler", "section": "deck", "tags": ["#Setup"], "mana_value": 1},
    ]
    deck, commander_cards = _build_sim_deck(cards, ["Partner A", "Partner B"])

    assert sorted(card.name for card in commander_cards) == ["Partner A", "Partner B"]
    assert all(card.name not in {"Partner A", "Partner B"} for card in deck)


def test_python_combo_win_requires_live_matched_variant():
    cards = _combo_shell_cards()
    matched_variant = [{"variant_id": "v1", "cards": ["Piece One", "Piece Two", "Piece Three"]}]

    live = run_python(
        cards=cards,
        commander="Combo Commander",
        runs=1,
        turn_limit=4,
        policy="optimized",
        multiplayer=True,
        threat_model=False,
        seed=42,
        primary_wincons=["Combo"],
        color_identity_size=1,
        combo_variants=matched_variant,
        combo_source_live=True,
    )["summary"]
    blocked = run_python(
        cards=cards,
        commander="Combo Commander",
        runs=1,
        turn_limit=4,
        policy="optimized",
        multiplayer=True,
        threat_model=False,
        seed=42,
        primary_wincons=["Combo"],
        color_identity_size=1,
        combo_variants=[],
        combo_source_live=True,
    )["summary"]

    assert live["win_metrics"]["most_common_wincon"] == "Combo"
    assert live["fastest_wins"][0]["win_reason"].startswith("All required cards for the CommanderSpellbook combo are live")
    assert blocked["win_metrics"]["p_win_by_turn_limit"] == 0.0
    assert blocked["fastest_wins"] == []


def test_vectorized_combo_win_requires_live_matched_variant():
    cards = _combo_shell_cards()
    matched_variant = [{"variant_id": "v1", "cards": ["Piece One", "Piece Two", "Piece Three"]}]

    live = run_vectorized(
        cards=cards,
        commander="Combo Commander",
        runs=1,
        turn_limit=4,
        policy="optimized",
        multiplayer=True,
        threat_model=False,
        seed=42,
        primary_wincons=["Combo"],
        color_identity_size=1,
        combo_variants=matched_variant,
        combo_source_live=True,
        batch_size=64,
    )["summary"]
    blocked = run_vectorized(
        cards=cards,
        commander="Combo Commander",
        runs=1,
        turn_limit=4,
        policy="optimized",
        multiplayer=True,
        threat_model=False,
        seed=42,
        primary_wincons=["Combo"],
        color_identity_size=1,
        combo_variants=[],
        combo_source_live=True,
        batch_size=64,
    )["summary"]

    assert live["win_metrics"]["most_common_wincon"] == "Combo"
    assert live["fastest_wins"][0]["win_reason"].startswith("All required cards for the CommanderSpellbook combo are live")
    assert blocked["win_metrics"]["p_win_by_turn_limit"] == 0.0
    assert blocked["fastest_wins"] == []


def test_combat_and_commander_damage_use_power_and_modifiers():
    combat_cards = _combat_shell_cards()
    voltron_cards = _voltron_shell_cards()

    py_combat = run_python(
        cards=combat_cards,
        commander=None,
        runs=1,
        turn_limit=5,
        policy="optimized",
        multiplayer=True,
        threat_model=False,
        seed=42,
        primary_wincons=["Combat"],
        color_identity_size=1,
    )["summary"]
    py_voltron = run_python(
        cards=voltron_cards,
        commander="Voltron Commander",
        runs=1,
        turn_limit=6,
        policy="optimized",
        multiplayer=True,
        threat_model=False,
        seed=42,
        primary_wincons=["Commander Damage"],
        color_identity_size=1,
    )["summary"]

    # The rewritten multiplayer evaluator only counts deterministic full-table kills as hard wins.
    # These fixtures should still register meaningful pressure and commander-damage accumulation
    # without being misreported as automatic multiplayer wins.
    assert py_combat["win_metrics"]["most_common_wincon"] is None
    assert py_combat["model_win_rate"] > 0 or py_combat["dominant_rate"] > 0

    assert py_voltron["win_metrics"]["most_common_wincon"] is None
    assert any(
        damage > 0
        for row in py_voltron.get("reference_trace", {}).get("commander_damage_by_slot", [])
        for damage in row
    )
