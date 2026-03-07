from fastapi.testclient import TestClient

from app.main import app


def test_random_art_endpoint_returns_crop(monkeypatch):
    def fake_random_display(self, query, art_preference="clean"):
        assert "unique:art" in query
        assert art_preference == "clean"
        return {
            "name": "Banner Card",
            "art_crop": "https://img.example/banner-crop.jpg",
            "scryfall_uri": "https://scryfall.com/card/banner",
        }

    monkeypatch.setattr("app.api.routes.CardDataService.get_random_display", fake_random_display)
    client = TestClient(app)
    res = client.get("/api/cards/random-art")
    assert res.status_code == 200
    assert res.json() == {
        "name": "Banner Card",
        "art_crop": "https://img.example/banner-crop.jpg",
        "scryfall_uri": "https://scryfall.com/card/banner",
    }
