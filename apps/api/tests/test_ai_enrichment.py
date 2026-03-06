from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SIM_PATH = ROOT / "packages" / "sim"
if str(SIM_PATH) not in sys.path:
    sys.path.insert(0, str(SIM_PATH))

from app.db.base import Base
from app.db.session import SessionLocal, engine
import app.models as models_registry  # noqa: F401
import app.api.routes as routes
from app.services.ai_enrichment import AIEnrichmentService
import app.services.ai_enrichment as ai_mod
from app.schemas.deck import AnalyzeRequest, AnalyzeResponse, GuideRequest


class _FakeRedis:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self.store[key] = value

    def incr(self, key):
        value = int(self.store.get(key, 0)) + 1
        self.store[key] = value
        return value

    def expire(self, key, ttl):
        return True

    def incrbyfloat(self, key, amount):
        value = float(self.store.get(key, 0.0)) + float(amount)
        self.store[key] = value
        return value


class _FakeCardService:
    def get_cards_by_name(self, names):
        out = {}
        for name in names:
            out[name] = {
                "name": name,
                "oracle_id": f"oid-{name}",
                "oracle_text": "Whenever this attacks, draw a card.",
                "type_line": "Creature",
                "mana_cost": "{2}{W}",
                "color_identity": ["W"] if name != "Sol Ring" else [],
                "keywords": [],
            }
        return out


def _ensure_tables():
    Base.metadata.create_all(bind=engine)


def test_ai_enrichment_disabled_is_noop(monkeypatch):
    monkeypatch.setattr(ai_mod, "redis_conn", _FakeRedis())
    monkeypatch.setattr(ai_mod.settings, "ai_enabled", False)
    monkeypatch.setattr(ai_mod.settings, "openai_api_key", "")

    svc = AIEnrichmentService(None)
    analyze = {"intent_summary": {"primary_plan": "Combat"}, "graph_explanations": {"mana_percentiles": "base"}}
    out = svc.enrich_analysis(cards=[], commander=None, analysis=analyze, sim_summary={}, watchouts=[], card_map={})
    assert out is analyze
    assert out["graph_explanations"]["mana_percentiles"] == "base"


def test_provider_cooldown_skips_repeated_upstream_failures(monkeypatch):
    fake_redis = _FakeRedis()
    monkeypatch.setattr(ai_mod, "redis_conn", fake_redis)
    monkeypatch.setattr(ai_mod.settings, "ai_enabled", True)
    monkeypatch.setattr(ai_mod.settings, "openai_api_key", "test-key")

    svc = AIEnrichmentService(None)
    calls = {"count": 0}

    def fake_post(*args, **kwargs):
        calls["count"] += 1
        req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        resp = httpx.Response(429, request=req, text='{"error":{"code":"insufficient_quota"}}')
        raise httpx.HTTPStatusError("quota", request=req, response=resp)

    import httpx

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    prompt = {"x": 1}
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
    }
    first = svc._call_model_json("intent_summary", prompt, schema)
    second = svc._call_model_json("intent_summary", prompt, schema)
    assert first is None
    assert second is None
    assert calls["count"] == 1
    assert fake_redis.get("aienrich:provider:cooldown")


def test_invalid_generated_card_name_is_rejected(monkeypatch):
    monkeypatch.setattr(ai_mod, "redis_conn", _FakeRedis())
    monkeypatch.setattr(ai_mod.settings, "ai_enabled", True)
    monkeypatch.setattr(ai_mod.settings, "openai_api_key", "test-key")

    svc = AIEnrichmentService(None)
    monkeypatch.setattr(svc, "_call_model_json", lambda family, prompt, schema: {
        "parsed": {"sections": [{"key": "plan_narrative", "text": "Win with `Black Lotus`.", "citations": ["intent:primary_plan"], "mentioned_cards": ["Black Lotus"]}]},
        "usage": {},
        "request_json": {"family": family, "prompt_payload": prompt},
        "response_json": {"parsed": {}},
        "payload_hash": "x",
        "estimated_cost_usd": 0.0,
    })
    analysis = {
        "intent_summary": {"primary_plan": "Combat"},
        "graph_explanations": {},
        "graph_deck_blurbs": {},
        "combo_intel": {"matched_variants": []},
        "adds": [],
        "cuts": [],
        "swaps": [],
        "health_summary": {},
    }
    out = svc.enrich_analysis(
        cards=[{"qty": 1, "name": "Soraya the Falconer", "section": "commander"}],
        commander="Soraya the Falconer",
        analysis=analysis,
        sim_summary={"milestones": {}},
        watchouts=[],
        card_map={"Soraya the Falconer": {"oracle_text": "Flying"}},
    )
    assert "plan_narrative" not in out["intent_summary"]


