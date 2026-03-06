from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Literal, Sequence

import httpx
from pydantic import BaseModel, Field
from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ai_enrichment_audit import AIEnrichmentAudit
from app.services.rules_index import search_rules
from app.services.scryfall import CardDataService
from app.workers.queue import redis_conn

OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
AI_RATE_LIMIT_PER_MINUTE = 24
DEFAULT_INPUT_COST_PER_1M = 1.0
DEFAULT_OUTPUT_COST_PER_1M = 4.0
MODEL_PRICING_PER_1M = {
    # Source: official OpenAI pricing. Keep this conservative for budget gating.
    # https://openai.com/api/pricing/
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-5-mini": (0.25, 2.00),
}
CARD_NAME_RE = re.compile(r"`([^`]+)`")
NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?%?\b")
class EnrichedText(BaseModel):
    text: str = ""
    citations: List[str] = Field(default_factory=list)
    mentioned_cards: List[str] = Field(default_factory=list)


class IntentSection(BaseModel):
    key: Literal[
        "plan_narrative",
        "backup_narrative",
        "engine_narrative",
        "interaction_narrative",
        "kill_vector_narrative",
    ]
    text: str = ""
    citations: List[str] = Field(default_factory=list)
    mentioned_cards: List[str] = Field(default_factory=list)


class IntentPayload(BaseModel):
    sections: List[IntentSection] = Field(default_factory=list)


class GraphItem(BaseModel):
    key: str
    kind: Literal["explanation", "blurb"]
    text: str = ""
    citations: List[str] = Field(default_factory=list)
    mentioned_cards: List[str] = Field(default_factory=list)


class GraphPayload(BaseModel):
    items: List[GraphItem] = Field(default_factory=list)


class WatchoutItem(BaseModel):
    card: str
    errata: List[EnrichedText] = Field(default_factory=list)
    notes: List[EnrichedText] = Field(default_factory=list)
    rules_information: List[EnrichedText] = Field(default_factory=list)


class WatchoutPayload(BaseModel):
    items: List[WatchoutItem] = Field(default_factory=list)


class GuidePayload(BaseModel):
    optimization_overview: EnrichedText = Field(default_factory=EnrichedText)
    play_overview: EnrichedText = Field(default_factory=EnrichedText)


class AuditIssue(BaseModel):
    section: str
    reason: str


class AuditPayload(BaseModel):
    status: Literal["pass", "fail"] = "fail"
    issues: List[AuditIssue] = Field(default_factory=list)


