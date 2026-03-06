from __future__ import annotations

from typing import Dict, List

from app.schemas.deck import CardEntry
from app.services.commander_utils import commander_names_from_cards
from app.services.scryfall import CardDataService


FLAG_COPY: Dict[str, Dict[str, str]] = {
    "Replacement effect": {
        "note": "This card changes an event before it happens, so sequencing matters.",
        "rules": "Replacement effects do not trigger and do not use the stack. They change an event before it happens, and if several could apply, the affected player or object's controller chooses the order.",
    },
    "Continuous condition": {
        "note": "Its effect can turn on and off as board state changes.",
        "rules": "Conditional static abilities are checked continuously. If the stated condition stops being true, the effect stops applying immediately without using the stack.",
    },
    "Conditional replacement": {
        "note": "Its replacement text only works while a stated condition is true.",
        "rules": "Check the condition at the exact moment the event would happen. If it is not true then, the replacement does nothing.",
    },
    "Triggered timing": {
        "note": "Its value depends on hitting the correct trigger window.",
        "rules": "Triggered abilities fire after their event, then wait to be put on the stack the next time a player would get priority. Attack, upkeep, dies, and enters-the-battlefield triggers each have different timing windows.",
    },
    "Mode selection": {
        "note": "Choices are locked in while casting or activating, not later.",
        "rules": "Modes are chosen as the spell or ability is put on the stack. You do not wait until resolution to decide them.",
    },
    "Additional casting costs": {
        "note": "Extra costs must be paid during casting, not after the spell resolves.",
        "rules": "Additional costs are part of casting the spell. They are paid up front and still matter even if the spell is later countered.",
    },
    "Stack interaction": {
        "note": "This card depends on priority windows and target legality.",
        "rules": "Track when players receive priority and whether the spell or ability still has legal targets when it resolves.",
    },
    "Alternate zone casting": {
        "note": "Casting from another zone changes timing and resource assumptions.",
        "rules": "Permission to cast from graveyard, exile, or another zone does not bypass normal timing unless the card explicitly says so. Extra costs and restrictions still apply.",
    },
}

MECHANIC_COPY: Dict[str, Dict[str, str]] = {
    "Banding": {
        "note": "Banding is legacy combat tech. Most tables misremember how it works.",
        "rules": "Banding matters in declare attackers and combat damage assignment. The controller of a blocking or blocked band, not the attacking player, can assign combat damage within that banding combat.",
    },
    "Bands with other": {
        "note": "Bands with other is even narrower than banding and is rarely played correctly.",
        "rules": "Bands with other only forms legal bands with the stated creature type or quality. It still uses banding combat-assignment rules once the band exists.",
    },
    "Protection": {
        "note": "Protection stops more than damage.",
        "rules": "Protection blocks four things: damage, enchanting/equipping, blocking, and targeting from the stated quality. DEBT is the safe mnemonic.",
    },
    "Phasing": {
        "note": "Phasing is not leaving the battlefield, so many normal zone-change assumptions are wrong.",
        "rules": "Phasing does not trigger enters or leaves-the-battlefield abilities. Phased-out permanents keep their attachments and phase back in during untap.",
    },
    "Morph": {
        "note": "Face-down creatures create hidden-information and timing traps.",
        "rules": "Turning a face-down permanent face up is a special action, not casting a spell, so it does not use the stack and cannot be responded to directly.",
    },
    "Manifest": {
        "note": "Manifest looks like morph, but the face-up rules are narrower.",
        "rules": "A manifested card can only be turned face up for its morph cost or, if it is a creature card, by revealing it and paying its mana cost if an effect allows that turn-up action.",
    },
    "Suspend": {
        "note": "Suspend changes both timing and payment assumptions.",
        "rules": "A suspended card is cast without paying its mana cost when the last time counter is removed, and that cast still follows any targeting and mode requirements.",
    },
    "Storm": {
        "note": "Storm counts spells cast before it this turn, not copies.",
        "rules": "Storm creates copies on resolution based on how many spells were cast before it in the same turn. The copies are not cast unless an effect explicitly says so.",
    },
    "Split second": {
        "note": "Split second narrows what players can do, but it is not full priority denial.",
        "rules": "While a spell with split second is on the stack, players cannot cast spells or activate non-mana abilities, but special actions and triggered abilities still happen normally.",
    },
    "Daybound": {
        "note": "Daybound/nightbound changes happen by turn structure, not by individual card memory.",
        "rules": "Day and night are game states shared by all permanents with daybound/nightbound. Once introduced, the game tracks them even if the original permanent leaves.",
    },
    "Nightbound": {
        "note": "Nightbound follows the same shared day/night state and can flip unexpectedly for unfamiliar tables.",
        "rules": "Track whether the game is currently day or night. The transition is tied to how many spells were cast on previous turns, not to a single permanent.",
    },
    "Mutate": {
        "note": "Mutate changes how a merged permanent keeps abilities, types, and ownership details.",
        "rules": "A mutated permanent is one object made from several cards. The top card determines name, power, toughness, and types, while the stack of cards contributes abilities.",
    },
    "Companion": {
        "note": "Companion uses outside-the-game procedures that many Commander players shortcut incorrectly.",
        "rules": "A companion starts outside the deck. Putting it into hand requires the companion special action and payment before it can be cast normally.",
    },
    "Adventure": {
        "note": "Adventure cards create zone-tracking mistakes around exile and recasting.",
        "rules": "If an Adventure spell resolves, the card goes to exile and may later be cast from exile as its creature half. If it goes elsewhere, that permission is lost.",
    },
    "Aftermath": {
        "note": "Split-zone casting restrictions on aftermath are easy to miss.",
        "rules": "The aftermath half can be cast only from the graveyard, and once the card leaves the graveyard that permission ends.",
    },
    "Flashback": {
        "note": "Flashback changes both casting zone and what happens after resolution.",
        "rules": "A flashback spell is cast from the graveyard, then gets exiled instead of going anywhere else when it would leave the stack.",
    },
    "Cascade": {
        "note": "Cascade cares about mana value, not total mana spent or copied costs.",
        "rules": "Exile cards until you find a nonland with lower mana value, then you may cast it without paying its mana cost. Additional costs can still apply.",
    },
    "Discover": {
        "note": "Discover offers a cast-or-draw decision that changes sequencing.",
        "rules": "Discover exiles cards until you reveal a nonland of the right mana value or less. You may cast it without paying its mana cost or put it into your hand.",
    },
    "Myriad": {
        "note": "Myriad changes combat math across multiple opponents and creates temporary attackers.",
        "rules": "Myriad creates tapped and attacking token copies for the other opponents. Those tokens are exiled at end of combat and do not stay around.",
    },
    "Melee": {
        "note": "Melee scales by how many opponents were attacked, which changes in multiplayer only.",
        "rules": "Melee counts opponents attacked this combat, not total creatures or total attack triggers.",
    },
    "The monarch": {
        "note": "Monarch introduces an extra game designation that changes combat incentives immediately.",
        "rules": "Being the monarch is a game state attached to a player, not a permanent. Combat damage to the monarch transfers it before end step draws happen.",
    },
    "The initiative": {
        "note": "Initiative uses the dungeon/Undercity subsystem and needs turn-order awareness.",
        "rules": "Taking the initiative causes a venture into the Undercity and passing it requires combat damage to that player, similar to monarch-style tracking.",
    },
    "Foretell": {
        "note": "Foretell splits payment across turns and changes hidden-information decisions.",
        "rules": "Foretelling is a special action, then the spell is cast from exile on a later turn for its foretell cost if timing allows.",
    },
}

