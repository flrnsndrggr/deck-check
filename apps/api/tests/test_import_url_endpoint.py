from fastapi.testclient import TestClient

from app.main import app


def test_import_url_endpoint_returns_structured_error():
    client = TestClient(app)
    res = client.post("/api/decks/import-url", json={"url": "https://example.com/decks/123"})
    assert res.status_code == 400
    body = res.json()
    assert isinstance(body.get("detail"), dict)
    assert body["detail"]["error_class"] == "unsupported_host"
    assert "guidance" in body["detail"]