def test_valid_hidden_ai_deck_name_overrides_fallback(monkeypatch):
    monkeypatch.setattr(ai_mod, "redis_conn", _FakeRedis())
    monkeypatch.setattr(ai_mod.settings, "ai_enabled", True)
    monkeypatch.setattr(ai_mod.settings, "openai_api_key", "test-key")

    svc = AIEnrichmentService(None)
    monkeypatch.setattr(svc, "_call_model_json", lambda family, prompt, schema: {
        "parsed": {
            "deck_name": "Dynamo Overclock",
            "citations": ["intent:primary_plan", "card:The Peregrine Dynamo"],
            "mentioned_cards": ["The Peregrine Dynamo"],
        },
        "usage": {},
        "request_json": {"family": family, "prompt_payload": prompt},
        "response_json": {"parsed": {}},
        "payload_hash": "deck-name-x",
        "estimated_cost_usd": 0.0,
    })
    analysis = {
        "deck_name": "Dynamo Engine",
        "intent_summary": {"primary_plan": "Combo Assembly"},
        "graph_explanations": {},
        "graph_deck_blurbs": {},
        "combo_intel": {"matched_variants": [], "near_miss_variants": []},
        "adds": [],
        "cuts": [],
        "swaps": [],
        "health_summary": {},
    }
    out = svc.enrich_analysis(
        cards=[{"qty": 1, "name": "The Peregrine Dynamo", "section": "commander"}],
        commander="The Peregrine Dynamo",
        analysis=analysis,
        sim_summary={"milestones": {}},
        watchouts=[],
        card_map={"The Peregrine Dynamo": {"oracle_id": "oid-dynamo", "oracle_text": "", "type_line": "Legendary Artifact Creature"}},
    )
    assert out["deck_name"] == "Dynamo Overclock"


def test_rules_watchout_enrichment_hides_empty_cards(monkeypatch):
    monkeypatch.setattr(ai_mod, "redis_conn", _FakeRedis())
    monkeypatch.setattr(ai_mod.settings, "ai_enabled", True)
    monkeypatch.setattr(ai_mod.settings, "openai_api_key", "test-key")

    svc = AIEnrichmentService(None)
    monkeypatch.setattr(svc, "card_service", _FakeCardService())
    monkeypatch.setattr(svc, "_call_model_json", lambda family, prompt, schema: {
        "parsed": {
            "items": [
                {
                    "card": "Gerrard's Hourglass Pendant",
                    "errata": [{"text": "The extra-turn replacement applies before the extra turn begins.", "citations": ["ruling:Gerrard's Hourglass Pendant:0"], "mentioned_cards": ["Gerrard's Hourglass Pendant"]}],
                    "notes": [],
                    "rules_information": [{"text": "Hold activation until you know which permanents actually went to your graveyard this turn.", "citations": ["flag:Gerrard's Hourglass Pendant:Replacement effect"], "mentioned_cards": ["Gerrard's Hourglass Pendant"]}],
                },
                {"card": "Soulcatcher", "errata": [], "notes": [], "rules_information": []},
            ]
        },
        "usage": {},
        "request_json": {"family": family, "prompt_payload": prompt},
        "response_json": {"parsed": {}},
        "payload_hash": "watchout-x",
        "estimated_cost_usd": 0.0,
    })
    watchouts = [
        {
            "card": "Gerrard's Hourglass Pendant",
            "complexity_flags": ["Replacement effect"],
            "rulings": [{"published_at": "2025-01-01", "comment": "Example ruling."}],
        },
        {
            "card": "Soulcatcher",
            "complexity_flags": ["Triggered timing"],
            "rulings": [],
        },
    ]
    out = svc.enrich_watchouts(cards=[], commander=None, watchouts=watchouts)
    assert len(out) == 1
    assert out[0]["card"] == "Gerrard's Hourglass Pendant"
    assert out[0]["errata"]
    assert out[0]["rules_information"]


