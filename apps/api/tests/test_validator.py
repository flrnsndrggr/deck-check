from app.schemas.deck import CardEntry
from app.services.validator import validate_deck


def test_color_identity_violation_dfc_style():
    cards = [
        CardEntry(qty=1, name="Commander Card", section="commander"),
        CardEntry(qty=99, name="OffColor Spell", section="deck"),
    ]
    card_map = {
        "Commander Card": {
            "type_line": "Legendary Creature — Human",
            "legalities": {"commander": "legal"},
            "color_identity": ["G"],
            "oracle_text": "",
        },
        "OffColor Spell": {
            "type_line": "Instant",
            "legalities": {"commander": "legal"},
            "color_identity": ["U"],
            "oracle_text": "",
        },
    }
    errors, _, _ = validate_deck(cards, "Commander Card", card_map, 3)
    assert any("Color identity violation" in e for e in errors)


def test_singleton_exception_relentless_rats():
    cards = [
        CardEntry(qty=1, name="Commander Card", section="commander"),
        CardEntry(qty=99, name="Relentless Rats", section="deck"),
    ]
    card_map = {
        "Commander Card": {
            "type_line": "Legendary Creature — Human",
            "legalities": {"commander": "legal"},
            "color_identity": ["B"],
            "oracle_text": "",
        },
        "Relentless Rats": {
            "type_line": "Creature — Rat",
            "legalities": {"commander": "legal"},
            "color_identity": ["B"],
            "oracle_text": "A deck can have any number of cards named Relentless Rats.",
        },
    }
    errors, _, _ = validate_deck(cards, "Commander Card", card_map, 3)
    assert not any("Singleton violation" in e for e in errors)


def test_legendary_artifact_creature_is_valid_commander():
    cards = [
        CardEntry(qty=1, name="The Peregrine Dynamo", section="commander"),
        CardEntry(qty=99, name="Filler", section="deck"),
    ]
    card_map = {
        "The Peregrine Dynamo": {
            "type_line": "Legendary Artifact Creature — Construct",
            "legalities": {"commander": "legal"},
            "color_identity": [],
            "oracle_text": "",
        },
        "Filler": {
            "type_line": "Artifact",
            "legalities": {"commander": "legal"},
            "color_identity": [],
            "oracle_text": "",
        },
    }
    errors, _, _ = validate_deck(cards, "The Peregrine Dynamo", card_map, 3)
    assert not any("Commander is not legal/valid as commander" in e for e in errors)


def test_validator_enforces_100_card_main_deck():
    cards = [
        CardEntry(qty=1, name="Commander Card", section="commander"),
        CardEntry(qty=98, name="Filler", section="deck"),
    ]
    card_map = {
        "Commander Card": {
            "type_line": "Legendary Creature — Human",
            "legalities": {"commander": "legal"},
            "color_identity": ["G"],
            "oracle_text": "",
        },
        "Filler": {
            "type_line": "Creature",
            "legalities": {"commander": "legal"},
            "color_identity": ["G"],
            "oracle_text": "",
        },
    }
    errors, _, _ = validate_deck(cards, "Commander Card", card_map, 3)
    assert any("exactly 100 cards" in e for e in errors)


def test_validator_rejects_commander_qty_not_one():
    cards = [
        CardEntry(qty=2, name="Commander Card", section="commander"),
        CardEntry(qty=98, name="Filler", section="deck"),
    ]
    card_map = {
        "Commander Card": {
            "type_line": "Legendary Creature — Human",
            "legalities": {"commander": "legal"},
            "color_identity": ["G"],
            "oracle_text": "",
        },
        "Filler": {
            "type_line": "Creature",
            "legalities": {"commander": "legal"},
            "color_identity": ["G"],
            "oracle_text": "",
        },
    }
    errors, _, _ = validate_deck(cards, "Commander Card", card_map, 3)
    assert any("Commander quantity must be exactly 1" in e for e in errors)


