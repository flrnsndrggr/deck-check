from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from statistics import median
from typing import Dict, List

from app.schemas.deck import CardEntry
from app.services.edhrec import EDHRecService
from app.services.scryfall import CardDataService
from app.services.tagger import compute_type_theme_profile

ROLE_TARGETS = {
    "balanced": {
        "#Land": 36,
        "#Ramp": 10,
        "#Draw": 10,
        "#Removal": 8,
        "#Boardwipe": 3,
        "#Tutor": 3,
        "#Protection": 5,
    }
}

CORE_TARGET_ROLES = [
    "#Land",
    "#Ramp",
    "#Fixing",
    "#Draw",
    "#Tutor",
    "#Removal",
    "#Counter",
    "#Boardwipe",
    "#Protection",
    "#Recursion",
    "#Engine",
    "#Wincon",
]

ROLE_PHILOSOPHY_TARGETS = {
    "proactive_combo": {
        "#Land": 34,
        "#Ramp": 12,
        "#Fixing": 8,
        "#Draw": 10,
        "#Tutor": 7,
        "#Removal": 4,
        "#Counter": 6,
        "#Boardwipe": 1,
        "#Protection": 6,
        "#Recursion": 2,
        "#Engine": 8,
        "#Wincon": 7,
    },
    "control_attrition": {
        "#Land": 36,
        "#Ramp": 9,
        "#Fixing": 8,
        "#Draw": 11,
        "#Tutor": 3,
        "#Removal": 9,
        "#Counter": 8,
        "#Boardwipe": 5,
        "#Protection": 4,
        "#Recursion": 4,
        "#Engine": 9,
        "#Wincon": 4,
    },
    "midrange_value": {
        "#Land": 36,
        "#Ramp": 10,
        "#Fixing": 8,
        "#Draw": 10,
        "#Tutor": 3,
        "#Removal": 7,
        "#Counter": 4,
        "#Boardwipe": 3,
        "#Protection": 5,
        "#Recursion": 4,
        "#Engine": 10,
        "#Wincon": 5,
    },
    "battlecruiser_value": {
        "#Land": 37,
        "#Ramp": 11,
        "#Fixing": 7,
        "#Draw": 9,
        "#Tutor": 2,
        "#Removal": 7,
        "#Counter": 2,
        "#Boardwipe": 3,
        "#Protection": 4,
        "#Recursion": 4,
        "#Engine": 8,
        "#Wincon": 7,
    },
    "stax_resource": {
        "#Land": 35,
        "#Ramp": 9,
        "#Fixing": 7,
        "#Draw": 9,
        "#Tutor": 4,
        "#Removal": 7,
        "#Counter": 6,
        "#Boardwipe": 2,
        "#Protection": 6,
        "#Recursion": 3,
        "#Engine": 9,
        "#Wincon": 4,
    },
}

MANA_ORDER = ["W", "U", "B", "R", "G", "C"]
MANA_LABELS = {
    "W": "White",
    "U": "Blue",
    "B": "Black",
    "R": "Red",
    "G": "Green",
    "C": "Colorless",
}

DECK_NAME_THEME_HOOKS = {
    "#Artifacts": ["Overclock", "Clockwork", "Chrome Sermon"],
    "#Enchantments": ["Rites", "Sigil", "Halo Work"],
    "#Tokens": ["Procession", "Pageant", "Parade"],
    "#Sacrifice": ["Bone Market", "Last Call", "Blood Ledger"],
    "#Spellslinger": ["Spellchain", "Fireworks", "Stack Dance"],
    "#Voltron": ["Warpath", "Lone Blade", "Single Combat"],
    "#Reanimator": ["Graveflow", "Afterparty", "Bone Tide"],
    "#Storm": ["Stormglass", "Ritual Storm", "Spark Weather"],
    "#LandsMatter": ["Faultline", "Groundwork", "Wilds Engine"],
    "#Counters": ["Escalation", "Tall Order", "Counterweight"],
    "#Blink": ["Ghoststep", "Flicker Hall", "Mirror Step"],
    "#Aristocrats": ["Last Supper", "Blood Ledger", "Bone Tax"],
    "#Control": ["Lockbox", "Icehouse", "Tax Season"],
    "#ComboControl": ["Soft Lock", "Endgame", "Icebox"],
}

DECK_NAME_THEME_LABELS = {
    "#Artifacts": "Artifacts",
    "#Enchantments": "Enchantments",
    "#Tokens": "Tokens",
    "#Sacrifice": "Sacrifice",
    "#Spellslinger": "Spells",
    "#Voltron": "Voltron",
    "#Reanimator": "Reanimator",
    "#Storm": "Storm",
    "#LandsMatter": "Lands",
    "#Counters": "Counters",
    "#Blink": "Blink",
    "#Aristocrats": "Aristocrats",
    "#Control": "Control",
    "#ComboControl": "Combo-Control",
}

DECK_NAME_PLAN_HOOKS = {
    "Combo Assembly": ["Assembly", "Breakfast", "Loopwork"],
    "Value Midrange": ["Long Game", "Grindhouse", "Value Engine"],
    "Control into Inevitable Finish": ["Lockbox", "Endgame", "Tax Season"],
    "Voltron Pressure": ["Warpath", "Lone Blade", "Single Combat"],
    "Poison Tempo": ["Toxicology", "Venom Clock", "Plague Run"],
    "Life-Drain Attrition": ["Blood Ledger", "Bleedout", "Last Call"],
    "Mill Pressure": ["Deep End", "Memory Leak", "Empty Shelves"],
}

DECK_NAME_PLAN_LABELS = {
    "Combo Assembly": "Combo",
    "Value Midrange": "Midrange",
    "Control into Inevitable Finish": "Control",
    "Voltron Pressure": "Voltron",
    "Poison Tempo": "Poison",
    "Life-Drain Attrition": "Drain",
    "Mill Pressure": "Mill",
}
_MANA_SYMBOL_RE = re.compile(r"\{([^}]+)\}")
_ADD_SEGMENT_RE = re.compile(r"add ([^.]+)", re.IGNORECASE)


def _safe_float(v: object, default: float = 0.0) -> float:
    try:
        return float(v)  # type: ignore[arg-type]
    except Exception:
        return default


def _pip_weights_from_symbol(symbol: str) -> Dict[str, float]:
    s = (symbol or "").strip().upper()
    if not s:
        return {}
    if s in MANA_ORDER:
        return {s: 1.0}
    if s.isdigit():
        return {"GENERIC": float(int(s))}
    if s in {"X", "Y", "Z", "T", "Q", "S", "E", "CHAOS"}:
        return {}
    if "/" in s:
        parts = [p.strip() for p in s.split("/") if p.strip()]
        color_parts = [p for p in parts if p in MANA_ORDER]
        if color_parts:
            # Hybrid/phyrexian/2-color symbols are split so demand isn't double-counted.
            w = 1.0 / len(color_parts)
            return {c: w for c in color_parts}
    return {}


def _mana_costs_for_payload(payload: Dict) -> List[str]:
    out: List[str] = []
    mc = payload.get("mana_cost")
    if isinstance(mc, str) and mc:
        out.append(mc)
    for face in payload.get("card_faces") or []:
        fm = face.get("mana_cost")
        if isinstance(fm, str) and fm:
            out.append(fm)
    # Keep order stable, dedupe exact duplicates.
    seen = set()
    unique: List[str] = []
    for x in out:
        if x in seen:
            continue
        seen.add(x)
        unique.append(x)
    return unique


def _produced_colors(payload: Dict) -> set[str]:
    colors = set()
    for c in payload.get("produced_mana") or []:
        uc = str(c).upper()
        if uc in MANA_ORDER:
            colors.add(uc)

    text = str(payload.get("oracle_text") or "")
    if text:
        for seg in _ADD_SEGMENT_RE.findall(text):
            for sym in _MANA_SYMBOL_RE.findall(seg):
                us = str(sym).upper()
                if us in MANA_ORDER:
                    colors.add(us)
        tl = text.lower()
        if "mana of any color" in tl:
            colors.update(["W", "U", "B", "R", "G"])
        if "mana of any type" in tl:
            colors.update(MANA_ORDER)
    return colors


def _source_weight(payload: Dict) -> float:
    type_line = str(payload.get("type_line") or "").lower()
    text = str(payload.get("oracle_text") or "").lower()
    mv = _safe_float(payload.get("cmc"), 0.0)
    is_land = "land" in type_line
    if is_land:
        if "enters the battlefield tapped unless" in text:
            return 0.92
        if "enters the battlefield tapped" in text:
            return 0.82
        return 1.0
    if "instant" in type_line or "sorcery" in type_line:
        return 0.18
    if mv <= 1:
        return 0.72
    if mv <= 2:
        return 0.62
    if mv <= 3:
        return 0.48
    if mv <= 4:
        return 0.35
    return 0.22


def _is_land_payload(payload: Dict) -> bool:
    return "land" in str(payload.get("type_line") or "").lower()


def _is_spell_payload(payload: Dict) -> bool:
    tl = str(payload.get("type_line") or "").lower()
    return ("instant" in tl) or ("sorcery" in tl)


def _mana_hit_lookup(sim_summary: Dict, turn: int, mana_value: int) -> float:
    gp = (sim_summary or {}).get("graph_payloads", {}) or {}
    table = gp.get("mana_hit_table") or []
    key = f"p_ge_{max(1, int(mana_value))}"
    for row in table:
        if int(row.get("turn", 0)) == int(turn):
            val = row.get(key)
            if isinstance(val, (float, int)):
                return float(val)

    # Fallback if hit-table is missing.
    mana_percentiles = gp.get("mana_percentiles") or []
    p50 = None
    for row in mana_percentiles:
        if int(row.get("turn", 0)) == int(turn):
            if isinstance(row.get("p50"), (float, int)):
                p50 = float(row["p50"])
                break
    if p50 is None:
        p50 = float((sim_summary.get("milestones") or {}).get("p_mana4_t3", 0.5) * 4.0)
    if mana_value <= 0:
        return 1.0
    rough = _clamp((p50 + 1.0) / max(1.0, float(mana_value + 1)), 0.0, 1.0)
    return rough


