from __future__ import annotations

from app.schemas.deck import CardEntry
from app.services.analyzer import analyze


def test_goldfish_graph_blurbs_are_deck_specific():
    cards = [
        CardEntry(qty=1, name="Commander A", section="commander", tags=["#Engine"]),
        CardEntry(qty=1, name="Sol Ring", section="deck", tags=["#Ramp", "#FastMana"]),
        CardEntry(qty=1, name="Mystic Remora", section="deck", tags=["#Draw", "#Engine"]),
        CardEntry(qty=1, name="Swords to Plowshares", section="deck", tags=["#Removal"]),
        CardEntry(qty=1, name="Craterhoof Behemoth", section="deck", tags=["#Wincon", "#Payoff"]),
    ]
    sim_summary = {
        "runs": 1000,
        "turn_limit": 8,
        "milestones": {"p_mana4_t3": 0.45, "p_mana5_t4": 0.35},
        "failure_modes": {"mana_screw": 0.28, "no_action": 0.31, "flood": 0.07},
        "win_metrics": {"p_win_by_turn_limit": 0.4, "most_common_wincon": "Combat"},
        "graph_payloads": {},
    }
    out = analyze(
        cards=cards,
        sim_summary=sim_summary,
        bracket_report={"bracket": 3, "violations": []},
        template="balanced",
        commander_ci="W",
        combo_intel={"combo_support_score": 0, "matched_variants": [], "near_miss_variants": []},
        commander="Commander A",
        commander_colors=["W"],
        card_map={
            "Sol Ring": {"name": "Sol Ring", "type_line": "Artifact", "mana_cost": "{1}", "cmc": 1, "oracle_text": "{T}: Add {C}{C}.", "produced_mana": ["C"]},
            "Mystic Remora": {"name": "Mystic Remora", "type_line": "Enchantment", "mana_cost": "{U}", "cmc": 1, "produced_mana": []},
            "Swords to Plowshares": {"name": "Swords to Plowshares", "type_line": "Instant", "mana_cost": "{W}", "cmc": 1, "produced_mana": []},
            "Craterhoof Behemoth": {"name": "Craterhoof Behemoth", "type_line": "Creature", "mana_cost": "{5}{G}{G}{G}", "cmc": 8, "produced_mana": []},
        },
    )

    blurbs = out.get("graph_deck_blurbs", {})
    assert blurbs.get("plan_progress")
    assert blurbs.get("failure_rates")
    assert blurbs.get("wincon_outcomes")
    assert blurbs.get("uncertainty")
    joined = " ".join([blurbs["plan_progress"], blurbs["failure_rates"], blurbs["wincon_outcomes"], blurbs["uncertainty"]])
    assert any(name in joined for name in ["Sol Ring", "Mystic Remora", "Swords to Plowshares", "Craterhoof Behemoth"])
