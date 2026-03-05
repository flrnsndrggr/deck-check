from app.services.scryfall import CardDataService


def test_card_display_single_face():
    svc = CardDataService(db_path=":memory:")
    card = {
        "name": "Sol Ring",
        "image_uris": {"small": "s", "normal": "n", "art_crop": "a"},
        "purchase_uris": {"cardmarket": "https://example.com/cardmarket"},
        "scryfall_uri": "https://example.com/scryfall",
        "prices": {"usd": "1.23"},
    }
    out = svc.card_display(card)
    assert out["small"] == "s"
    assert out["normal"] == "n"
    assert out["cardmarket_url"] == "https://example.com/cardmarket"


def test_card_display_dfc_fallback():
    svc = CardDataService(db_path=":memory:")
    card = {
        "name": "Delver of Secrets",
        "image_uris": {},
        "card_faces": [
            {"name": "Delver of Secrets", "image_uris": {"small": "s1", "normal": "n1", "art_crop": "a1"}},
            {"name": "Insectile Aberration", "image_uris": {"small": "s2", "normal": "n2", "art_crop": "a2"}},
        ],
    }
    out = svc.card_display(card)
    assert out["normal"] == "n1"
    assert len(out["face_images"]) == 2