def _manabase_analysis(
    cards: List[CardEntry],
    commander_colors: List[str] | None,
    sim_summary: Dict,
    card_map: Dict[str, Dict] | None = None,
) -> Dict:
    card_map = card_map or {}
    ci = [c for c in (commander_colors or []) if c in ["W", "U", "B", "R", "G"]]
    is_colorless = len(ci) == 0
    display_colors = ["C"] if is_colorless else ci.copy()

    pip_totals = Counter()
    pip_early = Counter()
    pip_mid = Counter()
    pip_late = Counter()
    pip_cards: List[Dict] = []

    source_rows = {
        c: {"land_sources": 0.0, "nonland_sources": 0.0, "weighted_sources": 0.0}
        for c in MANA_ORDER
    }
    top_sources: Dict[str, List[Dict]] = {c: [] for c in MANA_ORDER}

    main_cards = [c for c in cards if c.section in {"deck", "commander"}]
    source_cards = [c for c in cards if c.section == "deck"]
    for entry in main_cards:
        payload = card_map.get(entry.name) or {}
        costs = _mana_costs_for_payload(payload)
        if not costs:
            continue
        mv = _safe_float(payload.get("cmc"), 0.0)
        per_cost_qty_weight = float(entry.qty) / max(1, len(costs))
        local = Counter()
        for cost in costs:
            for sym in _MANA_SYMBOL_RE.findall(cost):
                for k, w in _pip_weights_from_symbol(sym).items():
                    local[k] += w * per_cost_qty_weight
        for k, v in local.items():
            pip_totals[k] += v
            if mv <= 2:
                pip_early[k] += v
            elif mv <= 4:
                pip_mid[k] += v
            else:
                pip_late[k] += v
        tracked_colors = ci if ci else ["C", "GENERIC"]
        weighted_pressure = sum(local.get(c, 0.0) for c in tracked_colors)
        if weighted_pressure > 0:
            pip_cards.append(
                {
                    "card": entry.name,
                    "qty": entry.qty,
                    "mana_cost": payload.get("mana_cost") or "",
                    "mana_value": mv,
                    "pressure": round(weighted_pressure, 3),
                    "pips": {k: round(v, 3) for k, v in local.items() if k in MANA_ORDER},
                }
            )

    for entry in source_cards:
        payload = card_map.get(entry.name) or {}
        produced = _produced_colors(payload)
        if not produced:
            continue
        type_line = str(payload.get("type_line") or "").lower()
        is_land = "land" in type_line
        w = _source_weight(payload)
        for c in produced:
            if c not in source_rows:
                continue
            if is_land:
                source_rows[c]["land_sources"] += float(entry.qty)
            else:
                source_rows[c]["nonland_sources"] += float(entry.qty)
            source_rows[c]["weighted_sources"] += float(entry.qty) * w
            top_sources[c].append(
                {
                    "name": entry.name,
                    "qty": int(entry.qty),
                    "weight": round(float(entry.qty) * w, 3),
                    "is_land": is_land,
                    "produces": sorted([x for x in produced if x in MANA_ORDER]),
                }
            )

    if not is_colorless and (pip_totals.get("C", 0.0) > 0 or source_rows.get("C", {}).get("weighted_sources", 0.0) > 0):
        display_colors = ci + ["C"]

    pip_basis_colors = ci.copy()
    if is_colorless:
        pip_basis_colors = ["C", "GENERIC"]
    elif pip_totals.get("C", 0.0) > 0:
        pip_basis_colors.append("C")
    total_pip_basis = sum(pip_totals.get(c, 0.0) for c in pip_basis_colors) or 0.0
    source_basis_colors = ci.copy()
    if is_colorless:
        source_basis_colors = ["C"]
    elif source_rows.get("C", {}).get("weighted_sources", 0.0) > 0:
        source_basis_colors.append("C")
    if not source_basis_colors:
        source_basis_colors = ["C"]
    total_source_basis = sum(source_rows.get(c, {}).get("weighted_sources", 0.0) for c in source_basis_colors) or 0.0

    rows = []
    advisories: List[str] = []
    for c in display_colors:
        pips = pip_totals.get(c, 0.0)
        if c == "C" and is_colorless:
            pips += pip_totals.get("GENERIC", 0.0)
        demand_share = (pips / total_pip_basis) if total_pip_basis > 0 else 0.0
        weighted_sources = source_rows.get(c, {}).get("weighted_sources", 0.0)
        source_share = (weighted_sources / total_source_basis) if total_source_basis > 0 else 0.0
        gap = source_share - demand_share
        status = "ok"
        if pips > 0:
            if gap < -0.08:
                status = "under"
            elif gap < -0.03:
                status = "warning"
            elif gap > 0.12:
                status = "over"

        top = sorted(top_sources.get(c, []), key=lambda x: x["weight"], reverse=True)[:8]
        rows.append(
            {
                "color": c,
                "label": MANA_LABELS.get(c, c),
                "pips": round(pips, 3),
                "pips_early": round(pip_early.get(c, 0.0), 3),
                "pips_mid": round(pip_mid.get(c, 0.0), 3),
                "pips_late": round(pip_late.get(c, 0.0), 3),
                "demand_share": round(demand_share, 4),
                "demand_share_pct": round(demand_share * 100, 1),
                "land_sources": round(source_rows.get(c, {}).get("land_sources", 0.0), 2),
                "nonland_sources": round(source_rows.get(c, {}).get("nonland_sources", 0.0), 2),
                "weighted_sources": round(weighted_sources, 3),
                "source_share": round(source_share, 4),
                "source_share_pct": round(source_share * 100, 1),
                "gap": round(gap, 4),
                "gap_pct": round(gap * 100, 1),
                "status": status,
                "top_sources": top,
            }
        )
        if status in {"under", "warning"} and pips > 0:
            top_pressure_names = [
                x["card"]
                for x in sorted(
                    [pc for pc in pip_cards if _safe_float((pc.get("pips") or {}).get(c), 0.0) > 0],
                    key=lambda pc: _safe_float((pc.get("pips") or {}).get(c), 0.0),
                    reverse=True,
                )[:3]
            ]
            if top_pressure_names:
                advisories.append(
                    f"{MANA_LABELS.get(c, c)} demand is {round(demand_share * 100, 1)}% but supply is {round(source_share * 100, 1)}%. "
                    f"Add more reliable {MANA_LABELS.get(c, c)} sources or reduce early {MANA_LABELS.get(c, c)} pips in cards like {', '.join(top_pressure_names)}."
                )
            else:
                advisories.append(
                    f"{MANA_LABELS.get(c, c)} demand is above supply ({round(demand_share * 100, 1)}% vs {round(source_share * 100, 1)}%)."
                )

    rows = [
        r
        for r in rows
        if is_colorless or r["color"] != "C" or (r["pips"] > 0 or r["weighted_sources"] > 0)
    ]
    rows.sort(key=lambda x: (MANA_ORDER.index(x["color"]) if x["color"] in MANA_ORDER else 99))
    pip_cards.sort(key=lambda x: x["pressure"], reverse=True)

    row_by_color = {r["color"]: r for r in rows}
    curve_buckets: Dict[int, Dict] = {}
    curve_cards_by_mv: Dict[str, List[Dict]] = defaultdict(list)
    expanded_mv_with_lands: List[float] = []
    expanded_mv_without_lands: List[float] = []
    total_mv_with_lands = 0.0
    total_mv_without_lands = 0.0
    turn_limit = int((sim_summary or {}).get("turn_limit", 8) or 8)

    for entry in source_cards:
        payload = card_map.get(entry.name) or {}
        mv = _safe_float(payload.get("cmc"), 0.0)
        is_land = _is_land_payload(payload)
        if is_land:
            total_mv_with_lands += 0.0
            expanded_mv_with_lands.extend([0.0] * int(entry.qty))
            continue

        qty = int(entry.qty)
        total_mv_with_lands += mv * qty
        total_mv_without_lands += mv * qty
        expanded_mv_with_lands.extend([mv] * qty)
        expanded_mv_without_lands.extend([mv] * qty)

        costs = _mana_costs_for_payload(payload)
        local = Counter()
        for cost in costs:
            for sym in _MANA_SYMBOL_RE.findall(cost):
                for k, w in _pip_weights_from_symbol(sym).items():
                    local[k] += w
        req_colors = [c for c in ["W", "U", "B", "R", "G", "C"] if local.get(c, 0.0) > 0]

        mv_bucket = int(round(mv))
        on_turn = max(1, min(turn_limit, mv_bucket if mv_bucket > 0 else 1))
        base_prob = _mana_hit_lookup(sim_summary, on_turn, max(1, mv_bucket))
        color_factor = 1.0
        if req_colors:
            factors = []
            for c in req_colors:
                rr = row_by_color.get(c)
                if rr is None:
                    factors.append(0.75)
                    continue
                demand_share = _safe_float(rr.get("demand_share"), 0.0)
                source_share = _safe_float(rr.get("source_share"), 0.0)
                if demand_share <= 0:
                    factors.append(1.0)
                else:
                    factors.append(_clamp(source_share / demand_share, 0.45, 1.2))
            if factors:
                color_factor = min(factors)
        p_on_curve = _clamp(base_prob * color_factor, 0.0, 1.0)

        group = "spells" if _is_spell_payload(payload) else "permanents"
        bucket = curve_buckets.setdefault(
            mv_bucket,
            {
                "mana_value": mv_bucket,
                "permanents": 0,
                "spells": 0,
                "total": 0,
                "on_curve_weighted_sum": 0.0,
                "on_curve_weighted_count": 0,
            },
        )
        bucket[group] += qty
        bucket["total"] += qty
        bucket["on_curve_weighted_sum"] += p_on_curve * qty
        bucket["on_curve_weighted_count"] += qty

        curve_cards_by_mv[str(mv_bucket)].append(
            {
                "card": entry.name,
                "qty": qty,
                "mana_cost": payload.get("mana_cost") or "",
                "mana_value": mv,
                "group": group,
                "p_on_curve_est": round(p_on_curve, 4),
            }
        )

    curve_histogram = []
    for mv in sorted(curve_buckets.keys()):
        row = curve_buckets[mv]
        p_on_curve = 0.0
        if row["on_curve_weighted_count"] > 0:
            p_on_curve = row["on_curve_weighted_sum"] / row["on_curve_weighted_count"]
        curve_histogram.append(
            {
                "mana_value": mv,
                "permanents": row["permanents"],
                "spells": row["spells"],
                "total": row["total"],
                "p_on_curve_est": round(p_on_curve, 4),
            }
        )

    avg_with_lands = (sum(expanded_mv_with_lands) / len(expanded_mv_with_lands)) if expanded_mv_with_lands else 0.0
    avg_without_lands = (sum(expanded_mv_without_lands) / len(expanded_mv_without_lands)) if expanded_mv_without_lands else 0.0
    median_with_lands = median(expanded_mv_with_lands) if expanded_mv_with_lands else 0.0
    median_without_lands = median(expanded_mv_without_lands) if expanded_mv_without_lands else 0.0

    most_stressed = next((r for r in sorted(rows, key=lambda r: r["gap"]) if r["status"] in {"under", "warning"}), None)
    summary = {
        "total_colored_pips": round(sum(pip_totals.get(c, 0.0) for c in ["W", "U", "B", "R", "G"]), 3),
        "total_colorless_pips": round(pip_totals.get("C", 0.0) + pip_totals.get("GENERIC", 0.0), 3),
        "total_weighted_sources": round(sum(source_rows[c]["weighted_sources"] for c in MANA_ORDER), 3),
        "most_stressed_color": most_stressed["color"] if most_stressed else None,
        "most_stressed_gap_pct": most_stressed["gap_pct"] if most_stressed else 0.0,
        "average_mana_value_with_lands": round(avg_with_lands, 3),
        "average_mana_value_without_lands": round(avg_without_lands, 3),
        "median_mana_value_with_lands": round(float(median_with_lands), 3),
        "median_mana_value_without_lands": round(float(median_without_lands), 3),
        "total_mana_value_with_lands": round(total_mv_with_lands, 1),
        "total_mana_value_without_lands": round(total_mv_without_lands, 1),
    }

    graph_payloads = {
        "manabase_pip_distribution": [
            {
                "color": r["color"],
                "label": r["label"],
                "pips": r["pips"],
                "share": r["demand_share"],
                "early": r["pips_early"],
                "mid": r["pips_mid"],
                "late": r["pips_late"],
            }
            for r in rows
        ],
        "manabase_source_coverage": [
            {
                "color": r["color"],
                "label": r["label"],
                "land_sources": r["land_sources"],
                "nonland_sources": r["nonland_sources"],
                "weighted_sources": r["weighted_sources"],
            }
            for r in rows
        ],
        "manabase_balance_gap": [
            {
                "color": r["color"],
                "label": r["label"],
                "demand_share": r["demand_share"],
                "source_share": r["source_share"],
                "gap": r["gap"],
                "gap_pct": r["gap_pct"],
            }
            for r in rows
        ],
        "curve_histogram": curve_histogram,
    }

    graph_blurbs = {
        "manabase_pip_distribution": (
            "This deck's mana symbols are concentrated in "
            + (MANA_LABELS.get(most_stressed["color"], most_stressed["color"]) if most_stressed else "multiple colors")
            + ". If early pips are concentrated, prioritize untapped sources and two-mana fixing."
        ),
        "manabase_source_coverage": (
            "Land sources are your reliable baseline; nonland sources are acceleration. "
            "If nonland is high but land sources are low, the deck becomes mulligan-sensitive."
        ),
        "manabase_balance_gap": (
            "Negative gap means color demand is higher than source share. "
            "Fix the most negative color first before adding more high-pip spells."
        ),
        "curve_histogram": (
            "This curve combines card counts by mana value with estimated on-curve cast chance. "
            "High bars in expensive slots are fine only if on-curve estimates stay healthy for your intended pod speed."
        ),
    }

    return {
        "summary": summary,
        "rows": rows,
        "top_pip_cards": pip_cards[:20],
        "curve": {
            "histogram": curve_histogram,
            "cards_by_mv": {k: v for k, v in curve_cards_by_mv.items()},
        },
        "advisories": advisories[:10],
        "graph_payloads": graph_payloads,
        "graph_blurbs": graph_blurbs,
        "methodology": [
            "Pips are parsed from mana costs and split hybrid symbols across their colors.",
            "Source counts come from cards that can produce mana (land and nonland shown separately).",
            "Weighted sources discount slow/non-permanent mana so early reliability is not overstated.",
            "Demand and source shares can exceed 100% when summed across colors because dual/flexible sources count for each color they can provide.",
        ],
    }


