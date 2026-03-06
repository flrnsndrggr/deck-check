from app.services.scryfall import CardDataService


def test_card_display_single_face():
    svc = CardDataService(db_path=":memory:")
    card = {
        "name": "Sol Ring",
        "image_uris": {"small": "s", "normal": "n", "art_crop": "a"},
        "scryfall_uri": "https://example.com/scryfall",
        "prices": {"usd": "1.23"},
    }
    out = svc.card_display(card)
    assert out["small"] == "s"
    assert out["normal"] == "n"
    assert (
        out["cardmarket_url"]
        == "https://www.cardmarket.com/en/Magic/Cards/Sol-Ring?sellerCountry=4&language=1&minCondition=3"
    )


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


def test_card_display_cardmarket_url_sanitizes_name():
    svc = CardDataService(db_path=":memory:")
    out = svc.card_display({"name": "Mox Diamond"})
    assert (
        out["cardmarket_url"]
        == "https://www.cardmarket.com/en/Magic/Cards/Mox-Diamond?sellerCountry=4&language=1&minCondition=3"
    )


def test_fetch_collection_by_name_falls_back_for_split_cards(monkeypatch):
    svc = CardDataService(db_path=":memory:")

    class _Resp:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError("http error")

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json):
            assert json == {"identifiers": [{"name": "Dusk // Dawn"}]}
            return _Resp(200, {"data": [], "not_found": [{"name": "Dusk // Dawn"}]})

        def get(self, url, params):
            assert params == {"exact": "Dusk // Dawn"}
            return _Resp(200, {"name": "Dusk // Dawn", "oracle_id": "oid-dusk"})

    monkeypatch.setattr("app.services.scryfall.httpx.Client", _Client)
    out = svc.fetch_collection_by_name(["Dusk // Dawn"])
    assert len(out) == 1
    assert out[0]["name"] == "Dusk // Dawn"
