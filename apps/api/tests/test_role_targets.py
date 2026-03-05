from __future__ import annotations

from app.schemas.deck import CardEntry
from app.services.analyzer import analyze


def _run(cards, sim_summary, bracket=3):
    return analyze(
        cards=cards,
        sim_summary=sim_summary,
        bracket_report={"bracket": bracket, "violations": []},
        template="balanced",
        commander_ci="",
        combo_intel={"combo_support_score": 0, "matched_variants": [], "near_miss_variants": []},
        commander=None,
        commander_colors=[],
    )


def test_role_breakdown_includes_adaptive_targets_and_cards_map():
    cards = [
        CardEntry(qty=1, name="A", section="deck", tags=["#Land"]),
        CardEntry(qty=1, name="B", section="deck", tags=["#Ramp", "#FastMana"]),
        CardEntry(qty=1, name="C", section="deck", tags=["#Draw", "#Engine"]),
        CardEntry(qty=1, name="D", section="deck", tags=["#Removal"]),
    ]
    sim_summary = {
        "milestones": {"p_mana4_t3": 0.52, "p_mana5_t4": 0.41},
        "failure_modes": {"no_action": 0.2},
        "win_metrics": {"p_win_by_turn_limit": 0.5, "most_common_wincon": "Combat"},
    }
    out = _run(cards, sim_summary)
    assert "role_targets" in out
    assert "#Ramp" in out["role_targets"]
    assert "role_target_model" in out
    assert out["role_target_model"]["primary_philosophy"]
    assert "role_cards_map" in out
    assert any(x["name"] == "B" for x in out["role_cards_map"]["#Ramp"])


def test_boardwipe_target_not_fixed_and_can_be_low_for_proactive_combo():
    cards = [
        CardEntry(qty=1, name=f"Combo{i}", section="deck", tags=["#Combo", "#Tutor", "#Protection", "#Wincon"])
        for i in range(12)
    ]
    sim_summary = {
        "milestones": {"p_mana4_t3": 0.64, "p_mana5_t4": 0.54},
        "failure_modes": {"no_action": 0.12},
        "win_metrics": {"p_win_by_turn_limit": 0.82, "most_common_wincon": "Combo"},
    }
    out = _run(cards, sim_summary, bracket=5)
    wipes = out["role_targets"]["#Boardwipe"]
    assert wipes["target"] <= 3
    assert "strategy-dependent" in wipes["reason"]