def _role_counts(cards: List[CardEntry]) -> Counter:
    counts = Counter()
    for c in cards:
        if c.section not in {"deck", "commander"}:
            continue
        for t in set(c.tags):
            counts[t] += c.qty
    return counts


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _weighted_target(role: str, weights: Dict[str, float]) -> float:
    return sum(weights.get(p, 0.0) * ROLE_PHILOSOPHY_TARGETS[p][role] for p in ROLE_PHILOSOPHY_TARGETS)


def _role_target_model(
    cards: List[CardEntry],
    sim_summary: Dict,
    combo_intel: Dict | None,
    bracket: int,
    color_count: int,
) -> Dict:
    role_counts = _role_counts(cards)
    combo_support = float((combo_intel or {}).get("combo_support_score", 0.0))
    win_metrics = sim_summary.get("win_metrics", {})
    wincon = (win_metrics.get("most_common_wincon") or "").lower()
    p4 = float(sim_summary.get("milestones", {}).get("p_mana4_t3", 0.0))
    pwin = float(win_metrics.get("p_win_by_turn_limit", 0.0))
    no_action = float(sim_summary.get("failure_modes", {}).get("no_action", 0.0))

    raw = {
        "proactive_combo": (
            role_counts.get("#Combo", 0) * 1.35
            + role_counts.get("#Tutor", 0) * 1.1
            + role_counts.get("#Protection", 0) * 0.5
            + combo_support * 0.12
            + (1.8 if "combo" in wincon else 0.0)
            + bracket * 0.55
        ),
        "control_attrition": (
            role_counts.get("#Removal", 0) * 1.0
            + role_counts.get("#Counter", 0) * 1.15
            + role_counts.get("#Boardwipe", 0) * 1.25
            + role_counts.get("#Draw", 0) * 0.55
            + (1.1 if "control" in wincon or "lock" in wincon else 0.0)
        ),
        "midrange_value": (
            role_counts.get("#Engine", 0) * 1.1
            + role_counts.get("#Draw", 0) * 1.0
            + role_counts.get("#Recursion", 0) * 0.75
            + role_counts.get("#Payoff", 0) * 0.45
            + max(0.0, (0.62 - no_action) * 3.0)
        ),
        "battlecruiser_value": (
            role_counts.get("#Wincon", 0) * 0.95
            + role_counts.get("#Payoff", 0) * 0.85
            + role_counts.get("#Ramp", 0) * 0.45
            + max(0.0, (1.0 - pwin) * 3.0)
            + (0.8 if bracket <= 2 else 0.0)
        ),
        "stax_resource": (
            role_counts.get("#Stax", 0) * 1.5
            + role_counts.get("#Tax", 0) * 1.3
            + role_counts.get("#Protection", 0) * 0.5
            + role_counts.get("#Counter", 0) * 0.5
        ),
    }
    total_raw = sum(max(0.0, v) for v in raw.values()) or 1.0
    weights = {k: round(max(0.0, v) / total_raw, 3) for k, v in raw.items()}
    primary = max(weights.items(), key=lambda kv: kv[1])[0]

    targets: Dict[str, Dict] = {}
    for role in CORE_TARGET_ROLES:
        center = _weighted_target(role, weights)
        span = 2.0
        if role in {"#Tutor", "#Boardwipe", "#Counter"}:
            span = 1.5
        if role == "#Land":
            span = 2.5

        # Board wipes should not be hard-universal: tune by proactive vs control posture.
        if role == "#Boardwipe":
            proactive_bias = weights["proactive_combo"] + 0.6 * weights["battlecruiser_value"]
            control_bias = weights["control_attrition"] + weights["stax_resource"]
            center = 0.8 + 5.0 * control_bias + 1.4 * weights["midrange_value"] - 1.5 * proactive_bias
            center = _clamp(center, 0.0, 6.0)
            min_target = int(round(_clamp(center - 1.2, 0.0, 5.0)))
            max_target = int(round(_clamp(center + 1.8, min_target, 8.0)))
            targets[role] = {
                "min": min_target,
                "target": int(round(center)),
                "max": max_target,
                "reason": "Boardwipe target is strategy-dependent: proactive lists can run very few; control shells typically need more.",
            }
            continue

        if role == "#Tutor":
            center = _clamp(center, 0.0, 9.0)
            if bracket <= 2:
                center = min(center, 2.0)
            elif bracket == 3:
                center = min(center, 4.0)
        elif role == "#Fixing":
            if color_count <= 1:
                center = _clamp(center * 0.4, 0.0, 5.0)
            elif color_count >= 4:
                center += 1.0
        elif role == "#Land":
            # Slow starts raise land target slightly; very fast proactive plans can shave one.
            center += _clamp((0.52 - p4) * 8.0, -1.0, 2.0)
            if weights["proactive_combo"] > 0.5 and bracket >= 4:
                center -= 1.0
            center = _clamp(center, 32.0, 39.0)

        center = _clamp(center, 0.0, 40.0)
        min_target = int(round(max(0.0, center - span)))
        max_target = int(round(max(float(min_target), center + span)))
        targets[role] = {
            "min": min_target,
            "target": int(round(center)),
            "max": max_target,
            "reason": "Adaptive target derived from deck tags, simulation outcomes, and strategy profile.",
        }

    return {
        "primary_philosophy": primary,
        "philosophy_weights": weights,
        "role_targets": targets,
        "notes": [
            "Not all categories are equally important for every deck.",
            "Boardwipes are treated as strategy-dependent, not a universal fixed quota.",
            "Targets are ranges; missing the exact center is not automatically wrong.",
        ],
    }


