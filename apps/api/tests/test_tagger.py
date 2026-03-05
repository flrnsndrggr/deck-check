from app.schemas.deck import CardEntry
from app.services.tagger import compute_archetype_weights, tag_cards


def test_tagging_snapshot_staples():
    cards = [CardEntry(qty=1, name="Sol Ring", section="deck"), CardEntry(qty=1, name="Swords to Plowshares", section="deck")]
    card_map = {
        "Sol Ring": {
            "type_line": "Artifact",
            "oracle_text": "{T}: Add {C}{C}.",
            "produced_mana": ["C"],
        },
        "Swords to Plowshares": {
            "type_line": "Instant",
            "oracle_text": "Exile target creature.",
            "produced_mana": [],
        },
    }
    tagged, _, _ = tag_cards(cards, card_map, commander=None, use_global_prefix=True)
    tags = {c.name: set(c.tags) for c in tagged}
    assert "#Rock" in tags["Sol Ring"]
    assert "#Ramp" in tags["Sol Ring"]
    assert "#Removal" in tags["Swords to Plowshares"]


def test_fast_mana_is_subtag_of_ramp_not_replacement():
    cards = [
        CardEntry(qty=1, name="Mana Crypt", section="deck"),
        CardEntry(qty=1, name="Arcane Signet", section="deck"),
    ]
    card_map = {
        "Mana Crypt": {
            "type_line": "Artifact",
            "oracle_text": "{T}: Add {C}{C}.",
            "cmc": 0,
            "produced_mana": ["C"],
        },
        "Arcane Signet": {
            "type_line": "Artifact",
            "oracle_text": "{T}: Add one mana of any color in your commander's color identity.",
            "cmc": 2,
            "produced_mana": ["W", "U", "B", "R", "G"],
        },
    }
    tagged, _, _ = tag_cards(cards, card_map, commander=None, use_global_prefix=True)
    tags = {c.name: set(c.tags) for c in tagged}

    assert "#Ramp" in tags["Mana Crypt"]
    assert "#FastMana" in tags["Mana Crypt"]
    assert "#Ramp" in tags["Arcane Signet"]
    assert "#FastMana" not in tags["Arcane Signet"]


def test_archetype_weighting_handles_phrase_signals():
    cards = [CardEntry(qty=1, name="A", section="deck"), CardEntry(qty=1, name="B", section="deck")]
    card_map = {
        "A": {"type_line": "Instant", "oracle_text": "Copy target spell. Draw a card."},
        "B": {"type_line": "Creature", "oracle_text": "Whenever you cast an instant or sorcery spell, draw a card."},
    }
    w = compute_archetype_weights(cards, card_map, commander=None)
    assert w["spellslinger"] > 0
    assert w["combo"] > 0
