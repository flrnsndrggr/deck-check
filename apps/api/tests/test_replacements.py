from app.schemas.deck import CardEntry
from app.services.replacements import strictly_better_replacements


def test_strictly_better_excludes_existing_and_respects_budget(monkeypatch):
    cards = [
        CardEntry(qty=1, name="Commander", section="commander", tags=["#Engine"]),
        CardEntry(qty=1, name="Arcane Signet", section="deck", tags=["#Ramp"]),
    ]

    class FakeSvc:
        def get_cards_by_name(self, names):
            out = {}
            for n in names:
                if n == "Commander":
                    out[n] = {"color_identity": ["W", "U"], "cmc": 4}
                elif n == "Arcane Signet":
                    out[n] = {"cmc": 2, "edhrec_rank": 200, "type_line": "Artifact", "oracle_text": "{T}: Add one mana of any color."}
            return out

        def search_candidates(self, query, ci, limit=16):
            return [
                {"name": "Arcane Signet", "cmc": 2, "edhrec_rank": 50, "type_line": "Artifact", "oracle_text": "{T}: Add one mana of any color.", "prices": {"usd": "1.0"}, "color_identity": []},
                {"name": "Mox Amber", "cmc": 0, "edhrec_rank": 40, "type_line": "Artifact", "oracle_text": "{T}: Add one mana of any color among legendary creatures.", "prices": {"usd": "35.0"}, "color_identity": []},
                {"name": "Mind Stone", "cmc": 2, "edhrec_rank": 80, "type_line": "Artifact", "oracle_text": "{T}: Add {C}.", "prices": {"usd": "1.0"}, "color_identity": []},
            ]

        def card_display(self, card):
            return {"scryfall_uri": "https://example.com", "cardmarket_url": "https://example.com/cm"}

    monkeypatch.setattr("app.services.replacements.CardDataService", FakeSvc)

    out = strictly_better_replacements(cards, "Arcane Signet", commander="Commander", budget_max_usd=5)
    names = [x["card"] for x in out["options"]]
    assert "Arcane Signet" not in names
    assert "Mox Amber" not in names
    assert "Mind Stone" not in names


def test_strictly_better_prefers_same_ramp_family_and_efficiency(monkeypatch):
    cards = [
        CardEntry(qty=1, name="Commander", section="commander", tags=["#Engine"]),
        CardEntry(qty=1, name="Hedron Archive", section="deck", tags=["#Ramp", "#Draw", "#Rock"]),
    ]

    class FakeSvc:
        def get_cards_by_name(self, names):
            out = {}
            for n in names:
                if n == "Commander":
                    out[n] = {"color_identity": [], "cmc": 4}
                elif n == "Hedron Archive":
                    out[n] = {
                        "cmc": 4,
                        "edhrec_rank": 800,
                        "type_line": "Artifact",
                        "oracle_text": "{T}: Add {C}{C}.",
                        "produced_mana": ["C"],
                    }
            return out

        def search_candidates(self, query, ci, limit=24):
            return [
                {
                    "name": "Sol Ring",
                    "cmc": 1,
                    "edhrec_rank": 1,
                    "type_line": "Artifact",
                    "oracle_text": "{T}: Add {C}{C}.",
                    "produced_mana": ["C"],
                    "prices": {"usd": "1.0"},
                    "color_identity": [],
                },
                {
                    "name": "Temple of the False God",
                    "cmc": 0,
                    "edhrec_rank": 50,
                    "type_line": "Land",
                    "oracle_text": "{T}: Add {C}{C}. Activate only if you control five or more lands.",
                    "produced_mana": ["C"],
                    "prices": {"usd": "0.2"},
                    "color_identity": [],
                },
            ]

        def card_display(self, card):
            return {"scryfall_uri": "https://example.com", "cardmarket_url": "https://example.com/cm"}

    monkeypatch.setattr("app.services.replacements.CardDataService", FakeSvc)

    out = strictly_better_replacements(cards, "Hedron Archive", commander="Commander", budget_max_usd=5)
    names = [x["card"] for x in out["options"]]
    assert names == ["Sol Ring"]
    assert any("Comes down earlier" in reason for reason in out["options"][0]["reasons"])


def test_strictly_better_does_not_downgrade_colored_rock_to_colorless(monkeypatch):
    cards = [
        CardEntry(qty=1, name="Commander", section="commander", tags=["#Engine"]),
        CardEntry(qty=1, name="Heraldic Banner", section="deck", tags=["#Ramp", "#Rock", "#Payoff"]),
    ]

    class FakeSvc:
        def get_cards_by_name(self, names):
            out = {}
            for n in names:
                if n == "Commander":
                    out[n] = {"color_identity": ["W"], "cmc": 3}
                elif n == "Heraldic Banner":
                    out[n] = {
                        "cmc": 3,
                        "edhrec_rank": 837,
                        "type_line": "Artifact",
                        "oracle_text": "As this artifact enters, choose a color. Creatures you control of the chosen color get +1/+0.\n{T}: Add one mana of the chosen color.",
                        "prices": {"usd": "0.2"},
                    }
            return out

        def search_candidates(self, query, ci, limit=24):
            return [
                {
                    "name": "Sol Ring",
                    "cmc": 1,
                    "edhrec_rank": 1,
                    "type_line": "Artifact",
                    "oracle_text": "{T}: Add {C}{C}.",
                    "produced_mana": ["C"],
                    "prices": {"usd": "1.0"},
                    "color_identity": [],
                },
                {
                    "name": "Marble Diamond",
                    "cmc": 2,
                    "edhrec_rank": 600,
                    "type_line": "Artifact",
                    "oracle_text": "Marble Diamond enters tapped.\n{T}: Add {W}.",
                    "produced_mana": ["W"],
                    "prices": {"usd": "0.3"},
                    "color_identity": [],
                },
                {
                    "name": "Temple of the False God",
                    "cmc": 0,
                    "edhrec_rank": 69,
                    "type_line": "Land",
                    "oracle_text": "{T}: Add {C}{C}. Activate only if you control five or more lands.",
                    "produced_mana": ["C"],
                    "prices": {"usd": "0.3"},
                    "color_identity": [],
                },
            ]

        def card_display(self, card):
            return {"scryfall_uri": "https://example.com", "cardmarket_url": "https://example.com/cm"}

    monkeypatch.setattr("app.services.replacements.CardDataService", FakeSvc)

    out = strictly_better_replacements(cards, "Heraldic Banner", commander="Commander", budget_max_usd=5)
    names = [x["card"] for x in out["options"]]
    assert "Temple of the False God" not in names
    assert "Sol Ring" not in names
    assert names == ["Marble Diamond"]
