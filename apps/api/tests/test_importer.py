import pytest

from app.services.importer import (
    UrlImportError,
    decklist_from_archidekt_payload,
    decklist_from_moxfield_payload,
    extract_archidekt_deck_id,
    extract_moxfield_deck_id,
    import_decklist_from_url,
)


def test_extract_moxfield_deck_id():
    assert extract_moxfield_deck_id("https://www.moxfield.com/decks/abc123") == "abc123"
    assert extract_moxfield_deck_id("https://moxfield.com/decks/xyz987?foo=1") == "xyz987"
    assert extract_moxfield_deck_id("https://example.com/decks/abc123") is None


def test_extract_archidekt_deck_id():
    assert extract_archidekt_deck_id("https://archidekt.com/decks/123456/my-deck") == "123456"
    assert extract_archidekt_deck_id("https://example.com/decks/123456") is None


def test_decklist_from_payload_boards_shape():
    payload = {
        "boards": {
            "commanders": {
                "Atraxa, Praetors' Voice": {
                    "quantity": 1,
                    "card": {"name": "Atraxa, Praetors' Voice"},
                }
            },
            "mainboard": {
                "Sol Ring": {"quantity": 1, "card": {"name": "Sol Ring"}},
                "Arcane Signet": {"quantity": 1, "card": {"name": "Arcane Signet"}},
            },
            "companions": {
                "Jegantha, the Wellspring": {
                    "quantity": 1,
                    "card": {"name": "Jegantha, the Wellspring"},
                }
            },
        }
    }
    text = decklist_from_moxfield_payload(payload)
    assert "Commander" in text
    assert "1 Atraxa, Praetors' Voice" in text
    assert "Deck" in text
    assert "1 Sol Ring" in text
    assert "Companion" in text


def test_decklist_from_payload_flat_shape():
    payload = {
        "commanders": {"The Ur-Dragon": {"qty": 1}},
        "deck": {"Dragon's Hoard": 1, "Sol Ring": 1},
        "sideboard": [{"name": "Swords to Plowshares", "quantity": 1}],
    }
    text = decklist_from_moxfield_payload(payload)
    assert "1 The Ur-Dragon" in text
    assert "1 Dragon's Hoard" in text
    assert "1 Swords to Plowshares" in text


def test_archidekt_payload_parse():
    payload = {
        "cards": [
            {"quantity": 1, "categories": ["Commander"], "card": {"name": "Atraxa, Praetors' Voice"}},
            {"quantity": 1, "categories": [], "card": {"name": "Sol Ring"}},
            {"quantity": 1, "categories": ["Sideboard"], "card": {"name": "Swan Song"}},
        ]
    }
    out = decklist_from_archidekt_payload(payload)
    assert "Commander" in out
    assert "Deck" in out
    assert "Sideboard" in out


def test_import_url_unsupported_host():
    with pytest.raises(UrlImportError) as exc:
        import_decklist_from_url("https://example.com/decks/123")
    assert exc.value.error_class == "unsupported_host"


def test_import_url_moxfield_bot_blocked(monkeypatch):
    class FakeResp:
        def __init__(self, status_code: int, json_payload=None, text: str = ""):
            self.status_code = status_code
            self._json_payload = json_payload
            self.text = text

        def json(self):
            if self._json_payload is None:
                raise ValueError("no json")
            return self._json_payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"http {self.status_code}")

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url: str):
            # Simulate Cloudflare-style block for API and HTML fallback
            if "api2.moxfield.com" in url:
                return FakeResp(403)
            if "moxfield.com/decks/" in url:
                return FakeResp(403)
            return FakeResp(404)

    monkeypatch.setattr("app.services.importer.httpx.Client", FakeClient)
    with pytest.raises(UrlImportError) as exc:
        import_decklist_from_url("https://www.moxfield.com/decks/abc123")
    assert exc.value.error_class == "bot_blocked"
