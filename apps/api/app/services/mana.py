from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Any

from app.schemas.deck import CardEntry


def _entry_field(entry: CardEntry | Mapping[str, Any] | None, field: str) -> Any:
    if entry is None:
        return None
    if isinstance(entry, Mapping):
        return entry.get(field)
    return getattr(entry, field, None)


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _face_mana_costs(payload: Mapping[str, Any] | None) -> list[str]:
    out: list[str] = []
    for face in (payload or {}).get("card_faces") or []:
        mana_cost = str((face or {}).get("mana_cost") or "").strip()
        if mana_cost:
            out.append(mana_cost)
    return out


def resolve_mana_cost_components(entry: CardEntry | Mapping[str, Any] | None, payload: Mapping[str, Any] | None) -> list[str]:
    entry_cost = str(_entry_field(entry, "mana_cost") or "").strip()
    payload = payload or {}
    top_level_cost = str(payload.get("mana_cost") or "").strip()
    if top_level_cost:
        return [top_level_cost]

    face_costs = _face_mana_costs(payload)
    if face_costs:
        return face_costs

    if entry_cost:
        return [entry_cost]
    return []


def resolve_mana_cost(entry: CardEntry | Mapping[str, Any] | None, payload: Mapping[str, Any] | None) -> str | None:
    entry_cost = str(_entry_field(entry, "mana_cost") or "").strip()
    if entry_cost:
        return entry_cost

    components = resolve_mana_cost_components(None, payload)
    if not components:
        return None
    if len(components) == 1:
        return components[0]
    return " // ".join(components)


def resolve_mana_value(entry: CardEntry | Mapping[str, Any] | None, payload: Mapping[str, Any] | None) -> float | None:
    entry_value = _coerce_float(_entry_field(entry, "mana_value"))
    if entry_value is not None:
        return entry_value

    payload = payload or {}
    payload_value = payload.get("mana_value")
    if payload_value is None:
        payload_value = payload.get("cmc")
    return _coerce_float(payload_value)


def hydrate_card_entry_mana(entry: CardEntry | MutableMapping[str, Any], payload: Mapping[str, Any] | None) -> None:
    mana_cost = resolve_mana_cost(entry, payload)
    mana_value = resolve_mana_value(entry, payload)

    if isinstance(entry, MutableMapping):
        entry["mana_cost"] = mana_cost
        entry["mana_value"] = mana_value
        return

    entry.mana_cost = mana_cost
    entry.mana_value = mana_value


def hydrate_card_entries_mana(cards: list[CardEntry], card_map: Mapping[str, Mapping[str, Any]]) -> list[CardEntry]:
    for entry in cards:
        hydrate_card_entry_mana(entry, card_map.get(entry.name))
    return cards