def _role_gap_list_from_model(cards: List[CardEntry], role_model: Dict) -> List[Dict]:
    role_counts = _role_counts(cards)
    role_targets = role_model.get("role_targets", {})
    gaps: List[Dict] = []
    for role, meta in role_targets.items():
        have = int(role_counts.get(role, 0))
        min_target = int(meta.get("min", 0))
        target = int(meta.get("target", min_target))
        max_target = int(meta.get("max", target))
        if have < min_target:
            gaps.append(
                {
                    "role": role,
                    "have": have,
                    "target": target,
                    "min_target": min_target,
                    "max_target": max_target,
                    "missing": min_target - have,
                    "reason": meta.get("reason", ""),
                }
            )
    gaps.sort(key=lambda x: x.get("missing", 0), reverse=True)
    return gaps


def _role_cards_map(cards: List[CardEntry], focus_roles: List[str]) -> Dict[str, List[Dict]]:
    out = {r: [] for r in focus_roles}
    for c in cards:
        if c.section not in {"deck", "commander"}:
            continue
        tags = set(c.tags)
        for role in focus_roles:
            if role in tags:
                out[role].append({"name": c.name, "qty": c.qty, "section": c.section})
    for role in out:
        out[role] = sorted(out[role], key=lambda x: (-x["qty"], x["name"]))[:40]
    return out


def role_breakdown(cards: List[CardEntry]) -> Dict:
    role_counts = Counter()
    cmc_buckets = defaultdict(int)
    land_count = 0
    for c in cards:
        if c.section not in {"deck", "commander"}:
            continue
        for t in set(c.tags):
            role_counts[t] += c.qty
        if "#Land" in c.tags:
            land_count += c.qty

    return {
        "roles": dict(role_counts),
        "lands": land_count,
        "curve": dict(cmc_buckets),
    }


def importance_scores(cards: List[CardEntry], sim_summary: Dict) -> List[Dict]:
    impacts = sim_summary.get("card_impacts", {})
    ranked = []
    for c in cards:
        if c.section not in {"deck", "commander"}:
            continue
        seen = impacts.get(c.name, {}).get("seen_lift", 0.0)
        cast = impacts.get(c.name, {}).get("cast_lift", 0.0)
        centrality = impacts.get(c.name, {}).get("centrality", 0.0)
        redundancy = impacts.get(c.name, {}).get("redundancy", 0.5)
        score = round((seen * 0.35 + cast * 0.35 + centrality * 0.2 + (1 - redundancy) * 0.1), 4)
        ranked.append(
            {
                "card": c.name,
                "score": score,
                "explanation": f"seen={seen:.2f}, cast={cast:.2f}, centrality={centrality:.2f}, redundancy={redundancy:.2f}",
                "tags": c.tags,
            }
        )

    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked


def _role_gap_list(cards: List[CardEntry], template: str) -> List[Dict]:
    targets = ROLE_TARGETS.get(template, ROLE_TARGETS["balanced"])
    role_counts = Counter()
    for c in cards:
        for t in set(c.tags):
            role_counts[t] += c.qty
    gaps = []
    for tag, target in targets.items():
        have = role_counts.get(tag, 0)
        if have < target:
            gaps.append({"role": tag, "have": have, "target": target, "missing": target - have})
    return gaps


def _find_replaceable(cards: List[CardEntry], low_cards: List[Dict]) -> List[Dict]:
    commander_names = {c.name for c in cards if c.section == "commander"}
    out = []
    for item in low_cards[:10]:
        card_name = item["card"]
        if card_name in commander_names:
            continue
        tags = set(item.get("tags", []))
        if "#Removal" in tags or "#Counter" in tags:
            label = "Low impact but necessary interaction"
        else:
            label = "Low impact and replaceable"
        out.append({"card": card_name, "reason": label, "score": item["score"]})
    return out


def _to_float(x, default=None):
    try:
        return float(x)
    except Exception:
        return default


def _card_ci_set(card: Dict) -> set[str]:
    ci = set(card.get("color_identity") or [])
    if ci:
        return ci
    # Defensive fallback: if color_identity is unexpectedly absent, derive from colors.
    return set(card.get("colors") or [])


def _card_matches_role(card: Dict, role: str) -> bool:
    txt = f"{card.get('type_line', '')} {card.get('oracle_text', '')}".lower()
    type_line = (card.get("type_line") or "").lower()
    # If metadata is sparse (e.g., mocked/test payloads), do not hard-fail role matching.
    if not txt.strip():
        return True
    if role == "#Ramp":
        return ("add {" in txt or "add one mana" in txt or "search your library for a land" in txt) and "land" not in type_line
    if role == "#Draw":
        return ("draw" in txt) or ("exile the top" in txt and "you may play" in txt)
    if role == "#Removal":
        return ("destroy target" in txt) or ("exile target" in txt) or ("return target" in txt and "to its owner's hand" in txt)
    if role == "#Protection":
        return any(k in txt for k in ["hexproof", "indestructible", "phase out", "protection from", "ward"])
    if role == "#Boardwipe":
        return any(k in txt for k in ["destroy all", "exile all", "each creature", "all creatures"])
    if role == "#Tutor":
        return "search your library" in txt
    if role == "#Counter":
        return "counter target" in txt
    if role == "#Wincon":
        return any(k in txt for k in ["you win the game", "each opponent loses", "combat damage to a player", "infinite"])
    return True


def _candidate_allowed(
    card: Dict,
    commander_ci_set: set[str],
    budget_max_usd: float | None,
) -> tuple[bool, float | None]:
    ci = _card_ci_set(card)
    if commander_ci_set:
        if not ci.issubset(commander_ci_set):
            return False, None
    else:
        if ci:
            return False, None
    usd = _to_float((card.get("prices") or {}).get("usd"), default=None)
    if budget_max_usd is not None:
        if usd is None or usd > budget_max_usd:
            return False, usd
    return True, usd


def _strict_filter_adds(
    cards: List[CardEntry],
    adds: List[Dict],
    commander_ci: str,
    budget_max_usd: float | None,
) -> List[Dict]:
    svc = CardDataService()
    deck_names = {c.name for c in cards if c.section in {"deck", "commander"}}
    out: List[Dict] = []
    seen = set()
    names = [a.get("card") for a in adds if a.get("card")]
    card_map = svc.get_cards_by_name(names)
    commander_ci_set = set((commander_ci or "").upper())

    for a in adds:
        name = a.get("card")
        if not name or name in deck_names or name in seen:
            continue
        card = card_map.get(name, {})
        if card:
            allowed, usd = _candidate_allowed(card, commander_ci_set, budget_max_usd)
            if not allowed:
                continue
            role = a.get("fills")
            if role and role.startswith("#") and not _card_matches_role(card, role):
                continue
            if budget_max_usd is not None:
                a["budget_note"] = f"{usd:.2f}" if isinstance(usd, (int, float)) else "n/a"
        else:
            # Preserve unknown cards only when constraints can still be respected.
            if budget_max_usd is not None:
                continue
            if commander_ci_set:
                # Cannot prove CI compliance without card metadata.
                continue
            a["source_warning"] = "Card metadata unavailable; recommendation kept without CI/budget verification."
        seen.add(name)
        out.append(a)
    return out