class AIEnrichmentService:
    def __init__(self, db: Session | None = None):
        self.db = db
        self.card_service = CardDataService()

    def enabled(self) -> bool:
        return bool(settings.ai_enabled and settings.openai_api_key.strip())

    def enrich_analysis(
        self,
        *,
        cards: List[Dict[str, Any]] | List[Any],
        commander: str | None,
        analysis: Dict[str, Any],
        sim_summary: Dict[str, Any],
        watchouts: List[Dict[str, Any]],
        card_map: Dict[str, Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        if not self.enabled():
            return analysis

        evidence = self._build_evidence_bundle(
            cards=cards,
            commander=commander,
            analysis=analysis,
            sim_summary=sim_summary,
            watchouts=watchouts,
            card_map=card_map,
        )

        intent = self._run_intent_enrichment(evidence, analysis)
        graphs = self._run_graph_enrichment(evidence, analysis)
        enriched_watchouts = self._run_watchout_enrichment(evidence, watchouts)

        if intent:
            analysis.setdefault("intent_summary", {}).update(intent)
        if graphs:
            analysis.setdefault("graph_explanations", {}).update(graphs.get("graph_explanations", {}))
            analysis.setdefault("graph_deck_blurbs", {}).update(graphs.get("graph_deck_blurbs", {}))
        if enriched_watchouts is not None:
            analysis["rules_watchouts"] = enriched_watchouts
        return analysis

    def enrich_guides(
        self,
        *,
        analyze: Dict[str, Any],
        sim_summary: Dict[str, Any],
        guides: Dict[str, str],
    ) -> Dict[str, str]:
        if not self.enabled():
            return guides

        evidence = self._build_evidence_bundle(
            cards=[],
            commander=analyze.get("intent_summary", {}).get("commander") or analyze.get("commander"),
            analysis=analyze,
            sim_summary=sim_summary,
            watchouts=analyze.get("rules_watchouts", []),
            card_map=None,
        )
        payload = self._run_guides_enrichment(evidence, analyze, guides)
        if not payload:
            return guides

        out = dict(guides)
        opt_text = payload.get("optimization_overview", {}).get("text", "").strip()
        play_text = payload.get("play_overview", {}).get("text", "").strip()
        if opt_text:
            out["optimization_guide_md"] = self._inject_guide_overview(
                guides.get("optimization_guide_md", ""),
                "## Optimization snapshot",
                opt_text,
            )
        if play_text:
            out["play_guide_md"] = self._inject_guide_overview(
                guides.get("play_guide_md", ""),
                "## Pilot snapshot",
                play_text,
            )
        return out

    def enrich_watchouts(
        self,
        *,
        cards: List[Dict[str, Any]] | List[Any],
        commander: str | None,
        watchouts: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not self.enabled():
            return watchouts
        evidence = self._build_evidence_bundle(
            cards=cards,
            commander=commander,
            analysis={},
            sim_summary={},
            watchouts=watchouts,
            card_map=None,
        )
        enriched = self._run_watchout_enrichment(evidence, watchouts)
        return enriched if enriched is not None else watchouts

    def run_consistency_audit(
        self,
        *,
        evidence: Dict[str, Any],
        sections: Dict[str, str],
    ) -> Dict[str, Any]:
        if not self.enabled():
            return {"status": "pass", "issues": []}
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "status": {"type": "string", "enum": ["pass", "fail"]},
                "issues": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "section": {"type": "string"},
                            "reason": {"type": "string"},
                        },
                        "required": ["section", "reason"],
                    },
                },
            },
            "required": ["status", "issues"],
        }
        prompt = {
            "evidence": self._trim_evidence_for_prompt(evidence, family="consistency_audit"),
            "sections": sections,
        }
        result = self._call_model_json("consistency_audit", prompt, schema)
        if not result:
            return {"status": "pass", "issues": []}
        parsed = AuditPayload.model_validate(result["parsed"]).model_dump()
        self._record_audit(
            family="consistency_audit",
            payload_hash=result["payload_hash"],
            status="accepted" if parsed.get("status") == "pass" else "rejected",
            reason="" if parsed.get("status") == "pass" else "consistency_fail",
            request_json=result["request_json"],
            response_json=result["response_json"],
            validation_issues={"issues": parsed.get("issues", [])},
            input_tokens=result["usage"].get("prompt_tokens", 0),
            output_tokens=result["usage"].get("completion_tokens", 0),
            estimated_cost_usd=result["estimated_cost_usd"],
        )
        return parsed

    def mine_override_candidates(self, limit: int = 25) -> Dict[str, Any]:
        if self.db is None:
            return {"items": []}
        rows = (
            self.db.query(AIEnrichmentAudit)
            .filter(AIEnrichmentAudit.status.in_(["rejected", "invalid"]))
            .order_by(AIEnrichmentAudit.created_at.desc())
            .limit(200)
            .all()
        )
        counts: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            issues = row.validation_issues or {}
            for issue in issues.get("issues", []):
                section = str(issue.get("section") or "unknown")
                entry = counts.setdefault(section, {"section": section, "count": 0, "reasons": {}})
                entry["count"] += 1
                reason = str(issue.get("reason") or "unspecified")
                entry["reasons"][reason] = int(entry["reasons"].get(reason, 0)) + 1
        items = []
        for section, payload in counts.items():
            reason_rows = sorted(payload["reasons"].items(), key=lambda x: (-x[1], x[0]))
            items.append(
                {
                    "section": section,
                    "count": payload["count"],
                    "top_reasons": [{"reason": r, "count": c} for r, c in reason_rows[:5]],
                }
            )
        items.sort(key=lambda x: (-x["count"], x["section"]))
        return {"items": items[:limit]}

    def _build_evidence_bundle(
        self,
        *,
        cards: List[Dict[str, Any]] | List[Any],
        commander: str | None,
        analysis: Dict[str, Any],
        sim_summary: Dict[str, Any],
        watchouts: List[Dict[str, Any]],
        card_map: Dict[str, Dict[str, Any]] | None,
    ) -> Dict[str, Any]:
        deck_names = self._deck_names(cards)
        rec_names = self._recommendation_names(analysis)
        combo_variant_ids = [str(v.get("variant_id")) for v in (analysis.get("combo_intel", {}) or {}).get("matched_variants", []) if v.get("variant_id")]
        watchout_names = [str(w.get("card") or "").strip() for w in watchouts if str(w.get("card") or "").strip()]
        allowed_card_names = sorted({n for n in (deck_names + rec_names + watchout_names + ([commander] if commander else [])) if n})
        lookup_names = allowed_card_names[:]
        lookup_names = sorted({n for n in lookup_names if n})
        if card_map is None:
            card_map = self.card_service.get_cards_by_name(lookup_names)

        evidence_index: Dict[str, Dict[str, Any]] = {}
        watchout_map: Dict[str, Dict[str, Any]] = {}
        for name in allowed_card_names:
            card = card_map.get(name, {}) or {}
            evidence_index[f"card:{name}"] = {
                "type": "card",
                "card": name,
                "oracle_id": str(card.get("oracle_id") or ""),
                "type_line": str(card.get("type_line") or ""),
            }
        for watchout in watchouts:
            card_name = str(watchout.get("card") or "").strip()
            if not card_name:
                continue
            rule_hits = []
            if self.db is not None:
                for query in (watchout.get("rule_queries") or [])[:3]:
                    for idx, hit in enumerate(search_rules(self.db, query, limit=2)):
                        eid = f"rule:{card_name}:{idx}"
                        evidence_index[eid] = {"type": "rule", "card": card_name, "query": query, "source": hit.get("source"), "title": hit.get("title")}
                        rule_hits.append({"id": eid, **hit})
            flags = []
            for flag in watchout.get("complexity_flags", []) or []:
                eid = f"flag:{card_name}:{flag}"
                evidence_index[eid] = {"type": "flag", "card": card_name, "flag": flag}
                flags.append({"id": eid, "flag": flag})
            rulings = []
            for idx, ruling in enumerate((watchout.get("rulings") or [])[:3]):
                eid = f"ruling:{card_name}:{idx}"
                evidence_index[eid] = {"type": "ruling", "card": card_name, "published_at": ruling.get("published_at")}
                rulings.append({"id": eid, **ruling})
            card = card_map.get(card_name, {})
            watchout_map[card_name] = {
                "card": card_name,
                "oracle_text": str(card.get("oracle_text") or ""),
                "type_line": str(card.get("type_line") or ""),
                "complexity_flags": watchout.get("complexity_flags") or [],
                "rulings": rulings,
                "rule_hits": rule_hits,
            }

        self._add_analysis_evidence(evidence_index, analysis)
        self._add_sim_evidence(evidence_index, sim_summary)

        evidence = {
            "analysis_hash": self._stable_hash(
                {
                    "analysis": analysis,
                    "sim_summary": sim_summary,
                    "watchouts": watchouts,
                    "cards": deck_names,
                    "commander": commander,
                }
            ),
            "commander": commander,
            "allowed_card_names": allowed_card_names,
            "combo_variant_ids": combo_variant_ids,
            "combo_variants": (analysis.get("combo_intel", {}) or {}).get("matched_variants", []),
            "analysis": {
                "intent_summary": analysis.get("intent_summary", {}),
                "graph_explanations": analysis.get("graph_explanations", {}),
                "graph_deck_blurbs": analysis.get("graph_deck_blurbs", {}),
                "adds": analysis.get("adds", []),
                "cuts": analysis.get("cuts", []),
                "swaps": analysis.get("swaps", []),
                "health_summary": analysis.get("health_summary", {}),
                "missing_roles": analysis.get("missing_roles", []),
                "bracket_report": analysis.get("bracket_report", {}),
                "combo_intel": analysis.get("combo_intel", {}),
            },
            "sim_summary": {
                "milestones": sim_summary.get("milestones", {}),
                "failure_modes": sim_summary.get("failure_modes", {}),
                "win_metrics": sim_summary.get("win_metrics", {}),
                "runs": sim_summary.get("runs", 0),
            },
            "cards": {
                name: {
                    "type_line": str((card_map.get(name) or {}).get("type_line") or ""),
                    "oracle_text": str((card_map.get(name) or {}).get("oracle_text") or ""),
                    "mana_cost": str((card_map.get(name) or {}).get("mana_cost") or ""),
                    "color_identity": (card_map.get(name) or {}).get("color_identity") or [],
                    "keywords": (card_map.get(name) or {}).get("keywords") or [],
                }
                for name in allowed_card_names
            },
            "watchouts": watchout_map,
            "evidence_index": evidence_index,
            "allowed_numbers": sorted(self._collect_allowed_numbers({"analysis": analysis, "sim_summary": sim_summary})),
        }
        return evidence

    def _run_intent_enrichment(self, evidence: Dict[str, Any], analysis: Dict[str, Any]) -> Dict[str, str] | None:
        intent = analysis.get("intent_summary", {}) or {}
        prompt = {
            "intent_summary": intent,
            "health_summary": analysis.get("health_summary", {}),
            "combo_intel": analysis.get("combo_intel", {}),
            "allowed_card_names": evidence.get("allowed_card_names", []),
            "evidence_index": self._prompt_evidence_subset(evidence, prefixes=["intent:", "card:", "sim:", "combo:", "recommendation:"]),
        }
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "sections": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "key": {
                                "type": "string",
                                "enum": [
                                    "plan_narrative",
                                    "backup_narrative",
                                    "engine_narrative",
                                    "interaction_narrative",
                                    "kill_vector_narrative",
                                ],
                            },
                            "text": {"type": "string"},
                            "citations": {"type": "array", "items": {"type": "string"}},
                            "mentioned_cards": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["key", "text", "citations", "mentioned_cards"],
                    },
                }
            },
            "required": ["sections"],
        }
        result = self._call_model_json("intent_summary", prompt, schema)
        if not result:
            return None
        parsed = IntentPayload.model_validate(result["parsed"]).model_dump()
        accepted: Dict[str, str] = {}
        issues: List[Dict[str, Any]] = []
        for section in parsed.get("sections", []):
            ok, reasons = self._validate_text_block(
                text=section["text"],
                citations=section["citations"],
                mentioned_cards=section["mentioned_cards"],
                evidence=evidence,
                require_rule_citation=False,
                oracle_texts=[],
                section_key=section["key"],
            )
            if ok:
                accepted[section["key"]] = section["text"].strip()
            else:
                issues.extend(reasons)
        self._record_audit(
            family="intent_summary",
            payload_hash=result["payload_hash"],
            status="accepted" if accepted else "rejected",
            reason="" if accepted else "validation_failed",
            request_json=result["request_json"],
            response_json=result["response_json"],
            validation_issues={"issues": issues},
            input_tokens=result["usage"].get("prompt_tokens", 0),
            output_tokens=result["usage"].get("completion_tokens", 0),
            estimated_cost_usd=result["estimated_cost_usd"],
        )
        return accepted or None

    def _run_graph_enrichment(self, evidence: Dict[str, Any], analysis: Dict[str, Any]) -> Dict[str, Dict[str, str]] | None:
        explain = analysis.get("graph_explanations", {}) or {}
        blurbs = analysis.get("graph_deck_blurbs", {}) or {}
        requested_keys = sorted(set(explain.keys()) | set(blurbs.keys()))
        if not requested_keys:
            return None
        prompt = {
            "graph_explanations": explain,
            "graph_deck_blurbs": blurbs,
            "allowed_card_names": evidence.get("allowed_card_names", []),
            "requested_keys": requested_keys,
            "evidence_index": self._prompt_evidence_subset(evidence, prefixes=["card:", "sim:", "intent:", "recommendation:", "combo:"]),
            "sim_summary": evidence.get("sim_summary", {}),
            "intent_summary": evidence.get("analysis", {}).get("intent_summary", {}),
            "cuts": evidence.get("analysis", {}).get("cuts", []),
            "adds": evidence.get("analysis", {}).get("adds", []),
        }
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "key": {"type": "string"},
                            "kind": {"type": "string", "enum": ["explanation", "blurb"]},
                            "text": {"type": "string"},
                            "citations": {"type": "array", "items": {"type": "string"}},
                            "mentioned_cards": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["key", "kind", "text", "citations", "mentioned_cards"],
                    },
                }
            },
            "required": ["items"],
        }
        result = self._call_model_json("graph_blurb", prompt, schema)
        if not result:
            return None
        parsed = GraphPayload.model_validate(result["parsed"]).model_dump()
        out = {"graph_explanations": {}, "graph_deck_blurbs": {}}
        issues: List[Dict[str, Any]] = []
        allowed_keys = set(requested_keys)
        for item in parsed.get("items", []):
            if item["key"] not in allowed_keys:
                issues.append({"section": item["key"], "reason": "unknown graph key"})
                continue
            ok, reasons = self._validate_text_block(
                text=item["text"],
                citations=item["citations"],
                mentioned_cards=item["mentioned_cards"],
                evidence=evidence,
                require_rule_citation=False,
                oracle_texts=[],
                section_key=f"{item['kind']}:{item['key']}",
            )
            if not ok:
                issues.extend(reasons)
                continue
            target = "graph_explanations" if item["kind"] == "explanation" else "graph_deck_blurbs"
            out[target][item["key"]] = item["text"].strip()
        self._record_audit(
            family="graph_blurb",
            payload_hash=result["payload_hash"],
            status="accepted" if out["graph_explanations"] or out["graph_deck_blurbs"] else "rejected",
            reason="" if out["graph_explanations"] or out["graph_deck_blurbs"] else "validation_failed",
            request_json=result["request_json"],
            response_json=result["response_json"],
            validation_issues={"issues": issues},
            input_tokens=result["usage"].get("prompt_tokens", 0),
            output_tokens=result["usage"].get("completion_tokens", 0),
            estimated_cost_usd=result["estimated_cost_usd"],
        )
        if not out["graph_explanations"] and not out["graph_deck_blurbs"]:
            return None
        return out

    def _run_watchout_enrichment(self, evidence: Dict[str, Any], watchouts: List[Dict[str, Any]]) -> List[Dict[str, Any]] | None:
        if not watchouts:
            return []
        prompt_watchouts = []
        for watchout in watchouts[:12]:
            card = str(watchout.get("card") or "")
            if not card:
                continue
            prompt_watchouts.append(
                {
                    "card": card,
                    "complexity_flags": watchout.get("complexity_flags", []),
                    "rulings": watchout.get("rulings", []),
                    "rule_hits": (evidence.get("watchouts", {}).get(card) or {}).get("rule_hits", []),
                    "oracle_text": (evidence.get("watchouts", {}).get(card) or {}).get("oracle_text", ""),
                }
            )
        prompt = {
            "watchouts": prompt_watchouts,
            "allowed_card_names": evidence.get("allowed_card_names", []),
            "evidence_index": self._prompt_evidence_subset(evidence, prefixes=["flag:", "ruling:", "rule:", "card:"]),
        }
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "card": {"type": "string"},
                            "errata": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "text": {"type": "string"},
                                        "citations": {"type": "array", "items": {"type": "string"}},
                                        "mentioned_cards": {"type": "array", "items": {"type": "string"}},
                                    },
                                    "required": ["text", "citations", "mentioned_cards"],
                                },
                            },
                            "notes": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "text": {"type": "string"},
                                        "citations": {"type": "array", "items": {"type": "string"}},
                                        "mentioned_cards": {"type": "array", "items": {"type": "string"}},
                                    },
                                    "required": ["text", "citations", "mentioned_cards"],
                                },
                            },
                            "rules_information": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "text": {"type": "string"},
                                        "citations": {"type": "array", "items": {"type": "string"}},
                                        "mentioned_cards": {"type": "array", "items": {"type": "string"}},
                                    },
                                    "required": ["text", "citations", "mentioned_cards"],
                                },
                            },
                        },
                        "required": ["card", "errata", "notes", "rules_information"],
                    },
                }
            },
            "required": ["items"],
        }
        result = self._call_model_json("rules_watchout", prompt, schema)
        if not result:
            return None
        parsed = WatchoutPayload.model_validate(result["parsed"]).model_dump()
        by_card = {str(item.get("card") or ""): item for item in parsed.get("items", [])}
        out: List[Dict[str, Any]] = []
        issues: List[Dict[str, Any]] = []
        for watchout in watchouts:
            card = str(watchout.get("card") or "")
            item = by_card.get(card)
            if not item:
                continue
            oracle_texts = [str((evidence.get("watchouts", {}).get(card) or {}).get("oracle_text") or "")]
            sections = {"errata": [], "notes": [], "rules_information": []}
            for key in sections.keys():
                for idx, block in enumerate(item.get(key, [])):
                    ok, reasons = self._validate_text_block(
                        text=block["text"],
                        citations=block["citations"],
                        mentioned_cards=block["mentioned_cards"],
                        evidence=evidence,
                        require_rule_citation=True,
                        oracle_texts=oracle_texts,
                        section_key=f"{card}:{key}:{idx}",
                    )
                    if ok and block["text"].strip():
                        sections[key].append(block["text"].strip())
                    else:
                        issues.extend(reasons)
            if not sections["errata"] and not sections["notes"] and not sections["rules_information"]:
                continue
            row = dict(watchout)
            row["errata"] = sections["errata"]
            row["notes"] = sections["notes"]
            row["rules_information"] = sections["rules_information"]
            out.append(row)
        self._record_audit(
            family="rules_watchout",
            payload_hash=result["payload_hash"],
            status="accepted" if out else "rejected",
            reason="" if out else "validation_failed",
            request_json=result["request_json"],
            response_json=result["response_json"],
            validation_issues={"issues": issues},
            input_tokens=result["usage"].get("prompt_tokens", 0),
            output_tokens=result["usage"].get("completion_tokens", 0),
            estimated_cost_usd=result["estimated_cost_usd"],
        )
        return out

    def _run_guides_enrichment(self, evidence: Dict[str, Any], analyze: Dict[str, Any], guides: Dict[str, str]) -> Dict[str, Any] | None:
        prompt = {
            "intent_summary": analyze.get("intent_summary", {}),
            "combo_intel": analyze.get("combo_intel", {}),
            "adds": analyze.get("adds", [])[:5],
            "cuts": analyze.get("cuts", [])[:5],
            "swaps": analyze.get("swaps", [])[:5],
            "sim_summary": evidence.get("sim_summary", {}),
            "existing_guides": {
                "optimization": guides.get("optimization_guide_md", "")[:4000],
                "play": guides.get("play_guide_md", "")[:6000],
            },
            "allowed_card_names": evidence.get("allowed_card_names", []),
            "evidence_index": self._prompt_evidence_subset(evidence, prefixes=["card:", "sim:", "intent:", "combo:", "recommendation:"]),
        }
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "optimization_overview": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "text": {"type": "string"},
                        "citations": {"type": "array", "items": {"type": "string"}},
                        "mentioned_cards": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["text", "citations", "mentioned_cards"],
                },
                "play_overview": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "text": {"type": "string"},
                        "citations": {"type": "array", "items": {"type": "string"}},
                        "mentioned_cards": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["text", "citations", "mentioned_cards"],
                },
            },
            "required": ["optimization_overview", "play_overview"],
        }
        result = self._call_model_json("primer", prompt, schema)
        if not result:
            return None
        parsed = GuidePayload.model_validate(result["parsed"]).model_dump()
        issues: List[Dict[str, Any]] = []
        accepted: Dict[str, Any] = {}
        for key in ("optimization_overview", "play_overview"):
            block = parsed.get(key, {})
            ok, reasons = self._validate_text_block(
                text=block.get("text", ""),
                citations=block.get("citations", []),
                mentioned_cards=block.get("mentioned_cards", []),
                evidence=evidence,
                require_rule_citation=False,
                oracle_texts=[],
                section_key=key,
            )
            if ok and block.get("text", "").strip():
                accepted[key] = block
            else:
                issues.extend(reasons)
        audit_sections = {
            key: block.get("text", "") for key, block in accepted.items()
        }
        audit_result = self.run_consistency_audit(evidence=evidence, sections=audit_sections) if audit_sections else {"status": "pass", "issues": []}
        if audit_result.get("status") == "fail":
            issues.extend([{"section": issue.get("section", "audit"), "reason": issue.get("reason", "audit_failed")} for issue in audit_result.get("issues", [])])
            accepted = {}
        self._record_audit(
            family="primer",
            payload_hash=result["payload_hash"],
            status="accepted" if accepted else "rejected",
            reason="" if accepted else "validation_failed",
            request_json=result["request_json"],
            response_json=result["response_json"],
            validation_issues={"issues": issues},
            input_tokens=result["usage"].get("prompt_tokens", 0),
            output_tokens=result["usage"].get("completion_tokens", 0),
            estimated_cost_usd=result["estimated_cost_usd"],
        )
        return accepted or None

    def _call_model_json(self, family: str, prompt_payload: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any] | None:
        if not self.enabled():
            return None
        request_json = {
            "family": family,
            "model": settings.openai_model,
            "prompt_payload": prompt_payload,
            "schema": schema,
        }
        payload_hash = self._stable_hash(request_json)
        cached = self._read_cache(family, payload_hash)
        if cached is not None:
            self._record_audit(
                family=family,
                payload_hash=payload_hash,
                status="cache_hit",
                reason="",
                request_json=request_json,
                response_json=cached,
                validation_issues={},
                input_tokens=int((cached.get("usage") or {}).get("prompt_tokens", 0)),
                output_tokens=int((cached.get("usage") or {}).get("completion_tokens", 0)),
                estimated_cost_usd=float(cached.get("estimated_cost_usd", 0.0) or 0.0),
            )
            return cached

        if not self._within_budget():
            self._record_audit(
                family=family,
                payload_hash=payload_hash,
                status="budget_skip",
                reason="daily_budget_exceeded",
                request_json=request_json,
                response_json={},
                validation_issues={},
            )
            return None
        if not self._within_rate_limit():
            self._record_audit(
                family=family,
                payload_hash=payload_hash,
                status="rate_limited",
                reason="minute_cap_exceeded",
                request_json=request_json,
                response_json={},
                validation_issues={},
            )
            return None

        system_prompt = self._system_prompt(family)
        user_prompt = self._user_prompt(family, prompt_payload)
        body = {
            "model": settings.openai_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_completion_tokens": settings.ai_max_output_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": f"deck_check_{family}",
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        try:
            with httpx.Client(timeout=settings.ai_timeout_s) as client:
                resp = client.post(
                    OPENAI_CHAT_COMPLETIONS_URL,
                    headers={
                        "Authorization": f"Bearer {settings.openai_api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
            resp.raise_for_status()
            response_json = resp.json()
            content = self._extract_message_content(response_json)
            if not content:
                self._record_audit(
                    family=family,
                    payload_hash=payload_hash,
                    status="invalid",
                    reason="empty_response_content",
                    request_json=request_json,
                    response_json=response_json,
                    validation_issues={},
                )
                return None
            parsed = json.loads(content)
            usage = response_json.get("usage") or {}
            estimated_cost = self._estimate_cost_usd(
                prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
                completion_tokens=int(usage.get("completion_tokens", 0) or 0),
            )
            result = {
                "parsed": parsed,
                "usage": usage,
                "response_json": {"parsed": parsed, "raw": response_json},
                "request_json": request_json,
                "payload_hash": payload_hash,
                "estimated_cost_usd": estimated_cost,
            }
            self._write_cache(family, payload_hash, result)
            self._add_cost_to_budget(estimated_cost)
            return result
        except Exception as exc:
            self._record_audit(
                family=family,
                payload_hash=payload_hash,
                status="error",
                reason=f"{type(exc).__name__}: {exc}",
                request_json=request_json,
                response_json={},
                validation_issues={},
            )
            return None

    def _extract_message_content(self, response_json: Dict[str, Any]) -> str:
        choices = response_json.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            out: List[str] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                text = item.get("text")
                if isinstance(text, str):
                    out.append(text)
            return "\n".join(out).strip()
        return ""

    def _validate_text_block(
        self,
        *,
        text: str,
        citations: Sequence[str],
        mentioned_cards: Sequence[str],
        evidence: Dict[str, Any],
        require_rule_citation: bool,
        oracle_texts: Sequence[str],
        section_key: str,
    ) -> tuple[bool, List[Dict[str, str]]]:
        issues: List[Dict[str, str]] = []
        text = str(text or "").strip()
        if not text:
            return False, [{"section": section_key, "reason": "empty text"}]

        allowed_ids = set((evidence.get("evidence_index") or {}).keys())
        bad_citations = [c for c in citations if c not in allowed_ids]
        if bad_citations:
            issues.append({"section": section_key, "reason": f"unknown citations: {', '.join(sorted(set(bad_citations)))}"})
        if not citations:
            issues.append({"section": section_key, "reason": "missing citations"})
        if require_rule_citation and not any(str(c).startswith(("rule:", "ruling:", "flag:")) for c in citations):
            issues.append({"section": section_key, "reason": "missing rule or ruling citation"})

        allowed_cards = {str(name) for name in evidence.get("allowed_card_names", [])}
        bad_cards = [name for name in mentioned_cards if name not in allowed_cards]
        if bad_cards:
            issues.append({"section": section_key, "reason": f"unknown mentioned cards: {', '.join(sorted(set(bad_cards)))}"})
        backticked = [m.strip() for m in CARD_NAME_RE.findall(text) if m.strip()]
        bad_backticked = [name for name in backticked if name not in allowed_cards]
        if bad_backticked:
            issues.append({"section": section_key, "reason": f"unknown backticked cards: {', '.join(sorted(set(bad_backticked)))}"})

        allowed_numbers = set(evidence.get("allowed_numbers", []) or [])
        for token in NUMBER_RE.findall(text):
            if token in allowed_numbers:
                continue
            if token.rstrip("%") in {str(i) for i in range(0, 101)}:
                continue
            issues.append({"section": section_key, "reason": f"unsupported number token: {token}"})
            break

        combo_variant_ids = set(evidence.get("combo_variant_ids", []) or [])
        variant_mentions = re.findall(r"\b[a-zA-Z]+-?\d+\b", text)
        for variant in variant_mentions:
            if variant.startswith("T"):
                continue
            if variant in combo_variant_ids:
                continue
            if any(variant in c for c in citations):
                continue
        for oracle_text in oracle_texts:
            oracle_text = str(oracle_text or "").strip()
            if not oracle_text:
                continue
            if fuzz.partial_ratio(text.lower(), oracle_text.lower()) >= 86:
                issues.append({"section": section_key, "reason": "too close to oracle text"})
                break

        return not issues, issues

    def _inject_guide_overview(self, markdown: str, heading: str, body: str) -> str:
        lines = markdown.splitlines()
        if not lines:
            return f"{heading}\n\n{body}"
        if heading in markdown:
            return markdown
        if lines[0].startswith("# "):
            return "\n".join([lines[0], "", heading, body, "", *lines[1:]]).strip()
        return f"{heading}\n\n{body}\n\n{markdown}".strip()

    def _deck_names(self, cards: Iterable[Dict[str, Any]] | Iterable[Any]) -> List[str]:
        out: List[str] = []
        for card in cards or []:
            if isinstance(card, dict):
                name = str(card.get("name") or "").strip()
                section = str(card.get("section") or "deck")
            else:
                name = str(getattr(card, "name", "") or "").strip()
                section = str(getattr(card, "section", "deck") or "deck")
            if name and section in {"deck", "commander"}:
                out.append(name)
        return out

    def _recommendation_names(self, analysis: Dict[str, Any]) -> List[str]:
        out: List[str] = []
        for row in analysis.get("adds", []) or []:
            if row.get("card"):
                out.append(str(row["card"]))
        for row in analysis.get("cuts", []) or []:
            if row.get("card"):
                out.append(str(row["card"]))
        for row in analysis.get("swaps", []) or []:
            if row.get("cut"):
                out.append(str(row["cut"]))
            if row.get("add"):
                out.append(str(row["add"]))
        intent = analysis.get("intent_summary", {}) or {}
        for key in ("key_support_cards", "key_engine_cards", "main_wincon_cards", "key_interaction_cards"):
            for name in intent.get(key, []) or []:
                if name:
                    out.append(str(name))
        return out

    def _add_analysis_evidence(self, evidence_index: Dict[str, Dict[str, Any]], analysis: Dict[str, Any]) -> None:
        intent = analysis.get("intent_summary", {}) or {}
        for key in ("primary_plan", "secondary_plan"):
            if intent.get(key):
                evidence_index[f"intent:{key}"] = {"type": "intent", "value": intent.get(key)}
        for idx, kill in enumerate(intent.get("kill_vectors", []) or []):
            evidence_index[f"intent:kill_vector:{idx}"] = {"type": "kill_vector", "value": kill}
        for idx, add in enumerate((analysis.get("adds") or [])[:10]):
            if add.get("card"):
                evidence_index[f"recommendation:add:{idx}"] = {"type": "recommendation", "card": add.get("card"), "fills": add.get("fills")}
        for idx, cut in enumerate((analysis.get("cuts") or [])[:10]):
            if cut.get("card"):
                evidence_index[f"recommendation:cut:{idx}"] = {"type": "recommendation", "card": cut.get("card")}
        combo = analysis.get("combo_intel", {}) or {}
        for idx, variant in enumerate((combo.get("matched_variants") or [])[:10]):
            if variant.get("variant_id"):
                evidence_index[f"combo:{idx}"] = {"type": "combo", "variant_id": variant.get("variant_id")}

    def _add_sim_evidence(self, evidence_index: Dict[str, Dict[str, Any]], sim_summary: Dict[str, Any]) -> None:
        milestones = sim_summary.get("milestones", {}) or {}
        for key, value in milestones.items():
            if isinstance(value, (int, float)):
                evidence_index[f"sim:{key}"] = {"type": "metric", "value": value}
        failures = sim_summary.get("failure_modes", {}) or {}
        for key, value in failures.items():
            if isinstance(value, (int, float)):
                evidence_index[f"sim:failure:{key}"] = {"type": "metric", "value": value}
        win = sim_summary.get("win_metrics", {}) or {}
        for key, value in win.items():
            if isinstance(value, (int, float, str)):
                evidence_index[f"sim:win:{key}"] = {"type": "metric", "value": value}

    def _collect_allowed_numbers(self, obj: Any) -> set[str]:
        out: set[str] = set()
        self._walk_numbers(obj, out)
        for i in range(0, 21):
            out.add(str(i))
        for i in range(0, 101):
            out.add(f"{i}%")
        return out

    def _walk_numbers(self, obj: Any, out: set[str]) -> None:
        if isinstance(obj, bool):
            return
        if isinstance(obj, int):
            out.add(str(obj))
            return
        if isinstance(obj, float):
            out.add(f"{obj:.0f}")
            out.add(f"{obj:.1f}")
            out.add(f"{obj:.2f}")
            if 0 <= obj <= 1:
                out.add(f"{obj:.0%}")
                out.add(f"{obj:.1%}")
            return
        if isinstance(obj, dict):
            for value in obj.values():
                self._walk_numbers(value, out)
            return
        if isinstance(obj, list):
            for value in obj:
                self._walk_numbers(value, out)

    def _trim_evidence_for_prompt(self, evidence: Dict[str, Any], family: str) -> Dict[str, Any]:
        if family == "consistency_audit":
            return {
                "analysis": evidence.get("analysis", {}),
                "sim_summary": evidence.get("sim_summary", {}),
                "combo_variants": evidence.get("combo_variants", []),
                "allowed_card_names": evidence.get("allowed_card_names", []),
            }
        return evidence

    def _prompt_evidence_subset(self, evidence: Dict[str, Any], prefixes: Sequence[str]) -> Dict[str, Any]:
        index = evidence.get("evidence_index", {}) or {}
        out = {}
        for key, value in index.items():
            if any(key.startswith(prefix) for prefix in prefixes):
                out[key] = value
        return out

    def _system_prompt(self, family: str) -> str:
        base = (
            "You are Deck.Check's hidden prose enrichment layer. "
            "You are not the source of truth. Use only the supplied evidence bundle. "
            "Never invent card names, numbers, rules, legality claims, combo lines, or recommendations. "
            "If evidence is insufficient, return empty text for that field. "
            "Return JSON only and follow the schema exactly. "
            "Wrap every card name you mention in backticks. "
            "Do not quote long oracle text. Transform facts into short explanations for normal Commander players."
        )
        family_tail = {
            "intent_summary": "Write concise plan narratives grounded in the provided intent, combo, and performance evidence.",
            "graph_blurb": "Explain graphs in plain English and tie advice to named cards only when supported by evidence.",
            "rules_watchout": "Explain tricky interactions, rulings, and sequencing. Do not repeat the card's oracle text.",
            "primer": "Write short primer overviews grounded in verified deck identity, metrics, and recommendations.",
            "consistency_audit": "Act as an internal checker and flag contradictions against the supplied evidence.",
        }
        return f"{base} {family_tail.get(family, '')}".strip()

    def _user_prompt(self, family: str, prompt_payload: Dict[str, Any]) -> str:
        instructions = {
            "intent_summary": (
                "Fill each section only if the evidence supports it. Mention concrete cards only from allowed_card_names. "
                "Use citations for every section."
            ),
            "graph_blurb": (
                "Rewrite only the requested graph keys. Keep explanations practical. "
                "If a graph lacks enough evidence for card-specific advice, omit card mentions instead of guessing."
            ),
            "rules_watchout": (
                "For each card, populate errata only from rulings, notes from complexity flags and rule hits, and rules_information from verified timing/layer/search evidence. "
                "Do not restate oracle text."
            ),
            "primer": (
                "Produce one short optimization overview and one short play overview. "
                "Do not invent new recommendations or matchup claims beyond the evidence bundle."
            ),
            "consistency_audit": "Return fail with issues if any section adds unsupported facts or contradicts the evidence.",
        }
        return json.dumps({"instructions": instructions.get(family, ""), "payload": prompt_payload}, ensure_ascii=True, sort_keys=True)

    def _estimate_cost_usd(self, prompt_tokens: int, completion_tokens: int) -> float:
        model_name = settings.openai_model.strip()
        input_cost, output_cost = MODEL_PRICING_PER_1M.get(model_name, (DEFAULT_INPUT_COST_PER_1M, DEFAULT_OUTPUT_COST_PER_1M))
        return round((prompt_tokens * input_cost + completion_tokens * output_cost) / 1_000_000, 6)

    def _within_budget(self) -> bool:
        if settings.ai_daily_budget_usd <= 0:
            return True
        spent = self._read_budget_spend()
        return spent < settings.ai_daily_budget_usd

    def _within_rate_limit(self) -> bool:
        key = f"aienrich:rate:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}"
        try:
            count = redis_conn.incr(key)
            if int(count) == 1:
                redis_conn.expire(key, 120)
            return int(count) <= AI_RATE_LIMIT_PER_MINUTE
        except Exception:
            return True

    def _read_budget_spend(self) -> float:
        key = f"aienrich:budget:{datetime.now(timezone.utc).date().isoformat()}"
        try:
            raw = redis_conn.get(key)
            return float(raw or 0.0)
        except Exception:
            return 0.0

    def _add_cost_to_budget(self, amount: float) -> None:
        if amount <= 0:
            return
        key = f"aienrich:budget:{datetime.now(timezone.utc).date().isoformat()}"
        try:
            redis_conn.incrbyfloat(key, amount)
            redis_conn.expire(key, 172800)
        except Exception:
            return

    def _cache_key(self, family: str, payload_hash: str) -> str:
        return f"aienrich:{family}:{settings.openai_model}:{payload_hash}"

    def _read_cache(self, family: str, payload_hash: str) -> Dict[str, Any] | None:
        try:
            raw = redis_conn.get(self._cache_key(family, payload_hash))
        except Exception:
            return None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    def _write_cache(self, family: str, payload_hash: str, payload: Dict[str, Any]) -> None:
        try:
            redis_conn.setex(self._cache_key(family, payload_hash), settings.ai_cache_ttl_s, json.dumps(payload))
        except Exception:
            return

    def _record_audit(
        self,
        *,
        family: str,
        payload_hash: str,
        status: str,
        reason: str,
        request_json: Dict[str, Any],
        response_json: Dict[str, Any],
        validation_issues: Dict[str, Any],
        input_tokens: int = 0,
        output_tokens: int = 0,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if self.db is None:
            return
        try:
            row = AIEnrichmentAudit(
                family=family,
                payload_hash=payload_hash,
                status=status,
                model=settings.openai_model,
                reason=reason,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost_usd=estimated_cost_usd,
                request_json=self._json_safe(request_json),
                response_json=self._json_safe(response_json),
                validation_issues=self._json_safe(validation_issues),
            )
            self.db.add(row)
            self.db.commit()
        except Exception:
            self.db.rollback()

    def _json_safe(self, obj: Any) -> Any:
        if obj is None:
            return {}
        try:
            return json.loads(json.dumps(obj, ensure_ascii=True, default=str))
        except Exception:
            return {"error": "serialization_failed"}

    def _stable_hash(self, obj: Any) -> str:
        stable = json.dumps(obj, sort_keys=True, ensure_ascii=True, separators=(",", ":"), default=str)
        return hashlib.sha256(stable.encode()).hexdigest()
