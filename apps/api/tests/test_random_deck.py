from app.services.parser import parse_decklist
from app.services.random_deck import RandomDeckService, GENERIC_NONBASIC_LANDS
from app.services.scryfall import CardDataService
from app.services.validator import validate_deck


def _make_card(name: str, **overrides):
    payload = {
        "name": name,
        "oracle_id": f"oid-{name.lower().replace(' ', '-')}",
        "mana_cost": "{1}{W}",
        "cmc": 2,
        "type_line": "Creature — Soldier",
        "oracle_text": "",
        "color_identity": ["W"],
        "legalities": {"commander": "legal"},
    }
    payload.update(overrides)
    return payload


def _make_shell(color="W"):
    interaction_cards = [
        _make_card(
            f"Quick Answer {idx}",
            mana_cost=f"{{{color}}}",
            cmc=1,
            type_line="Instant",
            oracle_text="Destroy target attacking creature.",
            color_identity=[color],
        )
        for idx in range(15)
    ]
    ramp_cards = [
        _make_card(
            f"Mana Rock {idx}",
            mana_cost="{2}",
            cmc=2,
            type_line="Artifact",
            oracle_text=f"{{T}}: Add {{{color}}}.",
            color_identity=[],
        )
        for idx in range(16)
    ]
    draw_cards = [
        _make_card(
            f"Insight {idx}",
            mana_cost=f"{{2}}{{{color}}}",
            cmc=3,
            type_line="Sorcery",
            oracle_text="Draw two cards.",
            color_identity=[color],
        )
        for idx in range(12)
    ]
    synergy_cards = [
        _make_card(
            f"Synergy Card {idx}",
            mana_cost=f"{{2}}{{{color}}}",
            cmc=3,
            type_line="Creature — Soldier",
            oracle_text="Whenever you cast a spell, draw a card.",
            color_identity=[color],
        )
        for idx in range(90)
    ]
    return interaction_cards, ramp_cards, draw_cards, synergy_cards


def _make_land_map(colors):
    basics = {
        "W": "Plains",
        "U": "Island",
        "B": "Swamp",
        "R": "Mountain",
        "G": "Forest",
    }
    out = {
        name: _make_card(
            name,
            mana_cost="",
            cmc=0,
            type_line="Land",
            oracle_text="{T}: Add {C}.",
            color_identity=[],
        )
        for name in GENERIC_NONBASIC_LANDS + ["Wastes"]
    }
    for color in colors:
        basic_name = basics[color]
        out[basic_name] = _make_card(
            basic_name,
            mana_cost="",
            cmc=0,
            type_line="Land",
            oracle_text=f"{{T}}: Add {{{color}}}.",
            color_identity=[],
        )
    return out


def _fake_search_factory(interaction_cards, ramp_cards, draw_cards, synergy_cards):
    def fake_search(self, query, color_identity, limit=10):
        if 'mv<=2' in query:
            return interaction_cards
        if 'mv<=4' in query:
            return ramp_cards + synergy_cards[:10]
        if 'mv<=5' in query:
            return draw_cards + synergy_cards[:10]
        return synergy_cards

    return fake_search