def suggest_adds(
    cards: List[CardEntry],
    commander_ci: str,
    gaps: List[Dict],
    bracket: int,
    budget_max_usd: float | None = None,
    commander: str | None = None,
) -> List[Dict]:
    svc = CardDataService()
    out: List[Dict] = []
    commander_ci_set = set((commander_ci or "").upper())
    deck_names = {c.name for c in cards if c.section in {"deck", "commander"}}
    edhrec_payload = EDHRecService().get_commander_cards(commander, limit=140) if commander else {"cards": []}
    edhrec_rank = {x.get("name"): idx for idx, x in enumerate(edhrec_payload.get("cards", []))}
    edhrec_names = [x.get("name") for x in (edhrec_payload.get("cards") or []) if x.get("name")]
    edhrec_map = svc.get_cards_by_name(edhrec_names[:100]) if edhrec_names else {}

    role_to_query = {
        "#Ramp": "t:artifact o:'add {' mv<=3",
        "#Draw": "o:'draw' mv<=4",
        "#Removal": "(o:'destroy target' or o:'exile target') mv<=4",
        "#Protection": "o:(hexproof or indestructible or 'phase out' or ward) mv<=4",
        "#Boardwipe": "o:'destroy all' mv<=6",
        "#Tutor": "o:'search your library' mv<=4",
        "#Counter": "o:'counter target' mv<=3",
    }

    seen = set()
    for gap in gaps[:10]:
        role = gap["role"]
        q = role_to_query.get(role)
        role_candidates: List[Dict] = []

        if q:
            candidates = svc.search_candidates(q, commander_ci, limit=10)
        else:
            candidates = []
        for cand in candidates:
            cand_name = cand.get("name")
            if not cand_name or cand_name in deck_names or cand_name in seen:
                continue
            allowed, usd = _candidate_allowed(cand, commander_ci_set, budget_max_usd)
            if not allowed or not _card_matches_role(cand, role):
                continue
            role_candidates.append(
                {
                    "card": cand_name,
                    "fills": role,
                    "why": f"Improves {role} density for current template target.",
                    "bracket_impact": "Check Game Changer status before inclusion.",
                    "is_game_changer": False,
                    "budget_note": f"{usd:.2f}" if isinstance(usd, (int, float)) else "n/a",
                    "source": "heuristic",
                    "_score": 1.0,
                }
            )

        # EDHREC enrichment (mixed with heuristics, never replacing them).
        for name, card in edhrec_map.items():
            if not name or name in deck_names or name in seen:
                continue
            if not _card_matches_role(card, role):
                continue
            allowed, usd = _candidate_allowed(card, commander_ci_set, budget_max_usd)
            if not allowed:
                continue
            rank = edhrec_rank.get(name, 999)
            score = 0.82 - min(0.6, rank * 0.0025)
            role_candidates.append(
                {
                    "card": name,
                    "fills": role,
                    "why": f"Matches {role} gap and appears frequently in EDHREC commander recommendations.",
                    "bracket_impact": "Check Game Changer status before inclusion.",
                    "is_game_changer": False,
                    "budget_note": f"{usd:.2f}" if isinstance(usd, (int, float)) else "n/a",
                    "source": "edhrec+heuristic",
                    "_score": score,
                }
            )

        role_candidates.sort(key=lambda x: (-float(x.get("_score", 0.0)), x.get("card", "")))
        picked = 0
        for c in role_candidates:
            if c["card"] in seen:
                continue
            seen.add(c["card"])
            c.pop("_score", None)
            out.append(c)
            picked += 1
            # Keep role advice aligned and concise.
            if picked >= 2:
                break

    return out[:10]


def _status_from_score(score: float) -> str:
    if score >= 75:
        return "healthy"
    if score >= 55:
        return "warning"
    return "critical"


def _health_summary(cards: List[CardEntry], rb: Dict, sim_summary: Dict, consistency_score: float, combo_intel: Dict | None = None) -> Dict:
    roles = rb.get("roles", {})
    p4t3 = sim_summary.get("milestones", {}).get("p_mana4_t3", 0.0)
    mana_screw = sim_summary.get("failure_modes", {}).get("mana_screw", 0.0)
    no_action = sim_summary.get("failure_modes", {}).get("no_action", 0.0)
    interaction = roles.get("#Removal", 0) + roles.get("#Counter", 0) + roles.get("#Boardwipe", 0)
    win_metrics = sim_summary.get("win_metrics", {})
    winconf = win_metrics.get("wincon_distribution", {})
    plan_clarity_score = min(100.0, 40.0 + max(0, 30 - len(winconf) * 6) + (20 if win_metrics.get("most_common_wincon") else 0))
    interaction_score = max(0.0, min(100.0, interaction * 4.5))
    mana_score = max(0.0, min(100.0, p4t3 * 100 - mana_screw * 60))
    early_score = max(0.0, min(100.0, (1 - no_action) * 100))

    return {
        "mana_base_stability": {
            "score": round(mana_score, 1),
            "status": _status_from_score(mana_score),
            "explanation": f"P(4 mana by T3)={p4t3:.1%}, mana screw={mana_screw:.1%}.",
        },
        "early_game_reliability": {
            "score": round(early_score, 1),
            "status": _status_from_score(early_score),
            "explanation": f"No-action starts={no_action:.1%}.",
        },
        "interaction_density": {
            "score": round(interaction_score, 1),
            "status": _status_from_score(interaction_score),
            "explanation": f"Interaction tags total={interaction}.",
        },
        "game_plan_clarity": {
            "score": round(plan_clarity_score, 1),
            "status": _status_from_score(plan_clarity_score),
            "explanation": f"Most common win line={win_metrics.get('most_common_wincon') or 'n/a'}.",
        },
        "combo_support_level": {
            "score": round(float((combo_intel or {}).get("combo_support_score", 0.0)), 1),
            "status": _status_from_score(float((combo_intel or {}).get("combo_support_score", 0.0)),
            ),
            "explanation": (
                f"CommanderSpellbook complete lines={len((combo_intel or {}).get('matched_variants', []))}, "
                f"near misses={len((combo_intel or {}).get('near_miss_variants', []))}."
            ),
        },
        "deck_consistency": {
            "score": round(consistency_score, 1),
            "status": _status_from_score(consistency_score),
            "explanation": "Composite from mana stability, no-action, and flood risk.",
        },
    }


def _consistency_score(sim_summary: Dict) -> float:
    fm = sim_summary.get("failure_modes", {})
    p4 = sim_summary.get("milestones", {}).get("p_mana4_t3", 0.0)
    p5 = sim_summary.get("milestones", {}).get("p_mana5_t4", 0.0)
    mana_screw = fm.get("mana_screw", 0.0)
    flood = fm.get("flood", 0.0)
    no_action = fm.get("no_action", 0.0)
    score = 100.0
    score -= mana_screw * 45
    score -= flood * 20
    score -= no_action * 30
    score -= max(0.0, 0.55 - p4) * 30
    score -= max(0.0, 0.45 - p5) * 15
    return round(max(0.0, min(100.0, score)), 1)


