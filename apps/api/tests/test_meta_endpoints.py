from fastapi.testclient import TestClient

from app.main import app


def test_meta_integrations_endpoint():
    client = TestClient(app)
    res = client.get("/api/meta/integrations")
    assert res.status_code == 200
    payload = res.json()
    assert "integrations" in payload
    assert any(x.get("key") == "scryfall" for x in payload["integrations"])


def test_tags_taxonomy_endpoint():
    client = TestClient(app)
    res = client.get("/api/tags/taxonomy")
    assert res.status_code == 200
    payload = res.json()
    assert "groups" in payload
    assert "parent_relations" in payload
    assert "#Ramp" in payload["groups"]["core_function"]
    assert payload["parent_relations"]["#FastMana"] == "#Ramp"


def test_health_ready_endpoint_exists():
    client = TestClient(app)
    res = client.get("/health/ready")
    assert res.status_code in {200, 503}
    payload = res.json()
    assert "checks" in payload
    assert "database" in payload["checks"]
    assert "redis" in payload["checks"]


def test_runtime_meta_endpoint_exists():
    client = TestClient(app)
    res = client.get("/api/meta/runtime")
    assert res.status_code == 200
    payload = res.json()
    assert "queue_depth" in payload
    assert "workers" in payload
    assert "simulation_backend" in payload
    assert "vectorized_available" in payload["simulation_backend"]