def test_random_deck_generator_builds_legal_shell(monkeypatch):
    commander = _make_card(
        "Captain of Relics",
        mana_cost="{2}{W}",
        cmc=3,
        type_line="Legendary Creature — Human Artificer",
        oracle_text="Whenever you cast an artifact spell, create a 1/1 colorless Thopter artifact creature token with flying.",
    )

    interaction_cards, ramp_cards, draw_cards, synergy_cards = _make_shell("W")
    synergy_cards = [
        _make_card(
            f"Servo Maker {idx}",
            mana_cost="{2}{W}",
            cmc=3,
            type_line="Artifact Creature — Thopter",
            oracle_text="When this enters, create a 1/1 colorless Thopter artifact creature token with flying.",
            color_identity=["W"],
        )
        for idx in range(80)
    ]

    land_map = _make_land_map(["W"])

    lookup = {
        commander["name"]: commander,
        **{card["name"]: card for card in interaction_cards},
        **{card["name"]: card for card in ramp_cards},
        **{card["name"]: card for card in draw_cards},
        **{card["name"]: card for card in synergy_cards},
        **land_map,
    }

    def fake_random(self):
        return commander

    def fake_get_by_names(self, names):
        return {name: lookup[name] for name in names if name in lookup}

    monkeypatch.setattr(RandomDeckService, "_random_commander", fake_random)
    monkeypatch.setattr(CardDataService, "search_candidates", _fake_search_factory(interaction_cards, ramp_cards, draw_cards, synergy_cards))
    monkeypatch.setattr(CardDataService, "get_cards_by_name", fake_get_by_names)

    svc = RandomDeckService()
    out = svc.generate(bracket=3)
    parsed = parse_decklist(out["decklist_text"])
    card_map = {name: lookup[name] for name in [card.name for card in parsed.cards]}
    errors, warnings, _ = validate_deck(parsed.cards, parsed.commander, card_map, 3)

    assert not errors
    assert parsed.commander == "Captain of Relics"
    assert sum(card.qty for card in parsed.cards if card.section in {"deck", "commander"}) == 100
    assert sum(card.qty for card in parsed.cards if card.section == "deck" and lookup[card.name]["type_line"].startswith("Land")) == 38
    assert 10 <= out["interaction_count"] <= 15
    assert isinstance(warnings, list)


def test_random_deck_generator_adds_second_commander_for_original_partner(monkeypatch):
    primary = _make_card(
        "Alpha Partner",
        mana_cost="{1}{R}",
        cmc=2,
        type_line="Legendary Creature — Human Warrior",
        oracle_text="Haste\nPartner (You can have two commanders if both have partner.)",
        color_identity=["R"],
    )
    secondary = _make_card(
        "Bravo Partner",
        mana_cost="{1}{U}",
        cmc=2,
        type_line="Legendary Creature — Merfolk Wizard",
        oracle_text="Partner (You can have two commanders if both have partner.)",
        color_identity=["U"],
    )
    interaction_cards, ramp_cards, draw_cards, synergy_cards = _make_shell("U")
    land_map = _make_land_map(["U", "R"])
    lookup = {
        primary["name"]: primary,
        secondary["name"]: secondary,
        **{card["name"]: card for card in interaction_cards + ramp_cards + draw_cards + synergy_cards},
        **land_map,
    }

    def fake_random_commander(self):
        return primary

    def fake_fetch_random(self, query):
        if 'o:"Partner"' in query:
            return secondary
        raise AssertionError(f"Unexpected random query: {query}")

    def fake_get_by_names(self, names):
        return {name: lookup[name] for name in names if name in lookup}

    monkeypatch.setattr(RandomDeckService, "_random_commander", fake_random_commander)
    monkeypatch.setattr(CardDataService, "fetch_random_card", fake_fetch_random)
    monkeypatch.setattr(CardDataService, "search_candidates", _fake_search_factory(interaction_cards, ramp_cards, draw_cards, synergy_cards))
    monkeypatch.setattr(CardDataService, "get_cards_by_name", fake_get_by_names)

    out = RandomDeckService().generate(bracket=3)
    parsed = parse_decklist(out["decklist_text"])
    card_map = {name: lookup[name] for name in [card.name for card in parsed.cards]}
    errors, _, _ = validate_deck(parsed.cards, parsed.commander, card_map, 3)

    assert not errors
    assert out["commanders"] == ["Alpha Partner", "Bravo Partner"]
    assert parsed.commanders == ["Alpha Partner", "Bravo Partner"]
    assert len([card for card in parsed.cards if card.section == "commander"]) == 2


