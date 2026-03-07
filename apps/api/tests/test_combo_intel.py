from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.deck import CardEntry
from app.services.analyzer import _generate_deck_name, analyze
from app.services.commanderspellbook import ComboIntelService, _normalize_variant


class _FakeRedis:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self.store[key] = value


def test_normalize_variant_complete_and_near_miss():
    raw = {
        "id": 123,
        "identity": "UG",
        "description": "Infinite mana loop",
        "uses": [
            {"card": {"name": "Freed from the Real"}},
            {"card": {"name": "Kinnan, Bonder Prodigy"}},
        ],
    }
    deck_names = {"freed from the real", "kinnan, bonder prodigy"}
    row = _normalize_variant(raw, deck_names, commander="Kinnan, Bonder Prodigy")
    assert row["status"] == "complete"
    assert row["missing_count"] == 0
    assert row["card_coverage"] == 1.0

    near = _normalize_variant(raw, {"freed from the real"}, commander=None)
    assert near["status"] == "near_miss"
    assert near["missing_count"] == 1


def test_combo_service_cache_deterministic(monkeypatch):
    from app.services import commanderspellbook as csb

    monkeypatch.setattr(csb, "redis_conn", _FakeRedis())
    svc = ComboIntelService()

    fake_rows = [
        {
            "id": 10,
            "description": "Line A",
            "uses": [{"card": {"name": "A"}}, {"card": {"name": "B"}}],
        },
        {
            "id": 11,
            "description": "Line B",
            "uses": [{"card": {"name": "A"}}, {"card": {"name": "C"}}],
        },
    ]
    monkeypatch.setattr(svc, "_fetch_variants_for_cards", lambda cards, limit=200: fake_rows)

    first = svc.get_combo_intel(["A", "B"], commander="Cmdr")
    second = svc.get_combo_intel(["A", "B"], commander="Cmdr")
    assert first == second
    assert first["matched_variants"][0]["variant_id"] == "10"


def test_combo_service_keeps_full_complete_catalog(monkeypatch):
    from app.services import commanderspellbook as csb

    monkeypatch.setattr(csb, "redis_conn", _FakeRedis())
    svc = ComboIntelService()

    fake_rows = []
    for idx in range(12):
        fake_rows.append(
            {
                "id": idx + 1,
                "description": f"Line {idx + 1}",
                "uses": [{"card": {"name": "A"}}, {"card": {"name": f"B{idx + 1}"}}],
            }
        )

    monkeypatch.setattr(svc, "_fetch_variants_for_cards", lambda cards, limit=200: fake_rows)
    out = svc.get_combo_intel(["A"] + [f"B{i + 1}" for i in range(12)], commander="Cmdr")
    assert len(out["matched_variants"]) == 12


def test_combo_service_keeps_only_one_card_near_miss_lines(monkeypatch):
    from app.services import commanderspellbook as csb

    monkeypatch.setattr(csb, "redis_conn", _FakeRedis())
    svc = ComboIntelService()
    fake_rows = [
        {
            "id": 10,
            "description": "Complete line",
            "uses": [{"card": {"name": "A"}}, {"card": {"name": "B"}}],
        },
        {
            "id": 11,
            "description": "One card short",
            "uses": [{"card": {"name": "A"}}, {"card": {"name": "C"}}],
        },
        {
            "id": 12,
            "description": "Two cards short",
            "uses": [{"card": {"name": "A"}}, {"card": {"name": "D"}}, {"card": {"name": "E"}}],
        },
    ]

    monkeypatch.setattr(svc, "_fetch_variants_for_cards", lambda cards, limit=200: fake_rows)
    out = svc.get_combo_intel(["A", "B"], commander="Cmdr")
    assert [v["variant_id"] for v in out["matched_variants"]] == ["10"]
    assert [v["variant_id"] for v in out["near_miss_variants"]] == ["11"]


