from __future__ import annotations

from app.schemas.deck import CardEntry
from app.services import analyzer as az


def test_suggest_adds_can_mix_edhrec_with_heuristics(monkeypatch):
    monkeypatch.setattr("app.services.scryfall.CardDataService.search_candidates", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        "app.services.edhrec.EDHRecService.get_commander_cards",
        lambda self, commander, limit=120: {"cards": [{"name": "Brainstorm", "edhrec_score": 91.0}]},
    )
    monkeypatch.setattr(
        "app.services.scryfall.CardDataService.get_cards_by_name",
        lambda self, names: {
            "Brainstorm": {
                "name": "Brainstorm",
                "type_line": "Instant",
                "oracle_text": "Draw three cards, then put two cards from your hand on top of your library in any order.",
                "color_identity": ["U"],
                "prices": {"usd": "1.50"},
            }
        },
    )

    out = az.suggest_adds(
        cards=[],
        commander_ci="U",
        gaps=[{"role": "#Draw", "have": 3, "target": 10, "missing": 7}],
        bracket=3,
        budget_max_usd=10.0,
        commander="Talrand, Sky Summoner",
    )
    assert any(x["card"] == "Brainstorm" for x in out)
    row = next(x for x in out if x["card"] == "Brainstorm")
    assert row["fills"] == "#Draw"
    assert row["source"] == "edhrec+heuristic"


def test_analyze_filters_offcolor_recommendations_even_if_upstream_leaks(monkeypatch):
    monkeypatch.setattr(
        "app.services.analyzer.suggest_adds",
        lambda *args, **kwargs: [{"card": "White Card", "fills": "#Ramp", "why": "x", "source": "heuristic"}],
    )
    monkeypatch.setattr(
        "app.services.scryfall.CardDataService.get_cards_by_name",
        lambda self, names: {
            "White Card": {
                "name": "White Card",
                "type_line": "Sorcery",
                "oracle_text": "Add {W}.",
                "color_identity": ["W"],
                "prices": {"usd": "1.0"},
            }
        },
    )
    cards = [
        CardEntry(qty=1, name="Commander", section="commander", tags=["#Engine"]),
        CardEntry(qty=99, name="Wastes", section="deck", tags=["#Land"]),
    ]
    out = az.analyze(
        cards=cards,
        sim_summary={"milestones": {"p_mana4_t3": 0.5, "p_mana5_t4": 0.4}, "failure_modes": {}, "win_metrics": {}},
        bracket_report={"bracket": 3, "violations": []},
        template="balanced",
        commander_ci="",
        commander="Commander",
        commander_colors=[],
        combo_intel={"matched_variants": [], "near_miss_variants": [], "combo_support_score": 0},
    )
    assert not any(a.get("card") == "White Card" for a in out["adds"])


def test_combo_near_miss_add_obeys_budget_cap(monkeypatch):
    monkeypatch.setattr("app.services.analyzer.suggest_adds", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        "app.services.scryfall.CardDataService.get_cards_by_name",
        lambda self, names: {
            "Expensive Combo Piece": {
                "name": "Expensive Combo Piece",
                "type_line": "Artifact",
                "oracle_text": "Untap all permanents.",
                "color_identity": [],
                "prices": {"usd": "49.99"},
            }
        },
    )
    cards = [
        CardEntry(qty=1, name="Commander", section="commander", tags=["#Engine"]),
        CardEntry(qty=99, name="Wastes", section="deck", tags=["#Land"]),
    ]
    out = az.analyze(
        cards=cards,
        sim_summary={"milestones": {"p_mana4_t3": 0.5, "p_mana5_t4": 0.4}, "failure_modes": {}, "win_metrics": {}},
        bracket_report={"bracket": 3, "violations": []},
        template="balanced",
        commander_ci="",
        commander="Commander",
        commander_colors=[],
        combo_intel={
            "matched_variants": [],
            "near_miss_variants": [{"variant_id": "x", "missing_cards": ["Expensive Combo Piece"]}],
            "combo_support_score": 10,
        },
        budget_max_usd=10.0,
    )
    assert not any(a.get("card") == "Expensive Combo Piece" for a in out["adds"])


def test_analyze_adds_align_with_missing_roles(monkeypatch):
    monkeypatch.setattr(
        "app.services.analyzer._role_gap_list_from_model",
        lambda cards, role_model: [{"role": "#Ramp", "have": 2, "target": 10, "missing": 8}],
    )
    monkeypatch.setattr(
        "app.services.analyzer.suggest_adds",
        lambda *args, **kwargs: [
            {"card": "Ramp Card", "fills": "#Ramp", "why": "x", "source": "heuristic"},
            {"card": "Draw Card", "fills": "#Draw", "why": "x", "source": "heuristic"},
        ],
    )
    monkeypatch.setattr(
        "app.services.scryfall.CardDataService.get_cards_by_name",
        lambda self, names: {
            "Ramp Card": {
                "name": "Ramp Card",
                "type_line": "Artifact",
                "oracle_text": "Tap: Add {C}.",
                "color_identity": [],
                "prices": {"usd": "1.0"},
            },
            "Draw Card": {
                "name": "Draw Card",
                "type_line": "Sorcery",
                "oracle_text": "Draw two cards.",
                "color_identity": [],
                "prices": {"usd": "1.0"},
            },
        },
    )
    cards = [
        CardEntry(qty=1, name="Commander", section="commander", tags=["#Engine"]),
        CardEntry(qty=30, name="Wastes", section="deck", tags=["#Land"]),
    ]
    out = az.analyze(
        cards=cards,
        sim_summary={"milestones": {"p_mana4_t3": 0.3, "p_mana5_t4": 0.2}, "failure_modes": {}, "win_metrics": {}},
        bracket_report={"bracket": 3, "violations": []},
        template="balanced",
        commander_ci="",
        commander="Commander",
        commander_colors=[],
        combo_intel={"matched_variants": [], "near_miss_variants": [], "combo_support_score": 0},
    )
    fills = {a.get("fills") for a in out["adds"]}
    assert "#Ramp" in fills
    assert "#Draw" not in fills
