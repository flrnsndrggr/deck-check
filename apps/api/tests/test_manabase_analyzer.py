from __future__ import annotations

from app.schemas.deck import CardEntry
from app.services import analyzer as az


def _base_sim():
    return {
        "milestones": {"p_mana4_t3": 0.55, "p_mana5_t4": 0.44},
        "failure_modes": {"mana_screw": 0.2, "no_action": 0.2, "flood": 0.08},
        "win_metrics": {"p_win_by_turn_limit": 0.6, "most_common_wincon": "Combat"},
    }


def test_manabase_analysis_reports_pips_and_sources_for_multicolor(monkeypatch):
    monkeypatch.setattr("app.services.analyzer.suggest_adds", lambda *args, **kwargs: [])

    cards = [
        CardEntry(qty=1, name="Commander", section="commander", tags=["#Engine"]),
        CardEntry(qty=1, name="Counterspell", section="deck", tags=["#Counter"]),
        CardEntry(qty=1, name="Lightning Bolt", section="deck", tags=["#Removal"]),
        CardEntry(qty=1, name="Izzet Signet", section="deck", tags=["#Ramp", "#Rock"]),
        CardEntry(qty=1, name="Island", section="deck", tags=["#Land"]),
        CardEntry(qty=1, name="Mountain", section="deck", tags=["#Land"]),
    ]
    card_map = {
        "Counterspell": {"name": "Counterspell", "mana_cost": "{U}{U}", "cmc": 2, "type_line": "Instant", "produced_mana": []},
        "Lightning Bolt": {"name": "Lightning Bolt", "mana_cost": "{R}", "cmc": 1, "type_line": "Instant", "produced_mana": []},
        "Izzet Signet": {
            "name": "Izzet Signet",
            "mana_cost": "{2}",
            "cmc": 2,
            "type_line": "Artifact",
            "oracle_text": "{1}, {T}: Add {U}{R}.",
            "produced_mana": ["U", "R"],
        },
        "Island": {"name": "Island", "type_line": "Basic Land — Island", "produced_mana": ["U"], "oracle_text": "{T}: Add {U}."},
        "Mountain": {"name": "Mountain", "type_line": "Basic Land — Mountain", "produced_mana": ["R"], "oracle_text": "{T}: Add {R}."},
    }

    out = az.analyze(
        cards=cards,
        sim_summary=_base_sim(),
        bracket_report={"bracket": 3, "violations": []},
        template="balanced",
        commander_ci="UR",
        combo_intel={"combo_support_score": 0, "matched_variants": [], "near_miss_variants": []},
        commander="Commander",
        commander_colors=["U", "R"],
        card_map=card_map,
    )

    mb = out["manabase_analysis"]
    assert "rows" in mb
    rows = {r["color"]: r for r in mb["rows"]}
    assert "U" in rows and "R" in rows
    assert rows["U"]["pips"] > rows["R"]["pips"]
    assert rows["U"]["land_sources"] >= 1
    assert rows["R"]["land_sources"] >= 1
    assert "manabase_pip_distribution" in out["graph_payloads"]
    assert "manabase_balance_gap" in out["graph_payloads"]
    assert "curve_histogram" in out["graph_payloads"]
    assert out["manabase_analysis"]["summary"]["average_mana_value_without_lands"] > 0


def test_manabase_analysis_handles_colorless_identity(monkeypatch):
    monkeypatch.setattr("app.services.analyzer.suggest_adds", lambda *args, **kwargs: [])

    cards = [
        CardEntry(qty=1, name="Commander", section="commander", tags=["#Engine"]),
        CardEntry(qty=1, name="Thought-Knot Seer", section="deck", tags=["#Payoff"]),
        CardEntry(qty=2, name="Wastes", section="deck", tags=["#Land"]),
    ]
    card_map = {
        "Thought-Knot Seer": {"name": "Thought-Knot Seer", "mana_cost": "{3}{C}", "cmc": 4, "type_line": "Creature", "produced_mana": []},
        "Wastes": {"name": "Wastes", "type_line": "Basic Land — Wastes", "produced_mana": ["C"], "oracle_text": "{T}: Add {C}."},
    }

    out = az.analyze(
        cards=cards,
        sim_summary=_base_sim(),
        bracket_report={"bracket": 3, "violations": []},
        template="balanced",
        commander_ci="",
        combo_intel={"combo_support_score": 0, "matched_variants": [], "near_miss_variants": []},
        commander="Commander",
        commander_colors=[],
        card_map=card_map,
    )

    rows = out["manabase_analysis"]["rows"]
    assert len(rows) == 1
    assert rows[0]["color"] == "C"
    assert rows[0]["pips"] > 0
    assert rows[0]["land_sources"] >= 2
    curve = out["manabase_analysis"]["curve"]["histogram"]
    assert any(int(x["mana_value"]) == 4 for x in curve)