def test_combo_service_filters_one_card_away_lines_by_color_identity(monkeypatch):
    from app.services import commanderspellbook as csb

    monkeypatch.setattr(csb, "redis_conn", _FakeRedis())
    svc = ComboIntelService()
    fake_rows = [
        {
            "id": 21,
            "identity": "B",
            "description": "Off-color near miss",
            "uses": [{"card": {"name": "A"}}, {"card": {"name": "Black Card"}}],
        },
        {
            "id": 22,
            "identity": "U",
            "description": "On-color near miss",
            "uses": [{"card": {"name": "A"}}, {"card": {"name": "Blue Card"}}],
        },
    ]
    monkeypatch.setattr(svc, "_fetch_variants_for_cards", lambda cards, limit=200: fake_rows)

    out = svc.get_combo_intel(["A"], commander="Cmdr", deck_colors=["U"])
    assert [v["variant_id"] for v in out["near_miss_variants"]] == ["22"]


def test_analyzer_includes_combo_intel(monkeypatch):
    cards = [
        CardEntry(qty=1, name="Card A", section="deck", tags=["#Combo", "#Engine"]),
        CardEntry(qty=1, name="Card B", section="deck", tags=["#Tutor"]),
    ]
    combo_intel = {
        "source": "commanderspellbook",
        "fetched_at": "2026-03-05T00:00:00+00:00",
        "source_hash": "x",
        "combo_support_score": 72.0,
        "matched_variants": [
            {
                "variant_id": "v-1",
                "identity": "U",
                "recipe": "",
                "cards": ["Card A", "Card B"],
                "present_cards": ["Card A", "Card B"],
                "missing_cards": [],
                "missing_count": 0,
                "card_coverage": 1.0,
                "score": 0.9,
                "status": "complete",
                "source_url": "https://commanderspellbook.com/combo/v-1",
            }
        ],
        "near_miss_variants": [],
        "warnings": [],
    }
    monkeypatch.setattr("app.services.analyzer.suggest_adds", lambda *args, **kwargs: [])
    out = analyze(
        cards=cards,
        sim_summary={"milestones": {"p_mana4_t3": 0.6, "p_mana5_t4": 0.45}, "failure_modes": {}},
        bracket_report={"bracket": 3, "violations": []},
        template="balanced",
        commander_ci="UB",
        combo_intel=combo_intel,
        commander="Cmdr",
    )
    assert out["combo_intel"]["combo_support_score"] == 72.0
    assert out["intent_summary"]["primary_plan"] == "Combo Assembly"
    assert out["deck_name"]
    assert "Cmdr" in out["deck_name"]


def test_combo_intel_endpoint(monkeypatch):
    payload = {
        "source": "commanderspellbook",
        "fetched_at": "2026-03-05T00:00:00+00:00",
        "source_hash": "abc",
        "combo_support_score": 25.0,
        "matched_variants": [],
        "near_miss_variants": [],
        "warnings": [],
    }
    monkeypatch.setattr(ComboIntelService, "get_combo_intel", lambda self, cards, commander=None: payload)
    client = TestClient(app)
    res = client.post("/api/combos/intel", json={"cards": ["Sol Ring"], "commander": "Urza"})
    assert res.status_code == 200
    assert res.json()["source"] == "commanderspellbook"


def test_deck_name_generator_prioritizes_dominant_subtype_theme():
    cards = [CardEntry(qty=1, name=f"Bird {i}", section="deck", tags=["#CommanderSynergy"]) for i in range(1, 7)]
    deck_name = _generate_deck_name(
        cards=cards,
        commander="Soraya the Falconer",
        intent={"primary_plan": "Value Midrange", "kill_vectors": ["Combat"]},
        combo_intel={"matched_variants": []},
        bracket=2,
        importance=[],
        type_profile={
            "dominant_creature_subtype": {"name": "Bird", "count": 6, "share": 1.0},
            "deck_theme_tags": ["#BirdTypal"],
            "primary_deck_theme_tag": "#BirdTypal",
        },
    )
    assert "Bird" in deck_name