def test_rules_watchout_enrichment_preserves_deterministic_sections_when_model_is_partial(monkeypatch):
    monkeypatch.setattr(ai_mod, "redis_conn", _FakeRedis())
    monkeypatch.setattr(ai_mod.settings, "ai_enabled", True)
    monkeypatch.setattr(ai_mod.settings, "openai_api_key", "test-key")

    svc = AIEnrichmentService(None)
    monkeypatch.setattr(svc, "card_service", _FakeCardService())
    monkeypatch.setattr(svc, "_call_model_json", lambda family, prompt, schema: {
        "parsed": {
            "items": [
                {
                    "card": "Gerrard's Hourglass Pendant",
                    "errata": [],
                    "notes": [
                        {
                            "text": "Hold activation until you know which permanents actually went to your graveyard this turn.",
                            "citations": ["flag:Gerrard's Hourglass Pendant:Replacement effect"],
                            "mentioned_cards": ["Gerrard's Hourglass Pendant"],
                        }
                    ],
                    "rules_information": [],
                }
            ]
        },
        "usage": {},
        "request_json": {"family": family, "prompt_payload": prompt},
        "response_json": {"parsed": {}},
        "payload_hash": "watchout-partial",
        "estimated_cost_usd": 0.0,
    })
    watchouts = [
        {
            "card": "Gerrard's Hourglass Pendant",
            "complexity_flags": ["Replacement effect"],
            "rulings": [{"published_at": "2025-01-01", "comment": "Example ruling."}],
            "errata": ["2025-01-01: Example ruling."],
            "notes": ["Base deterministic note."],
            "rules_information": ["Base deterministic rules info."],
        }
    ]
    out = svc.enrich_watchouts(cards=[], commander=None, watchouts=watchouts)
    assert out[0]["errata"] == ["2025-01-01: Example ruling."]
    assert "Base deterministic rules info." in out[0]["rules_information"]
    assert any("Hold activation" in note for note in out[0]["notes"])


def test_guide_enrichment_injects_hidden_overview(monkeypatch):
    monkeypatch.setattr(ai_mod, "redis_conn", _FakeRedis())
    monkeypatch.setattr(ai_mod.settings, "ai_enabled", True)
    monkeypatch.setattr(ai_mod.settings, "openai_api_key", "test-key")

    svc = AIEnrichmentService(None)
    monkeypatch.setattr(svc, "_call_model_json", lambda family, prompt, schema: {
        "parsed": {
            "optimization_overview": {"text": "Tighten the first three turns around `Sol Ring` and cheaper draw.", "citations": ["recommendation:add:0", "sim:p_mana4_t3"], "mentioned_cards": ["Sol Ring"]},
            "play_overview": {"text": "Mulligan for mana plus one engine, then protect `The Peregrine Dynamo` once it resolves.", "citations": ["intent:primary_plan", "card:The Peregrine Dynamo"], "mentioned_cards": ["The Peregrine Dynamo"]},
        },
        "usage": {},
        "request_json": {"family": family, "prompt_payload": prompt},
        "response_json": {"parsed": {}},
        "payload_hash": "guide-x",
        "estimated_cost_usd": 0.0,
    })
    monkeypatch.setattr(svc, "run_consistency_audit", lambda evidence, sections: {"status": "pass", "issues": []})

    guides = {"optimization_guide_md": "# OPTIMIZATION GUIDE\n\nBase text", "play_guide_md": "# COMMANDER PRIMER\n\nBase play text"}
    analyze = {
        "intent_summary": {"primary_plan": "Value", "commander": "The Peregrine Dynamo"},
        "combo_intel": {"matched_variants": []},
        "adds": [{"card": "Sol Ring", "fills": "#Ramp"}],
        "cuts": [],
        "swaps": [],
        "rules_watchouts": [],
    }
    sim_summary = {"milestones": {"p_mana4_t3": 0.55}, "win_metrics": {}, "failure_modes": {}, "runs": 2000}
    out = svc.enrich_guides(analyze=analyze, sim_summary=sim_summary, guides=guides)
    assert "## Optimization snapshot" in out["optimization_guide_md"]
    assert "## Pilot snapshot" in out["play_guide_md"]


