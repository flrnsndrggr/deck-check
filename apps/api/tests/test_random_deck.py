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


def test_random_deck_generator_builds_legal_shell(monkeypatch):
    commander = _make_card(
        "Captain of Relics",
        mana_cost="{2}{W}",
        cmc=3,
        type_line="Legendary Creature — Human Artificer",
        oracle_text="Whenever you cast an artifact spell, create a 1/1 colorless Thopter artifact creature token with flying.",
    )

    interaction_cards = [
        _make_card(
            f"Quick Answer {idx}",
            mana_cost="{W}",
            cmc=1,
            type_line="Instant",
            oracle_text="Destroy target attacking creature.",
        )
        for idx in range(15)
    ]
    ramp_cards = [
        _make_card(
            f"Mana Rock {idx}",
            mana_cost="{2}",
            cmc=2,
            type_line="Artifact",
            oracle_text="{T}: Add {W}.",
            color_identity=[],
        )
        for idx in range(16)
    ]
    draw_cards = [
        _make_card(
            f"Insight {idx}",
            mana_cost="{2}{W}",
            cmc=3,
            type_line="Sorcery",
            oracle_text="Draw two cards.",
        )
        for idx in range(12)
    ]
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

    land_map = {
        name: _make_card(
            name,
            mana_cost="",
            cmc=0,
            type_line="Land",
            oracle_text="{T}: Add {W}.",
            color_identity=[],
        )
        for name in GENERIC_NONBASIC_LANDS + ["Plains"]
    }

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

    def fake_search(self, query, color_identity, limit=10):
        if 'mv<=2' in query:
            return interaction_cards
        if 'mv<=4' in query:
            return ramp_cards + synergy_cards[:10]
        if 'mv<=5' in query:
            return draw_cards + synergy_cards[:10]
        return synergy_cards

    def fake_get_by_names(self, names):
        return {name: lookup[name] for name in names if name in lookup}

    monkeypatch.setattr(RandomDeckService, "_random_commander", fake_random)
    monkeypatch.setattr(CardDataService, "search_candidates", fake_search)
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
