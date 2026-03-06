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


def test_card_display_prefers_non_ub_printing(monkeypatch):
    svc = CardDataService(db_path=":memory:")

    class _Resp:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url, params=None):
            assert url == "https://api.scryfall.com/cards/search/prints"
            return _Resp(
                200,
                {
                    "data": [
                        {
                            "name": "Sol Ring",
                            "set_type": "universes_beyond",
                            "games": ["paper"],
                            "released_at": "2025-01-01",
                            "image_uris": {"small": "ub-s", "normal": "ub-n", "art_crop": "ub-a"},
                            "scryfall_uri": "https://scryfall.com/ub",
                        },
                        {
                            "name": "Sol Ring",
                            "set_type": "commander",
                            "games": ["paper"],
                            "released_at": "2024-01-01",
                            "image_uris": {"small": "main-s", "normal": "main-n", "art_crop": "main-a"},
                            "scryfall_uri": "https://scryfall.com/main",
                            "prices": {"usd": "1.00"},
                        },
                    ],
                    "has_more": False,
                },
            )

    monkeypatch.setattr("app.services.scryfall.httpx.Client", _Client)
    out = svc.card_display(
        {
            "name": "Sol Ring",
            "oracle_id": "oid-sol-ring",
            "set_type": "universes_beyond",
            "prints_search_uri": "https://api.scryfall.com/cards/search/prints",
            "image_uris": {"small": "ub-s", "normal": "ub-n", "art_crop": "ub-a"},
            "scryfall_uri": "https://scryfall.com/ub",
        }
    )
    assert out["normal"] == "main-n"
    assert out["scryfall_uri"] == "https://scryfall.com/main"
    assert out["prices"]["usd"] == "1.00"


def test_card_display_hides_ub_only_printing(monkeypatch):
    svc = CardDataService(db_path=":memory:")

    class _Resp:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url, params=None):
            return _Resp(
                200,
                {
                    "data": [
                        {
                            "name": "Lightning Greaves",
                            "set_type": "universes_beyond",
                            "games": ["paper"],
                            "released_at": "2025-01-01",
                            "image_uris": {"small": "ub-s", "normal": "ub-n", "art_crop": "ub-a"},
                            "scryfall_uri": "https://scryfall.com/ub-only",
                        }
                    ],
                    "has_more": False,
                },
            )

    monkeypatch.setattr("app.services.scryfall.httpx.Client", _Client)
    out = svc.card_display(
        {
            "name": "Lightning Greaves",
            "oracle_id": "oid-greaves",
            "set_type": "universes_beyond",
            "prints_search_uri": "https://api.scryfall.com/cards/search/prints",
            "image_uris": {"small": "ub-s", "normal": "ub-n", "art_crop": "ub-a"},
            "scryfall_uri": "https://scryfall.com/ub-only",
        }
    )
    assert out["normal"] is None
    assert "https://scryfall.com/search?q=%21%22Lightning+Greaves%22" == out["scryfall_uri"]


def test_card_display_respects_art_preference(monkeypatch):
    svc = CardDataService(db_path=":memory:")

    def fake_candidates(self, card):
        return [
            {
                "name": "Counterspell",
                "set_type": "expansion",
                "games": ["paper"],
                "released_at": "1993-08-05",
                "frame": "1993",
                "border_color": "black",
                "full_art": False,
                "promo": False,
                "promo_types": [],
                "frame_effects": [],
                "image_uris": {"small": "og-s", "normal": "og-n", "art_crop": "og-a"},
                "scryfall_uri": "https://scryfall.com/og",
            },
            {
                "name": "Counterspell",
                "set_type": "masters",
                "games": ["paper"],
                "released_at": "2020-01-01",
                "frame": "2015",
                "border_color": "black",
                "full_art": False,
                "promo": False,
                "promo_types": [],
                "frame_effects": [],
                "image_uris": {"small": "clean-s", "normal": "clean-n", "art_crop": "clean-a"},
                "scryfall_uri": "https://scryfall.com/clean",
            },
            {
                "name": "Counterspell",
                "set_type": "promo",
                "games": ["paper"],
                "released_at": "2024-01-01",
                "frame": "2015",
                "border_color": "borderless",
                "full_art": True,
                "promo": True,
                "promo_types": ["showcase", "borderless"],
                "frame_effects": ["showcase"],
                "image_uris": {"small": "showcase-s", "normal": "showcase-n", "art_crop": "showcase-a"},
                "scryfall_uri": "https://scryfall.com/showcase",
            },
            {
                "name": "Counterspell",
                "set_type": "expansion",
                "games": ["paper"],
                "released_at": "2025-01-01",
                "frame": "2015",
                "border_color": "black",
                "full_art": False,
                "promo": False,
                "promo_types": [],
                "frame_effects": [],
                "image_uris": {"small": "newest-s", "normal": "newest-n", "art_crop": "newest-a"},
                "scryfall_uri": "https://scryfall.com/newest",
            },
        ]

    monkeypatch.setattr(CardDataService, "_get_print_candidates", fake_candidates)
    base = {"name": "Counterspell", "oracle_id": "oid-counterspell", "set_type": "expansion"}

    assert svc.card_display(base, art_preference="original")["normal"] == "og-n"
    assert svc.card_display(base, art_preference="classic")["normal"] == "og-n"
    assert svc.card_display(base, art_preference="clean")["normal"] == "newest-n"
    assert svc.card_display(base, art_preference="showcase")["normal"] == "showcase-n"
    assert svc.card_display(base, art_preference="newest")["normal"] == "newest-n"
