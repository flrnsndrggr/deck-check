from __future__ import annotations

import random
import re
from collections import Counter
from typing import Dict, List, Sequence, Tuple

from app.schemas.deck import CardEntry
from app.services.commander_utils import (
    combined_color_identity,
    commander_display_name,
    has_choose_a_background,
    partner_mode,
)
from app.services.scryfall import CardDataService
from app.services.tagger import intrinsic_tags
from app.services.validator import validate_deck

COLOR_TO_BASIC = {
    "W": "Plains",
    "U": "Island",
    "B": "Swamp",
    "R": "Mountain",
    "G": "Forest",
}

GENERIC_NONBASIC_LANDS = [
    "Command Tower",
    "Path of Ancestry",
    "Exotic Orchard",
    "Ash Barrens",
    "Terramorphic Expanse",
    "Evolving Wilds",
    "Myriad Landscape",
    "Opal Palace",
]

COLORLESS_NONBASIC_LANDS = [
    "War Room",
    "Bonders' Enclave",
    "Buried Ruin",
    "Scavenger Grounds",
    "Rogue's Passage",
    "Myriad Landscape",
    "Blast Zone",
    "Demolition Field",
]

STOPWORDS = {
    "the",
    "and",
    "your",
    "with",
    "from",
    "that",
    "this",
    "whenever",
    "beginning",
    "each",
    "card",
    "cards",
    "creature",
    "legendary",
}

THEME_PATTERNS: Dict[str, Sequence[str]] = {
    "artifacts": ["artifact", "equipment", "treasure", "clue", "construct"],
    "enchantments": ["enchantment", "aura", "background", "shrine", "saga"],
    "spellslinger": ["instant", "sorcery", "noncreature", "magecraft", "prowess", "copy target spell"],
    "graveyard": ["graveyard", "return target", "reanimate", "mill", "surveil", "flashback", "escape"],
    "tokens": ["create", "token", "populate"],
    "sacrifice": ["sacrifice", "dies", "when another creature dies"],
    "counters": ["+1/+1 counter", "counter on", "proliferate"],
    "lifegain": ["gain life", "whenever you gain life", "lifelink"],
    "combat": ["attack", "attacks", "combat damage", "menace", "double strike", "flying"],
    "lands": ["landfall", "additional land", "search your library for a land"],
    "blink": ["exile", "return it to the battlefield", "blink"],
}


def _text(card: Dict) -> str:
    return f"{card.get('type_line', '')} {card.get('oracle_text', '')}".lower()


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-zA-Z]{4,}", text.lower()) if token not in STOPWORDS}


def _mana_value(card: Dict) -> float:
    try:
        return float(card.get("mana_value") or card.get("cmc") or 0.0)
    except Exception:
        return 0.0


def _is_fog(card: Dict) -> bool:
    txt = _text(card)
    return "prevent all combat damage" in txt or "prevent all damage that would be dealt by attacking" in txt


def _count_pips(cards: Sequence[Dict], commander_cards: Sequence[Dict], colors: Sequence[str]) -> Counter:
    counts: Counter = Counter({color: 1 for color in colors})
    mana_texts = [str(card.get("mana_cost") or "") for card in commander_cards]
    mana_texts.extend(str(card.get("mana_cost") or "") for card in cards)
    for mana_cost in mana_texts:
        for color in colors:
            counts[color] += mana_cost.count(f"{{{color}}}")
    return counts


