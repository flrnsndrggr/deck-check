from app.schemas.deck import CardEntry
from app.services import analyzer as az


def test_suggest_adds_filters_offcolor_candidates(monkeypatch):
    def fake_search(self, query, color_identity, limit=10):
        return [
            {"name": "Blue Card", "color_identity": ["U"], "prices": {"usd": "1.0"}},
            {"name": "Colorless Card", "color_identity": [], "prices": {"usd": "1.0"}},
        ]

    monkeypatch.setattr("app.services.scryfall.CardDataService.search_candidates", fake_search)
    gaps = [{"role": "#Ramp", "have": 6, "target": 10, "missing": 4}]
    out = az.suggest_adds([], commander_ci="", gaps=gaps, bracket=3, budget_max_usd=None)
    assert any(x["card"] == "Colorless Card" for x in out)
    assert not any(x["card"] == "Blue Card" for x in out)


def test_analyze_returns_color_profile(monkeypatch):
    monkeypatch.setattr("app.services.analyzer.suggest_adds", lambda *args, **kwargs: [])
    cards = [
        CardEntry(qty=1, name="Commander", section="commander", tags=["#Engine"]),
        CardEntry(qty=99, name="Filler", section="deck", tags=["#Land"]),
    ]
    out = az.analyze(
        cards=cards,
        sim_summary={"milestones": {"p_mana4_t3": 0.6, "p_mana5_t4": 0.5}, "failure_modes": {}},
        bracket_report={"bracket": 3, "violations": []},
        template="balanced",
        commander_ci="",
        commander="Commander",
        commander_colors=[],
    )
    assert out["color_profile"]["label"] == "Colorless"
    assert out["color_profile"]["recommendations_constrained"] is True


def test_analyze_never_recommends_existing_cards(monkeypatch):
    # Force suggestion list to include an existing deck card plus one new card.
    monkeypatch.setattr(
        "app.services.analyzer.suggest_adds",
        lambda *args, **kwargs: [
            {"card": "In Deck", "fills": "#Ramp", "why": "x", "is_game_changer": False},
            {"card": "New Card", "fills": "#Ramp", "why": "x", "is_game_changer": False},
        ],
    )
    cards = [
        CardEntry(qty=1, name="Commander", section="commander", tags=["#Engine"]),
        CardEntry(qty=1, name="In Deck", section="deck", tags=["#Ramp"]),
    ]
    out = az.analyze(
        cards=cards,
        sim_summary={"milestones": {"p_mana4_t3": 0.5, "p_mana5_t4": 0.4}, "failure_modes": {}},
        bracket_report={"bracket": 3, "violations": []},
        template="balanced",
        commander_ci="",
        commander="Commander",
        commander_colors=[],
    )
    add_names = {a["card"] for a in out["adds"]}
    assert "In Deck" not in add_names
    assert "New Card" in add_names


def test_combo_missing_piece_not_added_if_already_in_deck(monkeypatch):
    monkeypatch.setattr("app.services.analyzer.suggest_adds", lambda *args, **kwargs: [])
    cards = [
        CardEntry(qty=1, name="Commander", section="commander", tags=["#Engine"]),
        CardEntry(qty=1, name="Combo Piece A", section="deck", tags=["#Combo"]),
    ]
    combo_intel = {
        "matched_variants": [],
        "near_miss_variants": [
            {"variant_id": "v1", "missing_cards": ["Combo Piece A"]},
        ],
    }
    out = az.analyze(
        cards=cards,
        sim_summary={"milestones": {"p_mana4_t3": 0.5, "p_mana5_t4": 0.4}, "failure_modes": {}},
        bracket_report={"bracket": 3, "violations": []},
        template="balanced",
        commander_ci="",
        commander="Commander",
        commander_colors=[],
        combo_intel=combo_intel,
    )
    assert not any(a.get("card") == "Combo Piece A" for a in out["adds"])
