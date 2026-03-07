from __future__ import annotations

import re
from collections import defaultdict
from typing import List, Tuple

from app.schemas.deck import CardEntry, DeckParseResponse

SECTION_MAP = {
    "commander": "commander",
    "deck": "deck",
    "mainboard": "deck",
    "sideboard": "sideboard",
    "companion": "companion",
}


QTY_RE = re.compile(r"^(\d+)\s*x?\s+(.+?)\s*$", re.IGNORECASE)
TRAILING_TAGS_RE = re.compile(r"\s+(?:#!?\S+\s*)+$")


def strip_about_block(text: str) -> str:
    # Decklist metadata guidance: https://decklist.gg/docs/deck-import
    lines = text.splitlines()
    out = []
    for line in lines:
        if line.strip().lower().startswith("about"):
            break
        out.append(line)
    return "\n".join(out)


def _normalize_name(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip()
    name = name.replace("’", "'")
    return name


def _strip_trailing_tags(name: str) -> str:
    # Moxfield-style tags are suffix tokens like "#Ramp" or "#!Ramp".
    # Treat them as metadata so tagged exports round-trip back into parsing.
    return TRAILING_TAGS_RE.sub("", name).strip()


def parse_decklist(text: str) -> DeckParseResponse:
    text = strip_about_block(text)
    current_section = "deck"
    cards: List[CardEntry] = []
    errors: List[str] = []
    warnings: List[str] = []
    commander = None
    commander_count = 0
    commanders: List[str] = []
    companion = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        lower = line.lower().rstrip(":")
        if lower in SECTION_MAP:
            current_section = SECTION_MAP[lower]
            continue

        m = QTY_RE.match(line)
        if not m:
            continue
        qty = int(m.group(1))
        name = _normalize_name(_strip_trailing_tags(m.group(2)))

        entry = CardEntry(qty=qty, name=name, section=current_section)
        cards.append(entry)
        if current_section == "commander":
            commander_count += qty
            if commander is None:
                commander = name
            if name not in commanders:
                commanders.append(name)
        if current_section == "companion":
            companion = name

    if commander is None:
        detected = [c.name for c in cards if c.section == "commander"]
        if detected:
            commander = detected[0]
            commanders = list(dict.fromkeys(detected))

    total = sum(c.qty for c in cards if c.section in {"commander", "deck"})
    if total != 100:
        errors.append(f"Deck must contain exactly 100 cards including commander; found {total}.")

    if commander is None:
        errors.append("No commander found. Add a Commander section.")
    elif len(commanders) > 2 or commander_count > 2:
        errors.append("Commander section can include at most two commanders.")

    sideboard_qty = sum(c.qty for c in cards if c.section == "sideboard")
    if sideboard_qty > 0:
        warnings.append("Sideboard cards are excluded from Commander legality checks.")

    if companion and any(c.section == "companion" and c.qty > 1 for c in cards):
        errors.append("Companion section can include at most one card.")

    return DeckParseResponse(
        commander=commander,
        commanders=commanders,
        companion=companion,
        cards=cards,
        errors=errors,
        warnings=warnings,
    )


def singleton_violations(cards: List[CardEntry], exceptions: set[str], basics: set[str]) -> List[str]:
    counts = defaultdict(int)
    for c in cards:
        if c.section not in {"deck", "commander"}:
            continue
        counts[c.name] += c.qty

    violations = []
    for name, qty in counts.items():
        if name in basics or name in exceptions:
            continue
        if qty > 1:
            violations.append(f"Singleton violation: {name} appears {qty} times.")
    return violations


def flatten_main_deck(cards: List[CardEntry]) -> List[str]:
    names = []
    for c in cards:
        if c.section in {"deck", "commander"}:
            names.extend([c.name] * c.qty)
    return names