def _pick_names_by_tags(cards: List[CardEntry], tags: set[str], preferred: List[str] | None = None, limit: int = 6) -> List[str]:
    preferred = preferred or []
    preferred_set = set(preferred)
    out: List[str] = []
    seen = set()

    # First pass: keep high-priority cards in given order.
    for name in preferred:
        entry = next((c for c in cards if c.name == name and c.section in {"deck", "commander"}), None)
        if entry is None:
            continue
        if not (set(entry.tags) & tags):
            continue
        if name in seen:
            continue
        out.append(name)
        seen.add(name)
        if len(out) >= limit:
            return out

    # Second pass: fill from full deck order.
    for c in cards:
        if c.section not in {"deck", "commander"}:
            continue
        if c.name in seen:
            continue
        if not (set(c.tags) & tags):
            continue
        # If we have preferred cards list, lightly prioritize those cards first.
        if preferred_set and c.name not in preferred_set and len(out) < max(1, limit // 2):
            continue
        out.append(c.name)
        seen.add(c.name)
        if len(out) >= limit:
            break

    # Final fallback: if still empty, take matching cards regardless of preferred bias.
    if not out:
        for c in cards:
            if c.section not in {"deck", "commander"}:
                continue
            if c.name in seen:
                continue
            if set(c.tags) & tags:
                out.append(c.name)
                seen.add(c.name)
                if len(out) >= limit:
                    break
    return out


def _intent_summary(
    commander: str | None,
    cards: List[CardEntry],
    sim_summary: Dict,
    combo_intel: Dict | None,
    importance: List[Dict] | None = None,
    type_profile: Dict | None = None,
) -> Dict:
    role_counts = Counter()
    for c in cards:
        if c.section not in {"deck", "commander"}:
            continue
        for t in set(c.tags):
            role_counts[t] += c.qty

    supported_vectors = list((sim_summary.get("selected_wincons") or []))
    primary_plan = "Value Midrange"
    secondary = "Combat Pressure"
    kill_vectors = supported_vectors or ["Combat"]
    type_profile = type_profile or {}
    dominant_creature_subtype = type_profile.get("dominant_creature_subtype") or {}
    subtype_name = str(dominant_creature_subtype.get("name") or "").strip()
    card_type_counts = {
        str(row.get("name", "")).lower(): int(row.get("count", 0) or 0)
        for row in (type_profile.get("card_types") or [])
    }
    subtype_counts = {
        str(row.get("name", "")).lower(): int(row.get("count", 0) or 0)
        for row in (type_profile.get("subtypes") or [])
    }
    if "Combo" in kill_vectors or role_counts.get("#Combo", 0) >= 5 or (combo_intel or {}).get("matched_variants"):
        primary_plan = "Combo Assembly"
        secondary = "Value Engine Backup"
    elif "Commander Damage" in kill_vectors:
        primary_plan = "Voltron Pressure"
        secondary = "Combat Backup"
    elif "Poison" in kill_vectors:
        primary_plan = "Poison Tempo"
        secondary = "Combat Backup"
    elif "Drain/Burn" in kill_vectors:
        primary_plan = "Life-Drain Attrition"
        secondary = "Engine Value"
    elif "Mill" in kill_vectors:
        primary_plan = "Mill Pressure"
        secondary = "Control Backup"
    elif "Control Lock" in kill_vectors or role_counts.get("#Control", 0) + role_counts.get("#Counter", 0) >= 8:
        primary_plan = "Control into Inevitable Finish"
        secondary = "Commander Value"
    elif subtype_name and int(dominant_creature_subtype.get("count", 0) or 0) >= 6:
        primary_plan = f"{subtype_name} Typal Pressure"
        secondary = "Board Development Backup"
    elif subtype_counts.get("equipment", 0) >= 4 or subtype_counts.get("aura", 0) >= 4:
        primary_plan = "Voltron Board Pressure"
        secondary = "Commander-Led Backup"
    elif card_type_counts.get("artifact", 0) >= 12:
        primary_plan = "Artifact Value Engine"
        secondary = "Combo or Board Backup" if "#Combo" in role_counts else "Board Development Backup"
    elif card_type_counts.get("enchantment", 0) >= 10:
        primary_plan = "Enchantment Value Engine"
        secondary = "Board Development Backup"

    milestones = sim_summary.get("milestones", {})
    preferred_cards = [x.get("card") for x in (importance or []) if x.get("card")]

    key_support_cards = _pick_names_by_tags(cards, {"#Ramp", "#Fixing", "#Draw", "#Tutor", "#Setup"}, preferred=preferred_cards, limit=6)
    key_engine_cards = _pick_names_by_tags(cards, {"#Engine"}, preferred=preferred_cards, limit=6)
    main_wincon_cards = _pick_names_by_tags(cards, {"#Wincon", "#Payoff", "#Combo"}, preferred=preferred_cards, limit=6)
    key_interaction_cards = _pick_names_by_tags(cards, {"#Removal", "#Counter", "#Boardwipe", "#Protection", "#StackInteraction"}, preferred=preferred_cards, limit=6)

    required_resources = [
        f"Hit 4 mana by T3 ({milestones.get('p_mana4_t3', 0):.1%})",
        f"Commander by median turn {milestones.get('median_commander_cast_turn', 'n/a')}",
    ]
    combo_evidence = [
        {
            "variant_id": v.get("variant_id"),
            "present_cards": v.get("present_cards", [])[:4],
            "missing_cards": v.get("missing_cards", [])[:2],
            "score": v.get("score", 0),
        }
        for v in ((combo_intel or {}).get("matched_variants", []) + (combo_intel or {}).get("near_miss_variants", []))[:5]
    ]
    confidence = 0.55
    if combo_evidence:
        confidence += 0.2
    if role_counts.get("#Engine", 0) >= 8:
        confidence += 0.1
    confidence = round(min(1.0, confidence), 3)

    combo_lines = []
    for v in (combo_intel or {}).get("matched_variants", [])[:4]:
        combo_lines.append(
            {
                "variant_id": v.get("variant_id"),
                "status": "complete",
                "present_cards": v.get("present_cards", [])[:6],
                "missing_cards": [],
            }
        )
    for v in (combo_intel or {}).get("near_miss_variants", [])[:4]:
        combo_lines.append(
            {
                "variant_id": v.get("variant_id"),
                "status": "near_miss",
                "present_cards": v.get("present_cards", [])[:6],
                "missing_cards": v.get("missing_cards", [])[:2],
            }
        )

    return {
        "commander": commander,
        "primary_plan": primary_plan,
        "secondary_plan": secondary,
        "kill_vectors": kill_vectors,
        "critical_engines": key_engine_cards,
        "key_support_cards": key_support_cards,
        "key_engine_cards": key_engine_cards,
        "main_wincon_cards": main_wincon_cards,
        "key_interaction_cards": key_interaction_cards,
        "combo_lines": combo_lines,
        "required_resources": required_resources,
        "confidence": confidence,
        "evidence": {
            "top_tags": role_counts.most_common(6),
            "combo_evidence": combo_evidence,
            "type_signals": type_profile,
        },
        "combo_evidence": combo_evidence,
        "combo_confidence_boost": round(min(0.35, len(combo_evidence) * 0.08), 3),
        "type_signals": type_profile,
    }


def _actionable_actions(gaps: List[Dict], combo_intel: Dict | None) -> List[Dict]:
    actions: List[Dict] = []
    for g in gaps[:4]:
        actions.append(
            {
                "title": f"Increase {g['role']} density",
                "priority": "high" if g["missing"] >= 3 else "medium",
                "reason": f"{g['role']} is below target ({g['have']}/{g['target']}).",
            }
        )
    near = (combo_intel or {}).get("near_miss_variants", [])
    if near:
        top = near[0]
        actions.append(
            {
                "title": "Complete near-miss combo line",
                "priority": "medium",
                "reason": f"{top.get('variant_id')} is missing {', '.join(top.get('missing_cards', [])[:2])}.",
                "variant_id": top.get("variant_id"),
            }
        )
    if (combo_intel or {}).get("matched_variants"):
        actions.append(
            {
                "title": "Protect existing combo line",
                "priority": "medium",
                "reason": "Complete lines are present; add protection/tutor redundancy before adding more finishers.",
            }
        )
    return actions[:8]


def _graph_explanations(sim_summary: Dict) -> Dict[str, str]:
    milestones = sim_summary.get("milestones", {})
    p4 = milestones.get("p_mana4_t3", 0.0)
    mana_note = "Good early mana pacing." if p4 >= 0.55 else "Mana pacing is behind target; add low-curve ramp/fixing."
    ci_size = int(sim_summary.get("color_profile", {}).get("color_identity_size", 3) or 0)
    if ci_size <= 1:
        color_access_explainer = "Color-access pressure is minimal in colorless/mono-color decks; prioritize total mana and curve consistency over fixing density."
    elif ci_size == 2:
        color_access_explainer = "Track how quickly both colors become consistently available. Delayed second color means your dual/fetch/fixing package is too thin."
    else:
        color_access_explainer = "Track probability of having all commander colors available by turn. Low full-identity access means color screw risk."
    return {
        "mana_percentiles": "Shows your mana growth by turn (median and upper percentiles). If this climbs slowly before turn 4, trim top-end and add cheap ramp.",
        "land_hit_cdf": "Probability of hitting your natural on-curve land drops by turn. If this falls below 70% by turn 3, increase lands or draw smoothing.",
        "color_access": color_access_explainer,
        "phase_timeline": "Deck phases over turns: setup, engine, then win attempts. You want setup shrinking by turns 4-5 as engine/win phases rise.",
        "no_action_funnel": "Percent of games with no cast actions each turn. High T1-T3 no-action rates indicate clunky curve or insufficient cheap setup.",
        "action_rate": "How often each turn contains at least one action. Flat or dropping action rates suggest dead draws or poor sequencing support.",
        "win_turn_cdf": "Cumulative chance to have a win line by each turn. Compare this against your pod speed expectations.",
        "commander_cast_distribution": "Distribution of commander cast timing. Wide spread means opening consistency is low or commander timing policy is mismatched.",
        "engine_online_distribution": "When repeatable draw/value engines appear. Late engine turns imply your deck spins up too slowly.",
        "mulligan_funnel": "How often hands are kept after 0, 1, or 2+ mulligans. High deep-mulligan rates indicate fragile openers.",
        "dead_cards_top": f"Cards most often stranded in hand. {mana_note}",
        "manabase_pip_distribution": "Mana symbols required by your spells, split by color and by early/mid/late curve buckets.",
        "manabase_source_coverage": "How many land and nonland cards produce each color. Weighted sources discount slower mana.",
        "manabase_balance_gap": "Compares color demand share (pips) against source share. Negative gap means under-supplied color demand.",
        "curve_histogram": "Your mana curve by mana value, split into permanents and spells, with estimated chance to cast each bucket on curve.",
    }


def _systems_metrics(cards: List[CardEntry], importance: List[Dict], sim_summary: Dict) -> Dict:
    role_counts = Counter()
    for c in cards:
        if c.section not in {"deck", "commander"}:
            continue
        for t in set(c.tags):
            role_counts[t] += c.qty
    total_roles = sum(role_counts.values()) or 1
    probs = [v / total_roles for v in role_counts.values() if v > 0]
    role_entropy = -sum(p * math.log(p, 2) for p in probs) if probs else 0.0

    top_scores = [max(0.0, x.get("score", 0.0)) for x in importance[:20]]
    score_total = sum(top_scores) or 1.0
    top5_share = sum(top_scores[:5]) / score_total if top_scores else 0.0
    gini_like = 0.0
    if top_scores and sum(top_scores) > 0:
        sorted_scores = sorted(top_scores)
        n = len(sorted_scores)
        weighted = sum((i + 1) * v for i, v in enumerate(sorted_scores))
        gini_like = (2 * weighted) / (n * sum(sorted_scores)) - (n + 1) / n
        gini_like = max(0.0, min(1.0, gini_like))

    fm = sim_summary.get("failure_modes", {})
    resilience = max(0.0, min(100.0, 100 - (fm.get("mana_screw", 0.0) * 45 + fm.get("no_action", 0.0) * 40 + fm.get("flood", 0.0) * 20)))
    redundancy = max(0.0, min(100.0, (1 - top5_share) * 100))
    bottleneck = round(top5_share * 100, 1)

    return {
        "resilience_score": round(resilience, 1),
        "redundancy_score": round(redundancy, 1),
        "bottleneck_index": bottleneck,
        "impact_inequality": round(gini_like, 3),
        "role_entropy_bits": round(role_entropy, 3),
        "interpretation": {
            "resilience_score": "Higher is better. Reflects resistance to screw/flood/no-action failure modes.",
            "redundancy_score": "Higher means outcomes are not concentrated in a few cards.",
            "bottleneck_index": "Top-5 impact share. High values indicate fragile dependency on a few pieces.",
            "impact_inequality": "0 = evenly distributed impact, 1 = highly concentrated impact.",
            "role_entropy_bits": "Higher entropy means broader role spread; too low can mean a one-dimensional plan.",
        },
    }


def _tag_diagnostics(cards: List[CardEntry]) -> Dict:
    main_cards = [c for c in cards if c.section in {"deck", "commander"}]
    untagged = [c.name for c in main_cards if not c.tags]
    overloaded = [c.name for c in main_cards if len(set(c.tags)) >= 7]
    multi_role = [c.name for c in main_cards if len(set(c.tags)) >= 3]
    return {
        "untagged_count": len(untagged),
        "overloaded_count": len(overloaded),
        "multi_role_count": len(multi_role),
        "untagged_cards": untagged[:20],
        "overloaded_cards": overloaded[:20],
        "notes": [
            "Untagged cards often indicate missing oracle text patterns or insufficient overrides.",
            "Overloaded cards may have too many broad regex matches; review role specificity.",
            "Multi-role cards are expected in Commander, but excessive overlap can blur recommendations.",
        ],
    }


def _names_for_tag(cards: List[CardEntry], tags: set[str], n: int = 3) -> List[str]:
    out: List[str] = []
    seen = set()
    for c in cards:
        if c.section not in {"deck", "commander"}:
            continue
        if c.name in seen:
            continue
        if set(c.tags) & tags:
            out.append(c.name)
            seen.add(c.name)
        if len(out) >= n:
            break
    return out


def _fmt_names(names: List[str], fallback: str = "key cards") -> str:
    if not names:
        return fallback
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + f", and {names[-1]}"


def _fallback_deck_names(cards: List[CardEntry], n: int = 3) -> List[str]:
    out: List[str] = []
    seen = set()
    for c in cards:
        if c.section not in {"deck", "commander"}:
            continue
        if c.name in seen:
            continue
        tags = set(c.tags or [])
        # Prefer cards that meaningfully affect game flow over pure lands.
        if "#Land" in tags and len(tags) == 1:
            continue
        out.append(c.name)
        seen.add(c.name)
        if len(out) >= n:
            break
    if out:
        return out
    # Absolute fallback: still return real deck cards.
    for c in cards:
        if c.section in {"deck", "commander"} and c.name not in seen:
            out.append(c.name)
            seen.add(c.name)
        if len(out) >= n:
            break
    return out


def _stable_pick(options: List[str], seed: str) -> str:
    if not options:
        return ""
    idx = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16) % len(options)
    return options[idx]


