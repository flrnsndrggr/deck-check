from fastapi.testclient import TestClient

import app.api.routes as routes
from app.main import app
from app.schemas.deck import CardEntry
from app.services.winplans import enrich_sim_cards
from sim.engine import _build_sim_deck


def test_tag_route_returns_hydrated_mana_metadata(monkeypatch):
    monkeypatch.setattr(
        routes.CardDataService,
        "get_cards_by_name",
        lambda self, names: {
            "Gilded Lotus": {
                "name": "Gilded Lotus",
                "mana_cost": "{5}",
                "cmc": 5,
                "type_line": "Artifact",
                "oracle_text": "{T}: Add three mana of any one color.",
                "produced_mana": ["W", "U", "B", "R", "G"],
            }
        },
    )
    monkeypatch.setattr(routes.CardDataService, "get_display_by_names", lambda self, names, art_preference="clean": {})
    monkeypatch.setattr(routes, "_validate_deck_compat", lambda *args, **kwargs: ([], [], {"bracket": 3, "violations": []}))

    client = TestClient(app)
    res = client.post(
        "/api/decks/tag",
        json={
            "cards": [{"qty": 1, "name": "Gilded Lotus", "section": "deck"}],
            "global_tags": True,
            "art_preference": "clean",
        },
    )

    assert res.status_code == 200
    card = res.json()["cards"][0]
    assert card["mana_cost"] == "{5}"
    assert card["mana_value"] == 5.0


def test_tag_route_joins_multiface_mana_cost_when_top_level_missing(monkeypatch):
    monkeypatch.setattr(
        routes.CardDataService,
        "get_cards_by_name",
        lambda self, names: {
            "Response // Rescue": {
                "name": "Response // Rescue",
                "mana_cost": "",
                "cmc": 4,
                "type_line": "Instant // Instant",
                "oracle_text": "",
                "card_faces": [
                    {"name": "Response", "mana_cost": "{W}{W}", "oracle_text": ""},
                    {"name": "Rescue", "mana_cost": "{3}{W}", "oracle_text": ""},
                ],
                "produced_mana": [],
            }
        },
    )
    monkeypatch.setattr(routes.CardDataService, "get_display_by_names", lambda self, names, art_preference="clean": {})
    monkeypatch.setattr(routes, "_validate_deck_compat", lambda *args, **kwargs: ([], [], {"bracket": 3, "violations": []}))

    client = TestClient(app)
    res = client.post(
        "/api/decks/tag",
        json={
            "cards": [{"qty": 1, "name": "Response // Rescue", "section": "deck"}],
            "global_tags": True,
            "art_preference": "clean",
        },
    )

    assert res.status_code == 200
    card = res.json()["cards"][0]
    assert card["mana_cost"] == "{W}{W} // {3}{W}"


def test_enrich_sim_cards_includes_resolved_mana_metadata():
    cards = [CardEntry(qty=1, name="Gilded Lotus", section="deck", tags=["#Ramp"])]
    card_map = {
        "Gilded Lotus": {
            "name": "Gilded Lotus",
            "mana_cost": "{5}",
            "cmc": 5,
            "type_line": "Artifact",
            "oracle_text": "{T}: Add three mana of any one color.",
            "produced_mana": ["W", "U", "B", "R", "G"],
        }
    }

    out = enrich_sim_cards(cards, card_map, commander=None)

    assert out[0]["mana_cost"] == "{5}"
    assert out[0]["mana_value"] == 5.0


def test_build_sim_deck_uses_enriched_mana_value_instead_of_default_two():
    cards = [CardEntry(qty=1, name="Gilded Lotus", section="deck", tags=["#Ramp"])]
    card_map = {
        "Gilded Lotus": {
            "name": "Gilded Lotus",
            "mana_cost": "{5}",
            "cmc": 5,
            "type_line": "Artifact",
            "oracle_text": "{T}: Add three mana of any one color.",
            "produced_mana": ["W", "U", "B", "R", "G"],
        }
    }

    deck, _ = _build_sim_deck(enrich_sim_cards(cards, card_map, commander=None), None)

    assert deck[0].mana_value == 5.0