LEGACY_KEYWORDS = {
    "banding": "Banding",
    "bands with other": "Bands with other",
    "phasing": "Phasing",
    "protection": "Protection",
    "morph": "Morph",
    "manifest": "Manifest",
    "suspend": "Suspend",
    "storm": "Storm",
    "split second": "Split second",
    "daybound": "Daybound",
    "nightbound": "Nightbound",
    "mutate": "Mutate",
    "companion": "Companion",
    "adventure": "Adventure",
    "aftermath": "Aftermath",
    "flashback": "Flashback",
    "cascade": "Cascade",
    "discover": "Discover",
    "myriad": "Myriad",
    "melee": "Melee",
    "the monarch": "The monarch",
    "the initiative": "The initiative",
    "foretell": "Foretell",
}

RULE_QUERY_MAPPING = {
    "Replacement effect": "replacement effect",
    "Continuous condition": "continuous effect layer",
    "Conditional replacement": "if instead replacement",
    "Triggered timing": "triggered ability timing",
    "Mode selection": "modal spells choose one",
    "Additional casting costs": "additional costs casting spell",
    "Stack interaction": "counter target spell",
    "Alternate zone casting": "cast from graveyard",
}


def _oracle_text(card: Dict) -> str:
    text = str(card.get("oracle_text") or "").strip()
    if text:
        return text
    face_texts = [str(face.get("oracle_text") or "").strip() for face in (card.get("card_faces") or []) if str(face.get("oracle_text") or "").strip()]
    return "\n".join(face_texts)


def _complexity_flags(oracle_text: str) -> List[str]:
    txt = (oracle_text or "").lower()
    out: List[str] = []
    if "instead" in txt:
        out.append("Replacement effect")
    if "as long as" in txt or "for as long as" in txt:
        out.append("Continuous condition")
    if "if " in txt and "instead" in txt:
        out.append("Conditional replacement")
    if "at the beginning of" in txt or "whenever" in txt or "when " in txt:
        out.append("Triggered timing")
    if "choose one" in txt or "choose two" in txt or "choose one or both" in txt:
        out.append("Mode selection")
    if "as an additional cost" in txt or "additional cost" in txt or "rather than pay" in txt:
        out.append("Additional casting costs")
    if "counter target" in txt or "countered" in txt:
        out.append("Stack interaction")
    if "cast from your graveyard" in txt or "cast from exile" in txt or "flashback" in txt or "foretell" in txt:
        out.append("Alternate zone casting")
    return list(dict.fromkeys(out))