def _deck_name_anchor(name: str | None) -> str:
    raw = str(name or "").strip()
    if not raw:
        return "Deck"
    if "," in raw:
        head = raw.split(",", 1)[0].strip()
        head_tokens = [t for t in re.split(r"\s+", head) if t]
        return head_tokens[0] if head_tokens else head
    tokens = [re.sub(r"[^A-Za-z0-9'-]", "", t) for t in re.split(r"\s+", raw) if t]
    tokens = [t for t in tokens if t]
    if not tokens:
        return "Deck"
    if tokens[0].lower() == "the" and len(tokens) >= 2:
        return tokens[-1]
    if len(tokens) >= 3 and tokens[1].lower() == "the":
        return tokens[0]
    return tokens[0]


def _dominant_deck_name_theme(cards: List[CardEntry], primary_plan: str) -> str | None:
    counts: Counter = Counter()
    for c in cards:
        if c.section not in {"deck", "commander"}:
            continue
        for tag in set(c.tags or []):
            if tag in DECK_NAME_THEME_HOOKS:
                counts[tag] += c.qty
    if primary_plan == "Combo Assembly":
        counts["#ComboControl"] += 1
    if primary_plan == "Control into Inevitable Finish":
        counts["#Control"] += 1
    if primary_plan == "Voltron Pressure":
        counts["#Voltron"] += 1
    if not counts:
        return None
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _generate_deck_name(
    cards: List[CardEntry],
    commander: str | None,
    intent: Dict,
    combo_intel: Dict | None,
    bracket: int,
    importance: List[Dict] | None = None,
) -> str:
    primary_plan = str(intent.get("primary_plan") or "Value Midrange")
    dominant_theme = _dominant_deck_name_theme(cards, primary_plan)
    anchor_source = commander
    if not anchor_source:
        preferred_cards = [x.get("card") for x in (importance or []) if x.get("card")]
        anchor_source = preferred_cards[0] if preferred_cards else (_fallback_deck_names(cards, n=1) or ["Deck"])[0]
    anchor = _deck_name_anchor(anchor_source)
    seed = "|".join(
        [
            anchor_source or "",
            primary_plan,
            dominant_theme or "",
            ",".join(intent.get("kill_vectors", []) or []),
            str(bracket),
            str(len((combo_intel or {}).get("matched_variants", []) or [])),
        ]
    )

    if bracket >= 4:
        label = DECK_NAME_THEME_LABELS.get(dominant_theme or "", "") or DECK_NAME_PLAN_LABELS.get(primary_plan, "Value")
        name = f"{anchor} {label}".strip()
        return re.sub(r"\s+", " ", name)

    hook_options = DECK_NAME_THEME_HOOKS.get(dominant_theme or "", []) or DECK_NAME_PLAN_HOOKS.get(primary_plan, [])
    if primary_plan == "Combo Assembly" and (combo_intel or {}).get("matched_variants"):
        hook_options = hook_options + ["Breakfast", "Assembly Line"]
    if not hook_options:
        hook_options = ["Engine Room", "Long Game", "Endgame"]
    hook = _stable_pick(hook_options, seed)
    pattern = int(hashlib.sha256(f"{seed}:pattern".encode()).hexdigest()[:8], 16) % 3
    if pattern == 0:
        name = f"{anchor} {hook}"
    elif pattern == 1 and not anchor.endswith("s"):
        name = f"{anchor}'s {hook}"
    else:
        name = f"{hook} {anchor}"
    return re.sub(r"\s+", " ", name).strip()


def _graph_deck_blurbs(
    cards: List[CardEntry],
    sim_summary: Dict,
    commander: str | None,
    commander_colors: List[str],
    cuts: List[Dict],
    importance: List[Dict],
) -> Dict[str, str]:
    fm = sim_summary.get("failure_modes", {})
    miles = sim_summary.get("milestones", {})
    win = sim_summary.get("win_metrics", {})
    gp = sim_summary.get("graph_payloads", {})
    dead_cards = [d.get("card") for d in (gp.get("dead_cards_top") or []) if d.get("card")][:3]

    ramp_cards = _names_for_tag(cards, {"#Ramp", "#FastMana", "#Rock", "#Dork"}, n=3)
    draw_cards = _names_for_tag(cards, {"#Draw"}, n=3)
    fixing_cards = _names_for_tag(cards, {"#Fixing"}, n=3)
    engine_cards = _names_for_tag(cards, {"#Engine"}, n=3)
    interaction_cards = _names_for_tag(cards, {"#Removal", "#Counter", "#Boardwipe"}, n=3)
    payoff_cards = _names_for_tag(cards, {"#Wincon", "#Payoff", "#Combo"}, n=3)
    top_cards = [x.get("card") for x in importance[:3] if x.get("card")]
    cut_cards = [x.get("card") for x in cuts[:2] if x.get("card")]
    fallback_cards = _fallback_deck_names(cards, n=4)
    ci_size = len(commander_colors or [])
    commander_label = commander or "your commander"

    mana_blurb = (
        f"In this list, {miles.get('p_mana4_t3', 0):.1%} of games reach 4 mana by turn 3. "
        f"Keep hands that include { _fmt_names(ramp_cards or fallback_cards, 'your cheap ramp package') }. "
        f"If starts still feel slow, trim clunky slots like { _fmt_names(cut_cards or fallback_cards[:2], 'low-impact top-end cards') }."
    )
    land_blurb = (
        f"Your early development hinges on hitting land drops and converting them with cards like { _fmt_names(draw_cards or fallback_cards, 'cheap draw/filter cards') }. "
        f"If on-curve land hits dip early, increase raw mana consistency before adding more payoff cards such as { _fmt_names(payoff_cards or fallback_cards[:2], 'finishers') }."
    )
    if ci_size <= 1:
        color_blurb = (
            f"This is a {('colorless' if ci_size == 0 else 'single-color')} deck, so color screw is not a primary failure mode. "
            f"Focus on total mana pace and sequencing around { _fmt_names(ramp_cards or fallback_cards, 'mana enablers') } and { _fmt_names(engine_cards or fallback_cards, 'engines') }."
        )
    else:
        color_blurb = (
            f"Color access needs to reliably enable all {ci_size} commander colors. "
            f"Prioritize fixing cards like { _fmt_names(fixing_cards or fallback_cards, 'your fixing package') }, then cast engines such as { _fmt_names(engine_cards or fallback_cards, 'core engines') }."
        )

    phase_blurb = (
        f"The deck should move from setup into engine by turn 4-5. "
        f"Use { _fmt_names(engine_cards or fallback_cards, 'engine cards') } as your transition point, then pivot to { _fmt_names(payoff_cards or top_cards or fallback_cards[:2], 'win pieces') } once mana is stable."
    )
    win_blurb = (
        f"Current win timing shows your close speed is tied to { _fmt_names(payoff_cards or top_cards or fallback_cards[:2], 'your payoff package') }. "
        f"Most common route is {win.get('most_common_wincon') or 'not clearly dominant'}. Action: keep that line, cut underperformers like { _fmt_names(cut_cards or fallback_cards[:2], 'replaceable cards') }, and add redundancy/protection around { _fmt_names(top_cards or fallback_cards[:2], 'core finishers') }."
    )
    no_action_blurb = (
        f"No-action starts are {fm.get('no_action', 0):.1%}. "
        f"Mulligan for hands containing { _fmt_names((ramp_cards + draw_cards) or fallback_cards, 'cheap setup cards') }, and avoid keeps loaded only with finishers like { _fmt_names(payoff_cards or fallback_cards[:2], 'top-end cards') }."
    )
    dead_blurb = (
        f"Most stranded cards in your current sims include { _fmt_names(dead_cards, 'high-cost pieces') }. "
        f"Either cast them later behind { _fmt_names(engine_cards or fallback_cards, 'engines') } or replace them with smoother options from your role-gap recommendations."
    )
    commander_blurb = (
        f"{commander_label} is central to your line quality. "
        f"If cast timing is inconsistent, prioritize early support cards like { _fmt_names((ramp_cards + draw_cards) or fallback_cards, 'early setup tools') } to land commander on a productive turn."
    )
    mulligan_blurb = (
        f"Your keep quality improves when openers contain { _fmt_names(ramp_cards or fallback_cards, 'ramp') } plus { _fmt_names(draw_cards or fallback_cards[:2], 'card flow') }. "
        f"If you are taking deep mulligans frequently, reduce dependency on narrow cards like { _fmt_names(cut_cards or fallback_cards[:2], 'replaceable low-impact slots') }."
    )
    plan_blurb = (
        f"Plan progress is strongest when { _fmt_names(top_cards or fallback_cards[:3], 'your top impact cards') } appear early. "
        f"Sequence these before committing to secondary lines, then use { _fmt_names(interaction_cards or fallback_cards[:2], 'interaction pieces') } to protect momentum."
    )
    failure_blurb = (
        f"Your biggest risks are mana screw ({fm.get('mana_screw', 0):.1%}) and no-action starts ({fm.get('no_action', 0):.1%}). "
        f"Fix these first with { _fmt_names((ramp_cards + draw_cards) or fallback_cards, 'early consistency cards') } before changing finishers. "
        f"Concrete first move: swap out weaker cards like { _fmt_names(cut_cards or fallback_cards[:2], 'replaceable cards') } for low-MV setup that supports { _fmt_names(top_cards or fallback_cards[:2], 'your best-performing line') }."
    )
    wincon_blurb = (
        f"Win routes currently concentrate around {win.get('most_common_wincon') or 'mixed lines'}. "
        f"Support that route with cards already in your list like { _fmt_names(payoff_cards or top_cards or fallback_cards[:2], 'payoff cards') } and keep interaction ({ _fmt_names(interaction_cards or fallback_cards[:2], 'answers') }) available in real pods."
    )
    uncertainty_blurb = (
        f"These confidence ranges are based on your exact list and current run count. "
        f"If ranges stay wide, raise runs before changing cards. If ranges are tight and still poor, act on deck structure: improve early consistency around { _fmt_names((ramp_cards + draw_cards) or fallback_cards[:3], 'your setup package') } and de-prioritize low-impact slots like { _fmt_names(cut_cards or fallback_cards[:2], 'replaceable cards') }."
    )

    return {
        "mana_percentiles": mana_blurb,
        "land_hit_cdf": land_blurb,
        "color_access": color_blurb,
        "phase_timeline": phase_blurb,
        "win_turn_cdf": win_blurb,
        "no_action_funnel": no_action_blurb,
        "dead_cards_top": dead_blurb,
        "commander_cast_distribution": commander_blurb,
        "mulligan_funnel": mulligan_blurb,
        "plan_progress": plan_blurb,
        "failure_rates": failure_blurb,
        "wincon_outcomes": wincon_blurb,
        "uncertainty": uncertainty_blurb,
    }