def test_random_deck_generator_adds_partner_with_counterpart(monkeypatch):
    primary = _make_card(
        "Twin Flame",
        mana_cost="{2}{R}",
        cmc=3,
        type_line="Legendary Creature — Human Shaman",
        oracle_text="Partner with Twin Tide (When this creature enters, target player may put Twin Tide into their hand from their library, then shuffle.)",
        color_identity=["R"],
    )
    counterpart = _make_card(
        "Twin Tide",
        mana_cost="{2}{U}",
        cmc=3,
        type_line="Legendary Creature — Merfolk Wizard",
        oracle_text="Partner with Twin Flame (When this creature enters, target player may put Twin Flame into their hand from their library, then shuffle.)",
        color_identity=["U"],
    )
    interaction_cards, ramp_cards, draw_cards, synergy_cards = _make_shell("U")
    land_map = _make_land_map(["U", "R"])
    lookup = {
        primary["name"]: primary,
        counterpart["name"]: counterpart,
        **{card["name"]: card for card in interaction_cards + ramp_cards + draw_cards + synergy_cards},
        **land_map,
    }

    monkeypatch.setattr(RandomDeckService, "_random_commander", lambda self: primary)
    monkeypatch.setattr(CardDataService, "search_candidates", _fake_search_factory(interaction_cards, ramp_cards, draw_cards, synergy_cards))
    monkeypatch.setattr(CardDataService, "get_cards_by_name", lambda self, names: {name: lookup[name] for name in names if name in lookup})

    out = RandomDeckService().generate(bracket=3)
    parsed = parse_decklist(out["decklist_text"])
    card_map = {name: lookup[name] for name in [card.name for card in parsed.cards]}
    errors, _, _ = validate_deck(parsed.cards, parsed.commander, card_map, 3)

    assert not errors
    assert out["commanders"] == ["Twin Flame", "Twin Tide"]
    assert parsed.commanders == ["Twin Flame", "Twin Tide"]


def test_random_deck_generator_adds_background_for_choose_a_background(monkeypatch):
    primary = _make_card(
        "Hero of the Road",
        mana_cost="{2}{W}",
        cmc=3,
        type_line="Legendary Creature — Human Scout",
        oracle_text="Vigilance\nChoose a Background (You can have a Background as a second commander.)",
        color_identity=["W"],
    )
    background = _make_card(
        "Cloak of Echoes",
        mana_cost="{2}{U}",
        cmc=3,
        type_line="Legendary Enchantment — Background",
        oracle_text="Commander creatures you own have ward {2}.",
        color_identity=["U"],
    )
    interaction_cards, ramp_cards, draw_cards, synergy_cards = _make_shell("U")
    land_map = _make_land_map(["U", "W"])
    lookup = {
        primary["name"]: primary,
        background["name"]: background,
        **{card["name"]: card for card in interaction_cards + ramp_cards + draw_cards + synergy_cards},
        **land_map,
    }

    def fake_random_commander(self):
        return primary

    def fake_fetch_random(self, query):
        if "t:background" in query:
            return background
        raise AssertionError(f"Unexpected random query: {query}")

    def fake_get_by_names(self, names):
        return {name: lookup[name] for name in names if name in lookup}

    monkeypatch.setattr(RandomDeckService, "_random_commander", fake_random_commander)
    monkeypatch.setattr(CardDataService, "fetch_random_card", fake_fetch_random)
    monkeypatch.setattr(CardDataService, "search_candidates", _fake_search_factory(interaction_cards, ramp_cards, draw_cards, synergy_cards))
    monkeypatch.setattr(CardDataService, "get_cards_by_name", fake_get_by_names)

    out = RandomDeckService().generate(bracket=3)
    parsed = parse_decklist(out["decklist_text"])
    card_map = {name: lookup[name] for name in [card.name for card in parsed.cards]}
    errors, _, _ = validate_deck(parsed.cards, parsed.commander, card_map, 3)

    assert not errors
    assert out["commanders"] == ["Hero of the Road", "Cloak of Echoes"]
    assert parsed.commanders == ["Hero of the Road", "Cloak of Echoes"]
