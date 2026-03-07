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
            "oracle_text": "Lifelink\nAt the beginning of your postcombat main phase, you may pay X life, where X is the number of opponents that were dealt combat damage this turn. If you do, draw X cards.\nPartner (You can have two commanders if both have partner.)",
        },
        "Kraum, Ludevic's Opus": {
            "type_line": "Legendary Creature — Zombie Horror",
            "legalities": {"commander": "legal"},
            "color_identity": ["U", "R"],
            "oracle_text": "Flying, haste\nWhenever an opponent casts their second spell each turn, draw a card.\nPartner (You can have two commanders if both have partner.)",
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


def test_validator_accepts_original_partner_pair_with_realistic_oracle_text():
    cards = [
        CardEntry(qty=1, name="Vial Smasher the Fierce", section="commander"),
        CardEntry(qty=1, name="Thrasios, Triton Hero", section="commander"),
        CardEntry(qty=1, name="Blue Card", section="deck"),
        CardEntry(qty=97, name="Island", section="deck"),
    ]
    card_map = {
        "Vial Smasher the Fierce": {
            "type_line": "Legendary Creature — Goblin Berserker",
            "legalities": {"commander": "legal"},
            "color_identity": ["B", "R"],
            "oracle_text": "Whenever you cast your first spell each turn, Vial Smasher the Fierce deals damage equal to that spell's mana value to an opponent chosen at random.\nPartner (You can have two commanders if both have partner.)",
        },
        "Thrasios, Triton Hero": {
            "type_line": "Legendary Creature — Merfolk Wizard",
            "legalities": {"commander": "legal"},
            "color_identity": ["G", "U"],
            "oracle_text": "{4}: Scry 1, then reveal the top card of your library. If it's a land card, put it onto the battlefield tapped. Otherwise draw a card.\nPartner (You can have two commanders if both have partner.)",
        },
        "Blue Card": {
            "type_line": "Instant",
            "legalities": {"commander": "legal"},
            "color_identity": ["U"],
            "oracle_text": "",
        },
        "Island": {
            "type_line": "Basic Land — Island",
            "legalities": {"commander": "legal"},
            "color_identity": ["U"],
            "oracle_text": "",
        },
    }
    errors, _, _ = validate_deck(cards, "Vial Smasher the Fierce", card_map, 3)
    assert not errors


def test_validate_deck_can_infer_low_bracket_from_fair_shell(tmp_path, monkeypatch):
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    (rules_dir / "game_changers.json").write_text('{"cards":[]}')
    (rules_dir / "banned.json").write_text('{"banned":[],"banned_as_companion":[]}')
    (rules_dir / "brackets.json").write_text('{"limits":{"1":0,"2":0,"3":2,"4":5,"5":100}}')
    monkeypatch.setattr("app.services.validator.settings.rules_cache_dir", str(rules_dir))

    cards = [
        CardEntry(qty=1, name="Commander Card", section="commander", tags=["#CommanderSynergy"]),
        CardEntry(qty=99, name="Forest", section="deck", tags=["#Land"]),
    ]
    card_map = {
        "Commander Card": {
            "type_line": "Legendary Creature — Elf Druid",
            "legalities": {"commander": "legal"},
            "color_identity": ["G"],
            "oracle_text": "Whenever another creature enters the battlefield under your control, you gain 1 life.",
        },
        "Forest": {
            "type_line": "Basic Land — Forest",
            "legalities": {"commander": "legal"},
            "color_identity": ["G"],
            "oracle_text": "",
        },
    }
    errors, _, report = validate_deck(cards, "Commander Card", card_map, None, tagged_cards=cards)
    assert not errors
    assert report["source"] == "inferred"
    assert report["bracket"] in {1, 2}


def test_validate_deck_can_infer_high_bracket_from_fast_combo_shell(tmp_path, monkeypatch):
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    (rules_dir / "game_changers.json").write_text('{"cards":["Mana Crypt","Jeweled Lotus"]}')
    (rules_dir / "banned.json").write_text('{"banned":[],"banned_as_companion":[]}')
    (rules_dir / "brackets.json").write_text('{"limits":{"1":0,"2":0,"3":2,"4":5,"5":100}}')
    monkeypatch.setattr("app.services.validator.settings.rules_cache_dir", str(rules_dir))

    cards = [
        CardEntry(qty=1, name="Commander Card", section="commander", tags=["#Combo", "#CommanderSynergy"]),
        CardEntry(qty=1, name="Mana Crypt", section="deck", tags=["#Ramp", "#FastMana"]),
        CardEntry(qty=1, name="Jeweled Lotus", section="deck", tags=["#Ramp", "#FastMana"]),
        CardEntry(qty=1, name="Demonic Tutor", section="deck", tags=["#Tutor"]),
        CardEntry(qty=1, name="Vampiric Tutor", section="deck", tags=["#Tutor"]),
        CardEntry(qty=1, name="Mystical Tutor", section="deck", tags=["#Tutor"]),
        CardEntry(qty=1, name="Thassa's Oracle", section="deck", tags=["#Combo", "#Wincon"]),
        CardEntry(qty=1, name="Demonic Consultation", section="deck", tags=["#Combo", "#Wincon"]),
        CardEntry(qty=92, name="Island", section="deck", tags=["#Land"]),
    ]
    card_map = {
        "Commander Card": {
            "type_line": "Legendary Creature — Human Wizard",
            "legalities": {"commander": "legal"},
            "color_identity": ["U", "B"],
            "oracle_text": "Partner",
        },
        "Mana Crypt": {"type_line": "Artifact", "legalities": {"commander": "legal"}, "color_identity": [], "oracle_text": "{T}: Add {C}{C}."},
        "Jeweled Lotus": {"type_line": "Artifact", "legalities": {"commander": "legal"}, "color_identity": [], "oracle_text": "{T}, Sacrifice Jeweled Lotus: Add three mana of any one color. Spend this mana only to cast your commander."},
        "Demonic Tutor": {"type_line": "Sorcery", "legalities": {"commander": "legal"}, "color_identity": ["B"], "oracle_text": "Search your library for a card, put that card into your hand, then shuffle."},
        "Vampiric Tutor": {"type_line": "Instant", "legalities": {"commander": "legal"}, "color_identity": ["B"], "oracle_text": "Search your library for a card, then shuffle and put that card on top."},
        "Mystical Tutor": {"type_line": "Instant", "legalities": {"commander": "legal"}, "color_identity": ["U"], "oracle_text": "Search your library for an instant or sorcery card, reveal it, then shuffle and put that card on top."},
        "Thassa's Oracle": {"type_line": "Creature — Merfolk Wizard", "legalities": {"commander": "legal"}, "color_identity": ["U"], "oracle_text": "When Thassa's Oracle enters the battlefield, look at the top X cards of your library."},
        "Demonic Consultation": {"type_line": "Instant", "legalities": {"commander": "legal"}, "color_identity": ["B"], "oracle_text": "Choose a card name. Exile the top six cards of your library, then reveal cards from the top until you reveal the named card."},
        "Island": {"type_line": "Basic Land — Island", "legalities": {"commander": "legal"}, "color_identity": ["U"], "oracle_text": ""},
    }
    errors, _, report = validate_deck(
        cards,
        "Commander Card",
        card_map,
        None,
        tagged_cards=cards,
        sim_summary={"win_metrics": {"median_win_turn": 5}},
    )
    assert not errors
    assert report["source"] == "inferred"
    assert report["bracket"] >= 4


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
            "oracle_text": "When Abdel Adrian, Gorion's Ward enters, exile any number of other nonland permanents you control until Abdel Adrian leaves the battlefield.\nChoose a Background (You can have a Background as a second commander.)",
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