class RandomDeckService:
    def __init__(self, rng: random.Random | None = None, card_service: CardDataService | None = None):
        self.rng = rng or random.Random()
        self.card_service = card_service or CardDataService()

    def _random_commander(self) -> Dict:
        query = "game:paper legal:commander t:legendary t:creature -is:funny"
        return self.card_service.fetch_random_card(query)

    def _commander_profile(self, commander_cards: Sequence[Dict]) -> Dict[str, object]:
        text = " ".join(_text(card) for card in commander_cards)
        subtypes = set()
        for commander in commander_cards:
            type_line = str(commander.get("type_line") or "").lower()
            subtype_text = type_line.split("—", 1)[1] if "—" in type_line else type_line.split("-", 1)[1] if "-" in type_line else ""
            subtypes.update(
                token.strip()
                for token in re.split(r"\s+", subtype_text)
                if token.strip() and token.strip() not in {"human"}
            )
        themes = {theme for theme, patterns in THEME_PATTERNS.items() if any(pattern in text for pattern in patterns)}
        return {
            "text": text,
            "tokens": _tokens(text),
            "subtypes": subtypes,
            "themes": themes,
        }

    def _fetch_named_card(self, name: str) -> Dict | None:
        target = str(name or "").strip()
        if not target:
            return None
        candidates = [target]
        titled = " ".join(part.capitalize() for part in target.split())
        if titled not in candidates:
            candidates.append(titled)
        fetched = self.card_service.get_cards_by_name(candidates)
        for candidate in candidates:
            if fetched.get(candidate):
                return fetched[candidate]
        return next(iter(fetched.values()), None)

    def _random_partner_commander(self, primary_name: str) -> Dict | None:
        query = 'game:paper legal:commander t:legendary t:creature o:"Partner" -o:"Partner with" -is:funny'
        primary_key = str(primary_name or "").strip().lower()
        for _ in range(10):
            candidate = self.card_service.fetch_random_card(query)
            if str(candidate.get("name") or "").strip().lower() != primary_key:
                return candidate
        return None

    def _random_background(self) -> Dict | None:
        query = 'game:paper legal:commander t:background -is:funny'
        try:
            return self.card_service.fetch_random_card(query)
        except Exception:
            return None

    def _secondary_commander(self, primary_commander: Dict) -> Dict | None:
        mode, value = partner_mode(primary_commander)
        if mode == "partner_with" and value:
            return self._fetch_named_card(value)
        if mode == "partner":
            return self._random_partner_commander(str(primary_commander.get("name") or ""))
        if has_choose_a_background(primary_commander):
            return self._random_background()
        return None

    def _entry_with_tags(self, card: Dict) -> CardEntry:
        entry = CardEntry(qty=1, name=str(card.get("name") or ""), section="deck")
        entry.tags = []
        entry.confidence = {}
        entry.explanations = {}
        intrinsic_tags(entry, card)
        return entry

    def _candidate_score(self, card: Dict, entry: CardEntry, profile: Dict[str, object]) -> float:
        txt = _text(card)
        card_tokens = _tokens(txt)
        score = 0.0
        token_overlap = len(card_tokens & set(profile["tokens"]))
        score += min(token_overlap, 4) * 0.8

        card_type_line = str(card.get("type_line") or "").lower()
        subtype_overlap = 0
        for subtype in profile["subtypes"]:
            if subtype and subtype in card_type_line:
                subtype_overlap += 1
        score += subtype_overlap * 2.0

        themes = set(profile["themes"])
        if "artifacts" in themes and ("#Artifacts" in entry.tags or "artifact" in txt):
            score += 3.0
        if "enchantments" in themes and ("#Enchantments" in entry.tags or "enchantment" in txt):
            score += 3.0
        if "spellslinger" in themes and ("instant" in card_type_line or "sorcery" in card_type_line):
            score += 3.0
        if "graveyard" in themes and any(term in txt for term in ["graveyard", "return target", "reanimate", "mill"]):
            score += 3.0
        if "tokens" in themes and "#Tokens" in entry.tags:
            score += 2.5
        if "sacrifice" in themes and "#Sacrifice" in entry.tags:
            score += 2.5
        if "counters" in themes and any(term in txt for term in ["+1/+1 counter", "proliferate", "counter on"]):
            score += 2.5
        if "lifegain" in themes and any(term in txt for term in ["gain life", "lifelink"]):
            score += 2.0
        if "combat" in themes and any(term in txt for term in ["attacks", "combat damage", "double strike", "flying"]):
            score += 1.8
        if "lands" in themes and any(term in txt for term in ["landfall", "search your library for a land", "additional land"]):
            score += 2.5
        if "blink" in themes and "return it to the battlefield" in txt:
            score += 2.0

        if "#Engine" in entry.tags:
            score += 0.8
        if "#Payoff" in entry.tags:
            score += 0.6
        if "#Setup" in entry.tags:
            score += 0.3

        mv = _mana_value(card)
        if mv >= 7:
            score -= 1.4
        elif mv >= 5:
            score -= 0.5
        return score

    def _rank_interaction(self, card: Dict, entry: CardEntry, profile: Dict[str, object]) -> float:
        mv = _mana_value(card)
        txt = _text(card)
        type_line = str(card.get("type_line") or "").lower()
        instant_speed = "instant" in type_line or "flash" in txt or _is_fog(card)
        if mv > 2 or not instant_speed:
            return -999.0
        score = self._candidate_score(card, entry, profile)
        if {"#Removal", "#Counter", "#Protection"} & set(entry.tags):
            score += 6.0
        if "#StackInteraction" in entry.tags:
            score += 2.0
        if _is_fog(card):
            score += 3.0
        return score

    def _rank_ramp(self, card: Dict, entry: CardEntry, profile: Dict[str, object]) -> float:
        if "#Ramp" not in entry.tags:
            return -999.0
        mv = _mana_value(card)
        if mv > 4:
            return -999.0
        score = self._candidate_score(card, entry, profile) + 4.0
        if {"#FastMana", "#Rock", "#Dork", "#Ritual"} & set(entry.tags):
            score += 2.0
        score -= mv * 0.3
        return score

    def _rank_draw(self, card: Dict, entry: CardEntry, profile: Dict[str, object]) -> float:
        if "#Draw" not in entry.tags and "#Tutor" not in entry.tags:
            return -999.0
        mv = _mana_value(card)
        if mv > 5:
            return -999.0
        score = self._candidate_score(card, entry, profile) + 3.5
        if "#Tutor" in entry.tags:
            score += 0.8
        score -= mv * 0.25
        return score

    def _rank_synergy(self, card: Dict, entry: CardEntry, profile: Dict[str, object]) -> float:
        if "land" in str(card.get("type_line") or "").lower():
            return -999.0
        score = self._candidate_score(card, entry, profile)
        if "#CommanderSynergy" in entry.tags:
            score += 2.5
        if "#Wincon" in entry.tags or "#Combo" in entry.tags:
            score += 1.2
        return score

    def _pick_ranked(
        self,
        ranked: List[Tuple[float, CardEntry, Dict]],
        count: int,
        selected_names: set[str],
        window: int = 4,
    ) -> List[CardEntry]:
        chosen: List[CardEntry] = []
        candidates = [row for row in ranked if row[1].name not in selected_names]
        while len(chosen) < count and candidates:
            candidates.sort(key=lambda row: row[0], reverse=True)
            top = candidates[: min(window, len(candidates))]
            _, entry, _ = self.rng.choice(top)
            chosen.append(entry)
            selected_names.add(entry.name)
            candidates = [row for row in candidates if row[1].name not in selected_names]
        return chosen

    def _nonbasic_land_names(self, colors: Sequence[str]) -> List[str]:
        if not colors:
            return COLORLESS_NONBASIC_LANDS[:8]
        return GENERIC_NONBASIC_LANDS[:8]

    def _basic_land_entries(self, colors: Sequence[str], selected_nonlands: Sequence[Dict], commander_cards: Sequence[Dict], total_basics: int) -> List[CardEntry]:
        if total_basics <= 0:
            return []
        if not colors:
            return [CardEntry(qty=total_basics, name="Wastes", section="deck")]

        pip_counts = _count_pips(selected_nonlands, commander_cards, colors)
        total_weight = sum(max(1, pip_counts[color]) for color in colors)
        allocations = {color: max(1, round(total_basics * max(1, pip_counts[color]) / total_weight)) for color in colors}
        current_total = sum(allocations.values())
        order = sorted(colors, key=lambda color: pip_counts[color], reverse=True)
        while current_total > total_basics:
            for color in order:
                if allocations[color] > 1 and current_total > total_basics:
                    allocations[color] -= 1
                    current_total -= 1
        while current_total < total_basics:
            for color in order:
                if current_total < total_basics:
                    allocations[color] += 1
                    current_total += 1
        return [CardEntry(qty=allocations[color], name=COLOR_TO_BASIC[color], section="deck") for color in colors if allocations[color] > 0]

    def _build_deck_entries(self, commander_cards: Sequence[Dict]) -> tuple[List[CardEntry], Dict[str, Dict], int]:
        commander_names = [str(card.get("name") or "").strip() for card in commander_cards if str(card.get("name") or "").strip()]
        card_map: Dict[str, Dict] = {name: card for name, card in zip(commander_names, commander_cards)}
        commander_colors = combined_color_identity(card_map, commander_names)
        color_identity = "".join(commander_colors)
        profile = self._commander_profile(commander_cards)

        pools = {
            "interaction": self.card_service.search_candidates('mv<=2 ((t:instant) or o:"prevent all combat damage" or o:"flash") -t:land', color_identity, limit=120),
            "ramp": self.card_service.search_candidates("mv<=4 -t:land", color_identity, limit=140),
            "draw": self.card_service.search_candidates("mv<=5 -t:land", color_identity, limit=140),
            "synergy": self.card_service.search_candidates("-t:land", color_identity, limit=220),
        }

        entry_map: Dict[str, CardEntry] = {}
        for pool in pools.values():
            for card in pool:
                name = str(card.get("name") or "").strip()
                if not name or name in commander_names:
                    continue
                card_map[name] = card
                if name not in entry_map:
                    entry_map[name] = self._entry_with_tags(card)

        selected_names: set[str] = set()
        interaction_target = self.rng.randint(10, 15)
        ramp_target = 10
        draw_target = 8

        interaction_ranked = [(self._rank_interaction(card_map[name], entry, profile), entry, card_map[name]) for name, entry in entry_map.items()]
        ramp_ranked = [(self._rank_ramp(card_map[name], entry, profile), entry, card_map[name]) for name, entry in entry_map.items()]
        draw_ranked = [(self._rank_draw(card_map[name], entry, profile), entry, card_map[name]) for name, entry in entry_map.items()]
        synergy_ranked = [(self._rank_synergy(card_map[name], entry, profile), entry, card_map[name]) for name, entry in entry_map.items()]

        chosen_spells: List[CardEntry] = []
        interaction_picks = self._pick_ranked([row for row in interaction_ranked if row[0] > -900], interaction_target, selected_names)
        chosen_spells.extend(interaction_picks)
        chosen_spells.extend(self._pick_ranked([row for row in ramp_ranked if row[0] > -900], ramp_target, selected_names))
        chosen_spells.extend(self._pick_ranked([row for row in draw_ranked if row[0] > -900], draw_target, selected_names))
        spell_slot_target = 100 - 38 - len(commander_names)
        remaining_spell_slots = spell_slot_target - len(chosen_spells)
        chosen_spells.extend(self._pick_ranked([row for row in synergy_ranked if row[0] > -900], remaining_spell_slots, selected_names, window=6))

        if len(chosen_spells) < spell_slot_target:
            fallback_ranked = sorted(
                [row for row in synergy_ranked if row[1].name not in selected_names],
                key=lambda row: row[0],
                reverse=True,
            )
            for _, entry, _ in fallback_ranked:
                if len(chosen_spells) >= spell_slot_target:
                    break
                chosen_spells.append(entry)
                selected_names.add(entry.name)

        chosen_cards = [card_map[entry.name] for entry in chosen_spells]
        nonbasic_names = self._nonbasic_land_names(commander_colors)
        nonbasic_land_entries = [CardEntry(qty=1, name=name, section="deck") for name in nonbasic_names]
        basic_land_entries = self._basic_land_entries(commander_colors, chosen_cards, commander_cards, total_basics=38 - len(nonbasic_land_entries))

        commander_entries = [CardEntry(qty=1, name=name, section="commander") for name in commander_names]
        return [*commander_entries, *nonbasic_land_entries, *basic_land_entries, *chosen_spells[:spell_slot_target]], card_map, len(interaction_picks)

    def _to_decklist_text(self, cards: Sequence[CardEntry]) -> str:
        commander_lines = [f"{entry.qty} {entry.name}" for entry in cards if entry.section == "commander"]
        deck_entries = [entry for entry in cards if entry.section == "deck"]

        def sort_key(entry: CardEntry) -> tuple[int, str]:
            if entry.name in COLOR_TO_BASIC.values() or entry.name == "Wastes":
                return (0, entry.name)
            return (1, entry.name)

        deck_lines = [f"{entry.qty} {entry.name}" for entry in sorted(deck_entries, key=sort_key)]
        return "Commander\n" + "\n".join(commander_lines) + "\nDeck\n" + "\n".join(deck_lines)

    def generate(self, bracket: int = 3) -> Dict[str, object]:
        last_errors: List[str] = []
        for _ in range(8):
            commander_card = self._random_commander()
            secondary = self._secondary_commander(commander_card)
            commander_cards = [commander_card, secondary] if secondary else [commander_card]
            cards, card_map, interaction_count = self._build_deck_entries(commander_cards)
            if interaction_count < 10:
                last_errors = [f"Could not find enough cheap interaction for {commander_card.get('name') or 'selected commander'}."]
                continue
            names = [entry.name for entry in cards]
            fetched_map = self.card_service.get_cards_by_name(names)
            card_map.update(fetched_map)
            commander_names = [entry.name for entry in cards if entry.section == "commander"]
            errors, warnings, _ = validate_deck(cards, commander_display_name(commander_names), card_map, bracket)
            if not errors:
                return {
                    "decklist_text": self._to_decklist_text(cards),
                    "commander": commander_display_name(commander_names) or commander_names[0],
                    "commanders": commander_names,
                    "color_identity": combined_color_identity(card_map, commander_names),
                    "interaction_count": interaction_count,
                    "warnings": warnings,
                }
            last_errors = errors
        raise RuntimeError(last_errors[0] if last_errors else "Could not generate a legal random deck.")
