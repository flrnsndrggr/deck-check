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
                    out[n] = {"color_identity": [], "cmc": 4}
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