def test_analyze_route_uses_hidden_enrichment(monkeypatch):
    _ensure_tables()
    monkeypatch.setattr(routes, "build_rules_watchouts", lambda cards, commander: [{"card": "Sol Ring", "complexity_flags": ["Triggered timing"], "rulings": []}])
    monkeypatch.setattr(routes, "validate_deck", lambda cards, commander, card_map, bracket: ([], [], {"bracket": 3, "violations": []}))

    class _RouteCardService:
        def get_cards_by_name(self, names):
            return {name: {"name": name, "color_identity": [], "oracle_text": "Whenever this attacks, draw a card.", "type_line": "Artifact", "oracle_id": f"oid-{name}"} for name in names}

    monkeypatch.setattr(routes, "CardDataService", lambda: _RouteCardService())
    monkeypatch.setattr(routes.ComboIntelService, "get_combo_intel", lambda self, cards, commander=None: {"matched_variants": [], "warnings": [], "combo_support_score": 0, "near_miss_variants": []})
    monkeypatch.setattr(routes, "analyze", lambda *args, **kwargs: {
        "intent_summary": {"primary_plan": "Combat"},
        "graph_explanations": {"mana_percentiles": "base"},
        "graph_deck_blurbs": {"mana_percentiles": "base blurb"},
        "adds": [],
        "cuts": [],
        "swaps": [],
        "combo_intel": {"matched_variants": [], "near_miss_variants": [], "warnings": []},
        "health_summary": {},
        "missing_roles": [],
        "bracket_report": {"bracket": 3, "violations": []},
        "rules_watchouts": [],
        "importance": [],
        "role_breakdown": {},
        "manabase_analysis": {},
        "systems_metrics": {},
        "tag_diagnostics": {},
        "color_profile": {},
        "compliant_alternatives": [],
        "actionable_actions": [],
        "role_targets": {},
        "role_target_model": {},
        "role_cards_map": {},
    })
    monkeypatch.setattr(routes.AIEnrichmentService, "enrich_analysis", lambda self, **kwargs: {**kwargs["analysis"], "intent_summary": {"primary_plan": "Combat", "plan_narrative": "Lean on `Sol Ring` to accelerate combat."}, "rules_watchouts": [{"card": "Sol Ring", "notes": ["Fast mana changes mulligan math."], "rulings": [], "complexity_flags": []}]})

    db = SessionLocal()
    try:
        body = routes.analyze_deck(
            AnalyzeRequest(
                cards=[{"qty": 1, "name": "Sol Ring", "section": "deck"}],
                commander="The Peregrine Dynamo",
                bracket=3,
                template="balanced",
                sim_summary={"milestones": {}, "failure_modes": {}, "win_metrics": {}, "runs": 50},
            ),
            db=db,
        )
    finally:
        db.close()
    assert body["intent_summary"]["plan_narrative"] == "Lean on `Sol Ring` to accelerate combat."
    assert body["rules_watchouts"][0]["notes"] == ["Fast mana changes mulligan math."]


def test_guides_route_keeps_public_contract(monkeypatch):
    _ensure_tables()
    monkeypatch.setattr(routes, "generate_guides", lambda analyze, sim_summary: {"optimization_guide_md": "# OPTIMIZATION GUIDE\n\nBase", "play_guide_md": "# COMMANDER PRIMER\n\nBase"})
    monkeypatch.setattr(routes.AIEnrichmentService, "enrich_guides", lambda self, analyze, sim_summary, guides: {**guides, "play_guide_md": guides["play_guide_md"] + "\n\n## Pilot snapshot\nHidden enrichment."})

    db = SessionLocal()
    try:
        res = routes.generate(
            GuideRequest(
                analyze=AnalyzeResponse(
                    role_breakdown={},
                    bracket_report={},
                    importance=[],
                    cuts=[],
                    adds=[],
                    swaps=[],
                    missing_roles=[],
                ),
                sim_summary={"runs": 10},
            ),
            db=db,
        )
    finally:
        db.close()
    assert "Pilot snapshot" in res.play_guide_md