def _dedupe_and_exclude_existing_adds(cards: List[CardEntry], adds: List[Dict]) -> List[Dict]:
    deck_names = {c.name for c in cards if c.section in {"deck", "commander"}}
    out: List[Dict] = []
    seen = set()
    for a in adds:
        name = a.get("card")
        if not name:
            continue
        if name in deck_names:
            continue
        if name in seen:
            continue
        seen.add(name)
        out.append(a)
    return out


def analyze(
    cards: List[CardEntry],
    sim_summary: Dict,
    bracket_report: Dict,
    template: str,
    commander_ci: str,
    budget_max_usd: float | None = None,
    combo_intel: Dict | None = None,
    commander: str | None = None,
    commander_colors: List[str] | None = None,
    card_map: Dict[str, Dict] | None = None,
) -> Dict:
    rb = role_breakdown(cards)
    importance = importance_scores(cards, sim_summary)
    top = importance[:20]
    bottom = list(reversed(importance[-20:]))
    bracket = int(bracket_report.get("bracket", 3) or 3)
    color_count = len(commander_colors or list((commander_ci or "").upper()))
    role_model = _role_target_model(cards, sim_summary, combo_intel, bracket=bracket, color_count=color_count)
    gaps = _role_gap_list_from_model(cards, role_model)
    gap_roles = {g.get("role") for g in gaps if g.get("role")}
    commander_names = {c.name for c in cards if c.section == "commander"}
    type_profile = compute_type_theme_profile(cards, card_map or {})

    cuts = _find_replaceable(cards, bottom)
    cuts = [c for c in cuts if c.get("card") not in commander_names]
    adds = suggest_adds(cards, commander_ci, gaps, bracket, budget_max_usd=budget_max_usd, commander=commander)
    consistency_score = _consistency_score(sim_summary)
    health_summary = _health_summary(cards, rb, sim_summary, consistency_score, combo_intel=combo_intel)

    commander_ci_set = set((commander_ci or "").upper())
    if (combo_intel or {}).get("near_miss_variants"):
        combo_missing = (combo_intel or {}).get("near_miss_variants", [])[0].get("missing_cards", [])
        combo_fill = None
        for role in ("#Combo", "#Wincon", "#Tutor", "#Protection"):
            if role in gap_roles:
                combo_fill = role
                break
        if combo_fill is None:
            combo_missing = []
        if combo_missing:
            candidate_name = combo_missing[0]
            allowed = True
            card_map = CardDataService().get_cards_by_name([candidate_name])
            cand_ci = set((card_map.get(candidate_name) or {}).get("color_identity") or [])
            if commander_ci_set:
                allowed = cand_ci.issubset(commander_ci_set)
            else:
                allowed = not cand_ci
            if not allowed:
                combo_missing = []
        if combo_missing:
            deck_names = {c.name for c in cards if c.section in {"deck", "commander"}}
            if combo_missing[0] in deck_names:
                combo_missing = []
        if combo_missing:
            adds = [
                {
                    "card": combo_missing[0],
                    "fills": combo_fill,
                    "why": f"Completes a high-scoring near-miss combo line from CommanderSpellbook while improving {combo_fill}.",
                    "bracket_impact": "Verify bracket/game-changer constraints.",
                    "is_game_changer": False,
                    "budget_note": "n/a",
                    "source": "commanderspellbook",
                }
            ] + adds
            adds = adds[:10]

    adds = _strict_filter_adds(cards, adds, commander_ci=commander_ci, budget_max_usd=budget_max_usd)
    if gap_roles:
        adds = [a for a in adds if a.get("fills") in gap_roles]
    adds = _dedupe_and_exclude_existing_adds(cards, adds)
    adds = adds[:10]

    compliant_alternatives = []
    if bracket_report.get("violations"):
        compliant_alternatives = [
            {
                "card": a["card"],
                "reason": "Bracket-compliant alternative for over-limit Game Changer slot.",
                "fills": a["fills"],
            }
            for a in adds
            if not a.get("is_game_changer", False)
        ][:10]

    swaps = []
    for c, a in zip(cuts[:10], adds[:10]):
        if c.get("card") in commander_names:
            continue
        swaps.append({"cut": c["card"], "add": a["card"], "reason": f"Replace low-impact slot with {a['fills']} support."})

    intent = _intent_summary(commander, cards, sim_summary, combo_intel, importance=top, type_profile=type_profile)
    actions = _actionable_actions(gaps, combo_intel)
    deck_card_map = card_map or {}
    manabase_analysis = _manabase_analysis(
        cards,
        commander_colors=commander_colors or [],
        sim_summary=sim_summary,
        card_map=deck_card_map,
    )
    graph_payloads = {
        **(sim_summary.get("graph_payloads", {}) or {}),
        **(manabase_analysis.get("graph_payloads", {}) or {}),
    }
    graph_explanations = _graph_explanations(sim_summary)
    systems_metrics = _systems_metrics(cards, top, sim_summary)
    tag_diagnostics = _tag_diagnostics(cards)
    ci = commander_colors or list((commander_ci or "").upper())
    graph_deck_blurbs = _graph_deck_blurbs(
        cards=cards,
        sim_summary=sim_summary,
        commander=commander,
        commander_colors=ci,
        cuts=cuts,
        importance=top,
    )
    graph_deck_blurbs.update(manabase_analysis.get("graph_blurbs", {}) or {})
    color_profile = {
        "color_identity": ci,
        "color_identity_size": len(ci),
        "label": "Colorless" if len(ci) == 0 else "".join(ci),
        "recommendations_constrained": True,
    }
    role_targets = role_model.get("role_targets", {})
    all_roles = sorted(set(list(role_targets.keys()) + list((rb.get("roles") or {}).keys())))
    role_cards_map = _role_cards_map(cards, all_roles)
    deck_name = _generate_deck_name(
        cards=cards,
        commander=commander,
        intent=intent,
        combo_intel=combo_intel,
        bracket=bracket,
        importance=top,
    )

    return {
        "deck_name": deck_name,
        "role_breakdown": rb,
        "role_targets": role_targets,
        "role_target_model": {
            "primary_philosophy": role_model.get("primary_philosophy"),
            "philosophy_weights": role_model.get("philosophy_weights", {}),
            "notes": role_model.get("notes", []),
        },
        "role_cards_map": role_cards_map,
        "bracket_report": bracket_report,
        "consistency_score": consistency_score,
        "health_summary": health_summary,
        "intent_summary": intent,
        "actionable_actions": actions,
        "combo_intel": combo_intel or {
            "source": "commanderspellbook",
            "fetched_at": None,
            "source_hash": "",
            "combo_support_score": 0.0,
            "matched_variants": [],
            "near_miss_variants": [],
            "warnings": [],
        },
        "type_theme_profile": type_profile,
        "graph_payloads": graph_payloads,
        "graph_explanations": graph_explanations,
        "graph_deck_blurbs": graph_deck_blurbs,
        "systems_metrics": systems_metrics,
        "tag_diagnostics": tag_diagnostics,
        "color_profile": color_profile,
        "manabase_analysis": manabase_analysis,
        "importance": top,
        "cuts": cuts[:10],
        "adds": adds[:10],
        "swaps": swaps[:10],
        "missing_roles": gaps,
        "compliant_alternatives": compliant_alternatives,
    }
