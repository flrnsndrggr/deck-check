from __future__ import annotations

from app.services.guides import generate_guides


def test_play_guide_is_primer_style_with_examples_and_matchups():
    analyze = {
        "intent_summary": {
            "primary_plan": "Combo Assembly",
            "secondary_plan": "Value Engine Backup",
            "kill_vectors": ["Combo", "Combat"],
            "confidence": 0.82,
            "key_support_cards": ["Sol Ring", "Arcane Signet", "Mystic Remora"],
            "key_engine_cards": ["Rhystic Study", "The Peregrine Dynamo"],
            "main_wincon_cards": ["Aetherflux Reservoir", "Walking Ballista"],
            "key_interaction_cards": ["Warping Wail", "All Is Dust"],
            "required_resources": ["Hit 4 mana by T3 (54.0%)", "Commander by median turn 3"],
        },
        "combo_intel": {
            "combo_support_score": 68,
            "matched_variants": [
                {
                    "variant_id": "1234",
                    "present_cards": ["Walking Ballista", "Basalt Monolith"],
                    "missing_cards": [],
                }
            ],
            "near_miss_variants": [
                {
                    "variant_id": "5678",
                    "present_cards": ["Sensei's Divining Top"],
                    "missing_cards": ["Aetherflux Reservoir"],
                }
            ],
        },
        "missing_roles": [],
        "actionable_actions": [{"title": "Increase #Draw density", "reason": "Low draw count"}],
        "cuts": [],
        "adds": [],
        "swaps": [],
        "bracket_report": {},
    }
    sim_summary = {
        "runs": 2000,
        "milestones": {"p_mana4_t3": 0.54, "p_mana5_t4": 0.42, "median_commander_cast_turn": 3},
        "failure_modes": {"mana_screw": 0.2, "no_action": 0.24, "flood": 0.08},
        "win_metrics": {"p_win_by_turn_limit": 0.61, "median_win_turn": 6, "most_common_wincon": "Combo"},
        "graph_payloads": {"dead_cards_top": [{"card": "Ulamog, the Ceaseless Hunger"}]},
    }

    out = generate_guides(analyze=analyze, sim_summary=sim_summary)
    primer = out["play_guide_md"]
    rule0 = out["rule0_brief_md"]

    assert "# COMMANDER PRIMER" in primer
    assert "## 8. Pod Archetype Matchup Plans" in primer
    assert "## 11. Pregame Pilot Checklist" in primer
    assert "`Sol Ring`" in primer
    assert "`Rhystic Study`" in primer
    assert "1234" in primer
    assert "5678" in primer
    assert "# RULE 0 BRIEF" in rule0
    assert "Rule 0 conversation" in rule0 or "What this deck is trying to do" in rule0