def _legacy_or_nonintuitive_flags(card: Dict) -> List[str]:
    txt = _oracle_text(card).lower()
    keywords = [str(k).lower() for k in (card.get("keywords") or [])]
    haystack = " ".join([txt, " ".join(keywords)])
    found: List[str] = []
    for needle, label in LEGACY_KEYWORDS.items():
        if needle in haystack:
            found.append(label)
    return list(dict.fromkeys(found))


def _legacy_age_note(card: Dict) -> str | None:
    released_at = str(card.get("released_at") or "").strip()
    if not released_at:
        return None
    year_text = released_at.split("-")[0]
    try:
        year = int(year_text)
    except Exception:
        return None
    if year <= 2003:
        return f"This is from an older rules era ({year}), so players often remember a printed-era wording instead of the current Oracle wording."
    return None


def _rule_keywords(flags: List[str]) -> List[str]:
    out = []
    for f in flags:
        if f in RULE_QUERY_MAPPING:
            out.append(RULE_QUERY_MAPPING[f])
    return out


def _ruling_errata(rulings: List[Dict]) -> List[str]:
    out: List[str] = []
    for ruling in rulings[:4]:
        if not isinstance(ruling, dict):
            continue
        comment = str(ruling.get("comment") or "").strip()
        if not comment:
            continue
        published = str(ruling.get("published_at") or "").strip()
        out.append(f"{published}: {comment}" if published else comment)
    return list(dict.fromkeys(out))


def _build_notes(flags: List[str], mechanics: List[str], card: Dict, rulings: List[Dict]) -> List[str]:
    notes = [FLAG_COPY[f]["note"] for f in flags if f in FLAG_COPY]
    notes.extend(MECHANIC_COPY[m]["note"] for m in mechanics if m in MECHANIC_COPY)
    age_note = _legacy_age_note(card)
    if age_note and (flags or mechanics or rulings):
        notes.append(age_note)
    return list(dict.fromkeys(notes))


def _build_rules_information(flags: List[str], mechanics: List[str]) -> List[str]:
    rules = [FLAG_COPY[f]["rules"] for f in flags if f in FLAG_COPY]
    rules.extend(MECHANIC_COPY[m]["rules"] for m in mechanics if m in MECHANIC_COPY)
    return list(dict.fromkeys(rules))


def _watchout_score(card_name: str, commanders: List[str], flags: List[str], mechanics: List[str], rulings: List[Dict]) -> tuple:
    commander_set = set(commanders)
    return (
        0 if card_name in commander_set else 1,
        -(len(rulings) * 4 + len(mechanics) * 3 + len(flags) * 2),
        card_name.lower(),
    )


def build_rules_watchouts(cards: List[CardEntry], commander: str | None) -> List[Dict]:
    commander_names = commander_names_from_cards(cards, fallback_commander=commander)
    svc = CardDataService()
    ranked_cards = [c for c in cards if c.section in {"deck", "commander"}]
    names = [c.name for c in ranked_cards]
    card_map = svc.get_cards_by_name(names)
    rulings_by_oracle = svc.get_rulings_by_oracle_id(card_map)

    enriched_rows = []
    for c in ranked_cards:
        card = card_map.get(c.name, {})
        oracle_text = _oracle_text(card)
        flags = _complexity_flags(oracle_text)
        mechanics = _legacy_or_nonintuitive_flags(card)
        rulings = rulings_by_oracle.get(card.get("oracle_id"), [])
        errata = _ruling_errata(rulings)
        notes = _build_notes(flags, mechanics, card, rulings)
        rules_information = _build_rules_information(flags, mechanics)
        if not errata and not notes and not rules_information:
            continue
        enriched_rows.append(
            {
                "card": c.name,
                "commander": c.name in set(commander_names),
                "complexity_flags": list(dict.fromkeys(flags + mechanics)),
                "rule_queries": _rule_keywords(flags),
                "oracle_watchout": oracle_text[:400],
                "rulings": [
                    {"published_at": r.get("published_at"), "comment": str(r.get("comment") or "")}
                    for r in rulings[:4]
                    if isinstance(r, dict) and str(r.get("comment") or "").strip()
                ],
                "errata": errata,
                "notes": notes,
                "rules_information": rules_information,
                "scryfall_uri": card.get("scryfall_uri"),
            }
        )

    enriched_rows.sort(
        key=lambda row: _watchout_score(
            row["card"],
            commander_names,
            row.get("complexity_flags", []),
            [f for f in row.get("complexity_flags", []) if f in MECHANIC_COPY],
            row.get("rulings", []),
        )
    )
    return enriched_rows