def test_bracket_report_includes_criteria_and_matching_cards(tmp_path, monkeypatch):
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    (rules_dir / "game_changers.json").write_text('{"cards":["Sol Ring"]}')
    (rules_dir / "banned.json").write_text('{"banned":[],"banned_as_companion":[]}')
    (rules_dir / "brackets.json").write_text('{"limits":{"3":2}}')

    monkeypatch.setattr("app.services.validator.settings.rules_cache_dir", str(rules_dir))

    cards = [
        CardEntry(qty=1, name="Commander Card", section="commander", tags=[]),
        CardEntry(qty=1, name="Sol Ring", section="deck", tags=["#Ramp", "#FastMana"]),
        CardEntry(qty=98, name="Wastes", section="deck", tags=["#Land"]),
    ]
    card_map = {
        "Commander Card": {
            "type_line": "Legendary Creature — Human",
            "legalities": {"commander": "legal"},
            "color_identity": [],
            "oracle_text": "",
        },
        "Sol Ring": {
            "type_line": "Artifact",
            "legalities": {"commander": "legal"},
            "color_identity": [],
            "oracle_text": "{T}: Add {C}{C}.",
        },
        "Wastes": {
            "type_line": "Land",
            "legalities": {"commander": "legal"},
            "color_identity": [],
            "oracle_text": "",
        },
    }
    errors, _, report = validate_deck(cards, "Commander Card", card_map, 3)
    assert not errors
    assert report["bracket"] == 3
    assert report["criteria"]
    gc = next((c for c in report["criteria"] if c["key"] == "game_changers"), None)
    assert gc is not None
    assert gc["current"] == 1
    assert any(x["name"] == "Sol Ring" for x in gc["cards"])


def test_validator_accepts_partner_pair_and_combined_color_identity():
    cards = [
        CardEntry(qty=1, name="Tymna the Weaver", section="commander"),
        CardEntry(qty=1, name="Kraum, Ludevic's Opus", section="commander"),
        CardEntry(qty=1, name="Esper Card", section="deck"),
        CardEntry(qty=97, name="Plains", section="deck"),
    ]
    card_map = {
        "Tymna the Weaver": {
            "type_line": "Legendary Creature — Human Cleric",
            "legalities": {"commander": "legal"},
            "color_identity": ["W", "B"],
            "oracle_text": "Partner",
        },
        "Kraum, Ludevic's Opus": {
            "type_line": "Legendary Creature — Zombie Horror",
            "legalities": {"commander": "legal"},
            "color_identity": ["U", "R"],
            "oracle_text": "Flying, haste\nPartner",
        },
        "Esper Card": {
            "type_line": "Sorcery",
            "legalities": {"commander": "legal"},
            "color_identity": ["W", "U", "B"],
            "oracle_text": "",
        },
        "Plains": {
            "type_line": "Basic Land — Plains",
            "legalities": {"commander": "legal"},
            "color_identity": ["W"],
            "oracle_text": "",
        },
    }
    errors, _, _ = validate_deck(cards, "Tymna the Weaver", card_map, 3)
    assert not errors


def test_validator_accepts_choose_a_background_pair():
    cards = [
        CardEntry(qty=1, name="Abdel Adrian, Gorion's Ward", section="commander"),
        CardEntry(qty=1, name="Candlekeep Sage", section="commander"),
        CardEntry(qty=1, name="Azorius Card", section="deck"),
        CardEntry(qty=97, name="Plains", section="deck"),
    ]
    card_map = {
        "Abdel Adrian, Gorion's Ward": {
            "type_line": "Legendary Creature — Human Warrior",
            "legalities": {"commander": "legal"},
            "color_identity": ["W"],
            "oracle_text": "Choose a Background",
        },
        "Candlekeep Sage": {
            "type_line": "Legendary Enchantment — Background",
            "legalities": {"commander": "legal"},
            "color_identity": ["U"],
            "oracle_text": "Commander creatures you own have ...",
        },
        "Azorius Card": {
            "type_line": "Instant",
            "legalities": {"commander": "legal"},
            "color_identity": ["W", "U"],
            "oracle_text": "",
        },
        "Plains": {
            "type_line": "Basic Land — Plains",
            "legalities": {"commander": "legal"},
            "color_identity": ["W"],
            "oracle_text": "",
        },
    }
    errors, _, _ = validate_deck(cards, "Abdel Adrian, Gorion's Ward", card_map, 3)
    assert not errors


def test_validator_rejects_two_commanders_without_legal_pairing():
    cards = [
        CardEntry(qty=1, name="Commander A", section="commander"),
        CardEntry(qty=1, name="Commander B", section="commander"),
        CardEntry(qty=98, name="Filler", section="deck"),
    ]
    card_map = {
        "Commander A": {
            "type_line": "Legendary Creature — Human",
            "legalities": {"commander": "legal"},
            "color_identity": ["G"],
            "oracle_text": "",
        },
        "Commander B": {
            "type_line": "Legendary Creature — Human",
            "legalities": {"commander": "legal"},
            "color_identity": ["G"],
            "oracle_text": "",
        },
        "Filler": {
            "type_line": "Creature",
            "legalities": {"commander": "legal"},
            "color_identity": ["G"],
            "oracle_text": "",
        },
    }
    errors, _, _ = validate_deck(cards, "Commander A", card_map, 3)
    assert any("legal pairing" in e or "legal/valid" in e for e in errors)
