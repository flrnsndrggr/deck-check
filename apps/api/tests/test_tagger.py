from app.schemas.deck import CardEntry
from app.services.tagger import compute_archetype_weights, compute_type_theme_profile, tag_cards


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


def test_type_theme_profile_tracks_creature_subtypes_and_packages():
    cards = [
        CardEntry(qty=1, name="Bird A", section="deck"),
        CardEntry(qty=1, name="Bird B", section="deck"),
        CardEntry(qty=1, name="Bird C", section="deck"),
        CardEntry(qty=1, name="Bird D", section="deck"),
        CardEntry(qty=1, name="Bird E", section="deck"),
        CardEntry(qty=1, name="Bird F", section="deck"),
        CardEntry(qty=1, name="Sword", section="deck"),
        CardEntry(qty=1, name="Shield", section="deck"),
        CardEntry(qty=1, name="Aura A", section="deck"),
        CardEntry(qty=1, name="Aura B", section="deck"),
    ]
    card_map = {
        "Bird A": {"type_line": "Creature — Bird", "oracle_text": ""},
        "Bird B": {"type_line": "Creature — Bird", "oracle_text": ""},
        "Bird C": {"type_line": "Creature — Bird", "oracle_text": ""},
        "Bird D": {"type_line": "Creature — Bird", "oracle_text": ""},
        "Bird E": {"type_line": "Creature — Bird", "oracle_text": ""},
        "Bird F": {"type_line": "Creature — Bird", "oracle_text": ""},
        "Sword": {"type_line": "Artifact — Equipment", "oracle_text": ""},
        "Shield": {"type_line": "Artifact — Equipment", "oracle_text": ""},
        "Aura A": {"type_line": "Enchantment — Aura", "oracle_text": ""},
        "Aura B": {"type_line": "Enchantment — Aura", "oracle_text": ""},
    }
    profile = compute_type_theme_profile(cards, card_map)
    assert profile["dominant_creature_subtype"]["name"] == "Bird"
    assert any("Bird is the main creature subtype package" in line for line in profile["package_signals"])


def test_archetype_weighting_uses_subtype_signal_for_typal_decks():
    cards = [CardEntry(qty=1, name=f"Bird {i}", section="deck") for i in range(1, 7)]
    card_map = {f"Bird {i}": {"type_line": "Creature — Bird", "oracle_text": ""} for i in range(1, 7)}
    w = compute_archetype_weights(cards, card_map, commanders=None)
    assert w["tribal"] > 0
