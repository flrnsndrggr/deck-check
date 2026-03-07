import random

from app.services.parser import parse_decklist
from app.schemas.deck import CardEntry
from app.services.random_deck import (
    CommanderPlan,
    DeckContext,
    GENERIC_NONBASIC_LANDS,
    GeneratedDeck,
    RandomDeckService,
    TaggedCandidate,
)
from app.services.scryfall import CardDataService, QuerySpec
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


def _make_tagged(
    name: str,
    *,
    tags=None,
    packages=None,
    provides=None,
    needs=None,
    coverage=None,
    roles=None,
    base_score=0.0,
    popularity_rank=None,
    effect_family="generic_value",
    color_identity=None,
    type_line="Creature — Soldier",
    oracle_text="",
):
    card = _make_card(
        name,
        type_line=type_line,
        oracle_text=oracle_text,
        color_identity=color_identity or ["B"],
    )
    return TaggedCandidate(
        card=card,
        entry=CardEntry(qty=1, name=name, section="deck", tags=sorted(set(tags or [])), confidence={}, explanations={}),
        matched_queries=set(),
        roles=set(roles or []),
        packages=set(packages or []),
        provides=set(provides or []),
        needs=set(needs or []),
        coverage=dict(coverage or {}),
        effect_family=effect_family,
        base_score=base_score,
        popularity_rank=popularity_rank,
    )


def _make_context(primary_package: str, secondary_packages=None, commander=None):
    commander = commander or _make_card(
        "Test Commander",
        mana_cost="{1}{B}{B}",
        cmc=3,
        type_line="Legendary Creature — Human Cleric",
        oracle_text="Whenever another creature dies, each opponent loses 1 life and you gain 1 life.",
        color_identity=["B"],
    )
    svc = RandomDeckService(random.Random(1))
    commander_profile = svc._commander_profile([commander])
    plan = CommanderPlan(
        primary_package=primary_package,
        secondary_packages=list(secondary_packages or []),
        confidence=0.9,
        needs=[],
        avoid_tags=[],
        staple_budget=4,
        protection_target=2,
        land_count=38,
        curve_target="mid",
        coverage_targets={
            "role:ramp": (2.0, 4.0),
            "role:draw": (2.0, 4.0),
            "role:interaction": (2.0, 4.0),
            "role:protection": (1.0, 2.0),
            "role:recursion": (0.0, 2.0),
            "role:wipe": (0.0, 2.0),
            "finisher": (1, 3),
            "role:tutor": (0.0, 1.0),
            "bridge": (2.0, 4.0),
            "pkg:primary_enabler": (4.0, 8.0),
            "pkg:primary_payoff": (2.0, 4.0),
        },
        support_targets={},
        novelty_weight=1.0,
        speed_tier="mid",
        subtype_anchor=None,
        commander_archetypes={},
    )
    return DeckContext(
        commander_cards=[commander],
        commander_names=[commander["name"]],
        color_identity="".join(commander.get("color_identity") or []),
        commander_profile=commander_profile,
        plan=plan,
        bracket=3,
    )


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


def _median(values):
    ordered = sorted(values)
    if not ordered:
        return 0.0
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _make_artifact_fixture():
    commander = _make_card(
        "Captain of Relics",
        mana_cost="{2}{W}",
        cmc=3,
        type_line="Legendary Creature — Human Artificer",
        oracle_text="Whenever you cast an artifact spell, create a 1/1 colorless Thopter artifact creature token with flying.",
    )
    interaction_cards, ramp_cards, draw_cards, _ = _make_shell("W")
    artifact_cards = [
        _make_card(
            f"Servo Maker {idx}",
            mana_cost="{2}{W}",
            cmc=3,
            type_line="Artifact Creature — Thopter",
            oracle_text="When this enters, create a 1/1 colorless Thopter artifact creature token with flying.",
            color_identity=["W"],
            edhrec_rank=1800 + idx,
        )
        for idx in range(80)
    ]
    generic_synergy_cards = [
        _make_card(
            f"Generic Value {idx}",
            mana_cost="{2}{W}",
            cmc=3,
            type_line="Creature — Soldier",
            oracle_text="Draw a card.",
            color_identity=["W"],
            edhrec_rank=30 + idx,
        )
        for idx in range(60)
    ]
    synergy_cards = artifact_cards + generic_synergy_cards
    land_map = _make_land_map(["W"])
    lookup = {
        commander["name"]: commander,
        **{card["name"]: card for card in interaction_cards},
        **{card["name"]: card for card in ramp_cards},
        **{card["name"]: card for card in draw_cards},
        **{card["name"]: card for card in synergy_cards},
        **land_map,
    }
    return commander, interaction_cards, ramp_cards, draw_cards, artifact_cards, generic_synergy_cards, synergy_cards, lookup


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


def _fake_search_factory(
    interaction_cards,
    ramp_cards,
    draw_cards,
    synergy_cards,
    *,
    artifact_cards=None,
    enchantment_cards=None,
    partner_cards=None,
    background_cards=None,
):
    artifact_cards = artifact_cards or []
    enchantment_cards = enchantment_cards or []
    partner_cards = partner_cards or []
    background_cards = background_cards or []

    def fake_search(self, query, color_identity, limit=10, order="edhrec", direction="asc"):
        if 'o:"Partner ("' in query:
            return partner_cards[:limit]
        if "t:background" in query:
            return background_cards[:limit]
        if 'mv<=2' in query:
            return interaction_cards
        if 'mv<=4' in query:
            return ramp_cards + synergy_cards[:10]
        if 'mv<=5' in query:
            return draw_cards + synergy_cards[:10]
        if "t:artifact" in query or 'o:"artifact"' in query:
            return (artifact_cards or synergy_cards)[:limit]
        if "t:enchantment" in query or 'o:"enchantment"' in query:
            return (enchantment_cards or synergy_cards)[:limit]
        return synergy_cards

    return fake_search


def test_random_deck_generator_builds_coherent_artifact_shell(monkeypatch):
    commander = _make_card(
        "Captain of Relics",
        mana_cost="{2}{W}",
        cmc=3,
        type_line="Legendary Creature — Human Artificer",
        oracle_text="Whenever you cast an artifact spell, create a 1/1 colorless Thopter artifact creature token with flying.",
    )

    interaction_cards, ramp_cards, draw_cards, _ = _make_shell("W")
    artifact_cards = [
        _make_card(
            f"Servo Maker {idx}",
            mana_cost="{2}{W}",
            cmc=3,
            type_line="Artifact Creature — Thopter",
            oracle_text="When this enters, create a 1/1 colorless Thopter artifact creature token with flying.",
            color_identity=["W"],
            edhrec_rank=1800 + idx,
        )
        for idx in range(80)
    ]
    generic_synergy_cards = [
        _make_card(
            f"Generic Value {idx}",
            mana_cost="{2}{W}",
            cmc=3,
            type_line="Creature — Soldier",
            oracle_text="Draw a card.",
            color_identity=["W"],
            edhrec_rank=60 + idx,
        )
        for idx in range(60)
    ]
    synergy_cards = artifact_cards + generic_synergy_cards

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
    monkeypatch.setattr(
        CardDataService,
        "search_candidates",
        _fake_search_factory(interaction_cards, ramp_cards, draw_cards, synergy_cards, artifact_cards=artifact_cards),
    )
    monkeypatch.setattr(CardDataService, "get_cards_by_name", fake_get_by_names)

    svc = RandomDeckService(random.Random(7))
    out = svc.generate(bracket=3)
    parsed = parse_decklist(out["decklist_text"])
    card_map = {name: lookup[name] for name in [card.name for card in parsed.cards]}
    errors, warnings, _ = validate_deck(parsed.cards, parsed.commander, card_map, 3)

    assert not errors
    assert parsed.commander == "Captain of Relics"
    assert sum(card.qty for card in parsed.cards if card.section in {"deck", "commander"}) == 100
    assert sum(card.qty for card in parsed.cards if card.section == "deck" and lookup[card.name]["type_line"].startswith("Land")) == 38
    assert out["interaction_count"] >= 10
    artifact_count = sum(
        card.qty
        for card in parsed.cards
        if card.section == "deck" and "artifact" in lookup[card.name]["type_line"].lower()
    )
    generic_count = sum(card.qty for card in parsed.cards if card.section == "deck" and card.name.startswith("Generic Value"))
    assert artifact_count >= 16
    assert generic_count <= artifact_count
    assert isinstance(warnings, list)


def test_commander_plan_inference_prefers_artifacts_for_artifact_commander():
    commander = _make_card(
        "Captain of Relics",
        mana_cost="{2}{W}",
        cmc=3,
        type_line="Legendary Creature — Human Artificer",
        oracle_text="Whenever you cast an artifact spell, create a 1/1 colorless Thopter artifact creature token with flying.",
    )
    plan = RandomDeckService(random.Random(1))._infer_plan([commander], bracket=3)

    assert plan.primary_package == "artifacts"
    assert "artifact_mass" in plan.needs
    assert plan.land_count == 38
    assert plan.confidence > 0.34


def test_commander_plan_inference_falls_back_to_typal_when_subtype_signal_is_strong():
    commander = _make_card(
        "Aerie Marshal",
        mana_cost="{1}{W}{W}",
        cmc=3,
        type_line="Legendary Creature — Bird Wizard",
        oracle_text="Bird creatures you control get +1/+1 and have vigilance.",
    )
    plan = RandomDeckService(random.Random(1))._infer_plan([commander], bracket=2)

    assert plan.primary_package == "typal"
    assert plan.subtype_anchor == "Bird"


def test_commander_plan_inference_prefers_aristocrats_for_death_trigger_commander():
    commander = _make_card(
        "Grave Host",
        mana_cost="{1}{B}{B}",
        cmc=3,
        type_line="Legendary Creature — Human Cleric",
        oracle_text="Whenever another creature you control dies, each opponent loses 1 life and you gain 1 life.",
        color_identity=["B"],
    )
    plan = RandomDeckService(random.Random(13))._infer_plan([commander], bracket=3)

    assert plan.primary_package == "aristocrats"
    assert "fodder" in plan.needs
    assert "death_payoff" in plan.needs


def test_commander_plan_inference_prefers_blink_for_etb_blink_commander():
    commander = _make_card(
        "Waystep Rector",
        mana_cost="{2}{W}{U}",
        cmc=4,
        type_line="Legendary Creature — Human Wizard",
        oracle_text="Whenever a permanent you control leaves the battlefield, exile up to one target creature you control, then return it to the battlefield under its owner's control.",
        color_identity=["W", "U"],
    )
    plan = RandomDeckService(random.Random(14))._infer_plan([commander], bracket=3)

    assert plan.primary_package == "blink"
    assert "blink_piece" in plan.needs
    assert "etb_target" in plan.needs


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

    def fake_get_by_names(self, names):
        return {name: lookup[name] for name in names if name in lookup}

    monkeypatch.setattr(RandomDeckService, "_random_commander", fake_random_commander)
    monkeypatch.setattr(
        CardDataService,
        "search_candidates",
        _fake_search_factory(
            interaction_cards,
            ramp_cards,
            draw_cards,
            synergy_cards,
            partner_cards=[secondary],
        ),
    )
    monkeypatch.setattr(CardDataService, "get_cards_by_name", fake_get_by_names)

    out = RandomDeckService(random.Random(3)).generate(bracket=3)
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
    monkeypatch.setattr(
        CardDataService,
        "search_candidates",
        _fake_search_factory(interaction_cards, ramp_cards, draw_cards, synergy_cards),
    )
    monkeypatch.setattr(CardDataService, "get_cards_by_name", lambda self, names: {name: lookup[name] for name in names if name in lookup})

    out = RandomDeckService(random.Random(5)).generate(bracket=3)
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

    def fake_get_by_names(self, names):
        return {name: lookup[name] for name in names if name in lookup}

    monkeypatch.setattr(RandomDeckService, "_random_commander", fake_random_commander)
    monkeypatch.setattr(
        CardDataService,
        "search_candidates",
        _fake_search_factory(
            interaction_cards,
            ramp_cards,
            draw_cards,
            synergy_cards,
            background_cards=[background],
        ),
    )
    monkeypatch.setattr(CardDataService, "get_cards_by_name", fake_get_by_names)

    out = RandomDeckService(random.Random(11)).generate(bracket=3)
    parsed = parse_decklist(out["decklist_text"])
    card_map = {name: lookup[name] for name in [card.name for card in parsed.cards]}
    errors, _, _ = validate_deck(parsed.cards, parsed.commander, card_map, 3)

    assert not errors
    assert out["commanders"] == ["Hero of the Road", "Cloak of Echoes"]
    assert parsed.commanders == ["Hero of the Road", "Cloak of Echoes"]


def test_random_partner_commander_prefers_higher_synergy_candidate(monkeypatch):
    svc = RandomDeckService(random.Random(15))
    primary = _make_card(
        "Forge Captain",
        mana_cost="{1}{R}",
        cmc=2,
        type_line="Legendary Creature — Dwarf Artificer",
        oracle_text="Artifact spells you cast cost {1} less to cast.",
        color_identity=["R"],
    )
    strong = _make_card(
        "Steel Mate",
        mana_cost="{1}{W}",
        cmc=2,
        type_line="Legendary Creature — Human Artificer",
        oracle_text="Whenever you cast an artifact spell, draw a card.",
        color_identity=["W"],
    )
    weak = _make_card(
        "Loose Blade",
        mana_cost="{1}{G}",
        cmc=2,
        type_line="Legendary Creature — Elf Warrior",
        oracle_text="Trample.",
        color_identity=["G"],
    )

    monkeypatch.setattr(RandomDeckService, "_search_pair_candidates", lambda self, query, limit=120: [weak, strong])
    monkeypatch.setattr(RandomDeckService, "_pick_rank_band", lambda self, ranked, window=6: max(ranked, key=lambda row: row[0])[1])

    chosen = svc._random_partner_commander(primary)

    assert chosen["name"] == "Steel Mate"
    assert svc._candidate_team_score(primary, strong) > svc._candidate_team_score(primary, weak)


def test_random_background_prefers_higher_synergy_candidate(monkeypatch):
    svc = RandomDeckService(random.Random(16))
    primary = _make_card(
        "Skyline Duelist",
        mana_cost="{2}{W}",
        cmc=3,
        type_line="Legendary Creature — Human Knight",
        oracle_text="Whenever equipped creature attacks, draw a card.",
        color_identity=["W"],
    )
    strong = _make_card(
        "Armory Tales",
        mana_cost="{2}{W}",
        cmc=3,
        type_line="Legendary Enchantment — Background",
        oracle_text="Commander creatures you own have \"Whenever this creature becomes equipped, create a token.\"",
        color_identity=["W"],
    )
    weak = _make_card(
        "Quiet Study",
        mana_cost="{2}{U}",
        cmc=3,
        type_line="Legendary Enchantment — Background",
        oracle_text="Commander creatures you own have ward {1}.",
        color_identity=["U"],
    )

    monkeypatch.setattr(RandomDeckService, "_search_pair_candidates", lambda self, query, limit=120: [weak, strong])
    monkeypatch.setattr(RandomDeckService, "_pick_rank_band", lambda self, ranked, window=6: max(ranked, key=lambda row: row[0])[1])

    chosen = svc._random_background(primary)

    assert chosen["name"] == "Armory Tales"
    assert svc._candidate_team_score(primary, strong) > svc._candidate_team_score(primary, weak)


def test_search_union_dedupes_oracle_ids_and_tracks_query_labels(monkeypatch):
    svc = CardDataService()
    alpha = _make_card("Alpha Utility", oracle_id="same-oid", edhrec_rank=50)
    beta = _make_card("Beta Glue", oracle_id="beta-oid", edhrec_rank=500)

    def fake_search(self, query, color_identity, limit=10, order="name", direction="asc"):
        if query == "first":
            return [alpha, beta]
        if query == "second":
            return [{**alpha, "name": "Alpha Utility Showcase"}]
        return []

    monkeypatch.setattr(CardDataService, "search_candidates", fake_search)

    rows = svc.search_union(
        [
            QuerySpec(label="role:interaction", query="first", limit=20),
            QuerySpec(label="pkg:blink", query="second", limit=20),
        ],
        "W",
    )
    by_oracle = {row["oracle_id"]: row for row in rows}

    assert set(by_oracle) == {"same-oid", "beta-oid"}
    assert set(by_oracle["same-oid"]["matched_queries"]) == {"role:interaction", "pkg:blink"}
    assert by_oracle["same-oid"]["popularity_pct"] is not None


def test_package_completion_uses_bottleneck_axis_for_aristocrats():
    svc = RandomDeckService(random.Random(2))
    context = _make_context("aristocrats")
    selected = [
        _make_tagged("Fodder A", packages={"aristocrats", "tokens"}, provides={"fodder", "token_source"}),
        _make_tagged("Fodder B", packages={"aristocrats", "tokens"}, provides={"fodder", "token_source"}),
        _make_tagged("Fodder C", packages={"aristocrats", "tokens"}, provides={"fodder", "token_source"}),
        _make_tagged("Fodder D", packages={"aristocrats", "tokens"}, provides={"fodder", "token_source"}),
        _make_tagged("Fodder E", packages={"aristocrats", "tokens"}, provides={"fodder", "token_source"}),
        _make_tagged("Fodder F", packages={"aristocrats", "tokens"}, provides={"fodder", "token_source"}),
        _make_tagged("Payoff A", packages={"aristocrats"}, provides={"death_payoff"}),
        _make_tagged("Payoff B", packages={"aristocrats"}, provides={"death_payoff"}),
        _make_tagged("Payoff C", packages={"aristocrats"}, provides={"death_payoff"}),
        _make_tagged("Outlet A", packages={"aristocrats"}, provides={"sac_outlet"}),
    ]

    completion, weakest_axis, axis_state = svc._package_completion_state(selected, "aristocrats")

    assert weakest_axis == "sac_outlet"
    assert round(completion, 3) == round(1 / 3, 3)
    assert axis_state["fodder"]["current"] == 6
    assert axis_state["death_payoff"]["current"] == 3
    assert axis_state["sac_outlet"]["current"] == 1


def test_package_core_picker_prefers_missing_sac_outlet_for_aristocrats():
    svc = RandomDeckService(random.Random(3))
    context = _make_context("aristocrats")
    selected = [
        _make_tagged("Fodder A", packages={"aristocrats", "tokens"}, provides={"fodder"}),
        _make_tagged("Fodder B", packages={"aristocrats", "tokens"}, provides={"fodder"}),
        _make_tagged("Fodder C", packages={"aristocrats", "tokens"}, provides={"fodder"}),
        _make_tagged("Fodder D", packages={"aristocrats", "tokens"}, provides={"fodder"}),
        _make_tagged("Fodder E", packages={"aristocrats", "tokens"}, provides={"fodder"}),
        _make_tagged("Fodder F", packages={"aristocrats", "tokens"}, provides={"fodder"}),
        _make_tagged("Payoff A", packages={"aristocrats"}, provides={"death_payoff"}),
        _make_tagged("Payoff B", packages={"aristocrats"}, provides={"death_payoff"}),
        _make_tagged("Payoff C", packages={"aristocrats"}, provides={"death_payoff"}),
    ]
    selected_names = {row.entry.name for row in selected}
    candidates = [
        _make_tagged("Extra Payoff", packages={"aristocrats"}, provides={"death_payoff"}, base_score=6.0),
        _make_tagged("Needed Outlet", packages={"aristocrats"}, provides={"sac_outlet"}, base_score=1.0),
        _make_tagged("Glue Card", packages={"aristocrats"}, provides={"fodder"}, base_score=4.0),
    ]

    pick = svc._pick_package_core_candidate(candidates, selected_names, context, selected, "aristocrats")

    assert pick is not None
    assert pick.entry.name == "Needed Outlet"


def test_package_core_picker_prefers_etb_target_when_blink_is_missing_targets():
    commander = _make_card(
        "Blink Marshal",
        mana_cost="{2}{W}{U}",
        cmc=4,
        type_line="Legendary Creature — Human Wizard",
        oracle_text="Whenever one or more creatures you control leave the battlefield, draw a card.",
        color_identity=["W", "U"],
    )
    svc = RandomDeckService(random.Random(4))
    context = _make_context("blink", commander=commander)
    selected = [
        _make_tagged(
            "Blink A",
            packages={"blink"},
            provides={"blink_piece"},
            needs={"etb_target"},
            base_score=4.0,
            color_identity=["W", "U"],
            oracle_text="Exile target creature you control, then return it to the battlefield under its owner's control.",
        ),
        _make_tagged(
            "Blink B",
            packages={"blink"},
            provides={"blink_piece"},
            needs={"etb_target"},
            base_score=4.0,
            color_identity=["W", "U"],
            oracle_text="Exile another target creature you control, then return that card to the battlefield under its owner's control.",
        ),
        _make_tagged(
            "Blink C",
            packages={"blink"},
            provides={"blink_piece"},
            needs={"etb_target"},
            base_score=4.0,
            color_identity=["W", "U"],
            oracle_text="Exile target artifact or creature you control, then return it to the battlefield under its owner's control.",
        ),
        _make_tagged(
            "ETB A",
            packages={"blink"},
            provides={"etb_target"},
            base_score=2.0,
            color_identity=["W", "U"],
            type_line="Creature — Spirit",
            oracle_text="When this creature enters the battlefield, draw a card.",
        ),
        _make_tagged(
            "ETB B",
            packages={"blink"},
            provides={"etb_target"},
            base_score=2.0,
            color_identity=["W", "U"],
            type_line="Creature — Drake",
            oracle_text="When this creature enters the battlefield, return target permanent to its owner's hand.",
        ),
    ]
    selected_names = {row.entry.name for row in selected}
    candidates = [
        _make_tagged(
            "Extra Blink",
            packages={"blink"},
            provides={"blink_piece"},
            needs={"etb_target"},
            base_score=6.0,
            color_identity=["W", "U"],
            oracle_text="Exile target creature you control, then return it to the battlefield under its owner's control.",
        ),
        _make_tagged(
            "Needed ETB",
            packages={"blink"},
            provides={"etb_target"},
            base_score=1.2,
            color_identity=["W", "U"],
            type_line="Creature — Angel",
            oracle_text="When this creature enters the battlefield, create a token.",
        ),
    ]

    pick = svc._pick_package_core_candidate(candidates, selected_names, context, selected, "blink")

    assert pick is not None
    assert pick.entry.name == "Needed ETB"


def test_multi_role_bridge_card_gets_weighted_shell_bonus():
    commander = _make_card(
        "Blink Marshal",
        mana_cost="{2}{W}{U}",
        cmc=4,
        type_line="Legendary Creature — Human Wizard",
        oracle_text="Whenever one or more creatures you control leave the battlefield, draw a card.",
        color_identity=["W", "U"],
    )
    svc = RandomDeckService(random.Random(9))
    context = _make_context("blink", commander=commander)
    bridge_entry = CardEntry(qty=1, name="Bridge ETB", section="deck", tags=["#Removal"], confidence={}, explanations={})
    generic_entry = CardEntry(qty=1, name="Plain Removal", section="deck", tags=["#Removal"], confidence={}, explanations={})

    bridge_card = _make_card(
        "Bridge ETB",
        type_line="Creature — Spirit",
        color_identity=["W", "U"],
        oracle_text="When this creature enters the battlefield, exile target creature until this leaves the battlefield.",
    )
    generic_card = _make_card(
        "Plain Removal",
        type_line="Instant",
        color_identity=["W", "U"],
        oracle_text="Exile target creature.",
    )

    bridge_roles = svc._candidate_roles(bridge_card, bridge_entry)
    bridge_packages = svc._candidate_packages(bridge_card, bridge_entry, context)
    bridge_provides, bridge_needs = svc._candidate_support_axes(bridge_card, bridge_entry, context)
    bridge_coverage = svc._candidate_coverage(bridge_card, bridge_entry, context, bridge_roles, bridge_packages, bridge_provides)

    generic_roles = svc._candidate_roles(generic_card, generic_entry)
    generic_packages = svc._candidate_packages(generic_card, generic_entry, context)
    generic_provides, generic_needs = svc._candidate_support_axes(generic_card, generic_entry, context)
    generic_coverage = svc._candidate_coverage(generic_card, generic_entry, context, generic_roles, generic_packages, generic_provides)

    assert bridge_coverage["role:interaction"] == 1.0
    assert bridge_coverage["pkg:primary_enabler"] >= 0.8
    assert bridge_coverage["bridge"] >= 1.0
    assert generic_coverage["role:interaction"] == 1.0
    assert "pkg:primary_enabler" not in generic_coverage


def test_pick_score_prefers_plan_bridge_over_generic_popular_staple():
    commander = _make_card(
        "Blink Marshal",
        mana_cost="{2}{W}{U}",
        cmc=4,
        type_line="Legendary Creature — Human Wizard",
        oracle_text="Whenever one or more creatures you control leave the battlefield, draw a card.",
        color_identity=["W", "U"],
    )
    svc = RandomDeckService(random.Random(10))
    context = _make_context("blink", commander=commander)
    selected = [
        _make_tagged("Blink A", packages={"blink"}, provides={"blink_piece"}, coverage={"pkg:primary_enabler": 0.9}),
        _make_tagged("Blink B", packages={"blink"}, provides={"blink_piece"}, coverage={"pkg:primary_enabler": 0.9}),
        _make_tagged("Card Draw A", roles={"draw"}, coverage={"role:draw": 1.0}),
        _make_tagged("Ramp A", roles={"ramp"}, coverage={"role:ramp": 1.0}),
    ]
    coverage = svc._coverage_counts(selected)
    package_counts = svc._package_counts(selected)
    support_counts = svc._support_counts(selected)
    family_counts = svc._family_counts(selected)

    bridge_candidate = _make_tagged(
        "Bridge ETB Removal",
        tags=["#Removal"],
        packages={"blink"},
        provides={"etb_target"},
        roles={"interaction"},
        coverage={"role:interaction": 1.0, "pkg:primary_enabler": 0.8, "bridge": 1.0},
        base_score=1.8,
        color_identity=["W", "U"],
        type_line="Creature — Spirit",
        oracle_text="When this creature enters the battlefield, exile target creature until this leaves the battlefield.",
    )
    staple_candidate = _make_tagged(
        "Generic Premium Removal",
        tags=["#Removal"],
        roles={"interaction"},
        coverage={"role:interaction": 1.0},
        base_score=0.6,
        color_identity=["W", "U"],
        type_line="Instant",
        oracle_text="Exile target creature.",
    )
    staple_candidate.card["popularity_pct"] = 0.97

    bridge_score = svc._candidate_pick_score(
        bridge_candidate,
        context,
        selected,
        coverage,
        package_counts,
        support_counts,
        family_counts,
    )
    staple_score = svc._candidate_pick_score(
        staple_candidate,
        context,
        selected,
        coverage,
        package_counts,
        support_counts,
        family_counts,
    )

    assert bridge_score > staple_score


def test_select_final_deck_samples_only_from_top_group():
    svc = RandomDeckService(random.Random(11))
    decks = [
        GeneratedDeck(cards=[], selected=[], interaction_count=0, score=10.0, metrics={}, draft_seed=1),
        GeneratedDeck(cards=[], selected=[], interaction_count=0, score=9.6, metrics={}, draft_seed=2),
        GeneratedDeck(cards=[], selected=[], interaction_count=0, score=9.1, metrics={}, draft_seed=3),
        GeneratedDeck(cards=[], selected=[], interaction_count=0, score=7.0, metrics={}, draft_seed=4),
    ]

    picks = {svc._select_final_deck(decks).draft_seed for _ in range(25)}

    assert picks <= {1, 2}


def test_score_generated_deck_emits_deck_level_rerank_metrics():
    svc = RandomDeckService(random.Random(12))
    context = _make_context("aristocrats")
    selected = [
        _make_tagged(
            "Fodder A",
            packages={"aristocrats", "tokens"},
            provides={"fodder"},
            coverage={"pkg:primary_enabler": 0.9, "bridge": 1.0},
        ),
        _make_tagged(
            "Outlet A",
            packages={"aristocrats"},
            provides={"sac_outlet"},
            coverage={"pkg:primary_enabler": 0.9},
        ),
        _make_tagged(
            "Payoff A",
            packages={"aristocrats"},
            provides={"death_payoff"},
            coverage={"pkg:primary_payoff": 0.9, "finisher": 1.0},
        ),
        _make_tagged(
            "Removal Glue",
            tags=["#Removal"],
            packages={"aristocrats"},
            provides={"fodder"},
            roles={"interaction"},
            coverage={"role:interaction": 1.0, "pkg:primary_enabler": 0.8, "bridge": 1.0},
        ),
    ]

    score, metrics = svc._score_generated_deck(context, selected)

    assert isinstance(score, float)
    assert "shell_score" in metrics
    assert "cohesion_score" in metrics
    assert "package_completion_score" in metrics
    assert "diversity_score" in metrics
    assert "novelty_score" in metrics
    assert "unsupported_dependency_score" in metrics
    assert "tension_score" in metrics
    assert "staple_overload_penalty" in metrics
    assert "deck_score" in metrics


def test_shell_coverage_model_tracks_weighted_role_completion():
    selected = [
        _make_tagged("Ramp Rock", coverage={"role:ramp": 1.0}),
        _make_tagged("Treasure Maker", coverage={"role:ramp": 0.6, "bridge": 1.0}),
        _make_tagged("Draw Engine", coverage={"role:draw": 0.9}),
        _make_tagged("ETB Removal", coverage={"role:interaction": 1.0, "bridge": 1.0, "pkg:primary_enabler": 0.8}),
        _make_tagged("Sweeper", coverage={"role:wipe": 1.0}),
    ]
    svc = RandomDeckService(random.Random(17))
    coverage = svc._coverage_counts(selected)

    assert coverage["role:ramp"] == 1.6
    assert coverage["role:draw"] == 0.9
    assert coverage["role:interaction"] == 1.0
    assert coverage["role:wipe"] == 1.0
    assert coverage["bridge"] == 2.0


def test_generated_artifact_deck_keeps_generic_staples_under_budget(monkeypatch):
    commander, interaction_cards, ramp_cards, draw_cards, artifact_cards, _generic_cards, synergy_cards, lookup = _make_artifact_fixture()

    monkeypatch.setattr(RandomDeckService, "_random_commander", lambda self: commander)
    monkeypatch.setattr(
        CardDataService,
        "search_candidates",
        _fake_search_factory(interaction_cards, ramp_cards, draw_cards, synergy_cards, artifact_cards=artifact_cards),
    )
    monkeypatch.setattr(CardDataService, "get_cards_by_name", lambda self, names: {name: lookup[name] for name in names if name in lookup})

    svc = RandomDeckService(random.Random(18))
    out = svc.generate(bracket=3)
    metrics = out["generator_metrics"]["selected_metrics"]
    context = svc._build_context([commander], 3)

    assert metrics["generic_staples"] <= context.plan.staple_budget


def test_generated_artifact_deck_hits_core_shell_coverage(monkeypatch):
    commander, interaction_cards, ramp_cards, draw_cards, artifact_cards, _generic_cards, synergy_cards, lookup = _make_artifact_fixture()

    monkeypatch.setattr(RandomDeckService, "_random_commander", lambda self: commander)
    monkeypatch.setattr(
        CardDataService,
        "search_candidates",
        _fake_search_factory(interaction_cards, ramp_cards, draw_cards, synergy_cards, artifact_cards=artifact_cards),
    )
    monkeypatch.setattr(CardDataService, "get_cards_by_name", lambda self, names: {name: lookup[name] for name in names if name in lookup})

    svc = RandomDeckService(random.Random(19))
    out = svc.generate(bracket=3)
    metrics = out["generator_metrics"]["selected_metrics"]
    context = svc._build_context([commander], 3)
    coverage = metrics["coverage"]

    assert coverage["role:ramp"] / context.plan.coverage_targets["role:ramp"][0] >= 0.95
    assert coverage["role:draw"] / context.plan.coverage_targets["role:draw"][0] >= 0.90
    assert coverage["role:interaction"] / context.plan.coverage_targets["role:interaction"][0] >= 0.95


def test_dependency_penalty_flags_orphan_payoff():
    svc = RandomDeckService(random.Random(20))
    context = _make_context("aristocrats")
    orphan_payoff = _make_tagged(
        "Lonely Payoff",
        packages={"aristocrats"},
        provides={"death_payoff"},
        needs={"fodder", "sac_outlet"},
        coverage={"pkg:primary_payoff": 1.0, "finisher": 1.0},
    )
    supported = [
        _make_tagged("Fodder A", packages={"aristocrats"}, provides={"fodder"}, coverage={"pkg:primary_enabler": 0.9}),
        _make_tagged("Outlet A", packages={"aristocrats"}, provides={"sac_outlet"}, coverage={"pkg:primary_enabler": 0.9}),
        orphan_payoff,
    ]
    unsupported = [orphan_payoff]

    _score_supported, metrics_supported = svc._score_generated_deck(context, supported)
    _score_unsupported, metrics_unsupported = svc._score_generated_deck(context, unsupported)

    assert metrics_unsupported["unsupported_dependency_score"] > metrics_supported["unsupported_dependency_score"]


def test_variability_across_candidate_decks_stays_coherent(monkeypatch):
    commander, interaction_cards, ramp_cards, draw_cards, artifact_cards, _generic_cards, synergy_cards, lookup = _make_artifact_fixture()

    monkeypatch.setattr(
        CardDataService,
        "search_candidates",
        _fake_search_factory(interaction_cards, ramp_cards, draw_cards, synergy_cards, artifact_cards=artifact_cards),
    )
    monkeypatch.setattr(CardDataService, "get_cards_by_name", lambda self, names: {name: lookup[name] for name in names if name in lookup})

    svc = RandomDeckService(random.Random(21))
    context = svc._build_context([commander], 3)
    pool = svc._fetch_candidate_pool(context)
    candidates = svc._tag_candidate_pool(context, pool)
    drafted = svc._generate_candidate_decks(context, candidates, count=12)

    assert len(drafted) >= 3

    signatures = [
        {entry.name for entry in deck.cards if entry.section == "deck" and entry.name not in GENERIC_NONBASIC_LANDS and entry.name != "Plains"}
        for deck in drafted
    ]
    overlaps = []
    for idx, left in enumerate(signatures):
        for right in signatures[idx + 1 :]:
            overlaps.append(len(left & right) / max(1, len(left | right)))

    assert _median(overlaps) < 0.9
    assert _median([deck.metrics["cohesion_score"] for deck in drafted]) >= 0.45


def test_reranked_deck_scores_above_single_draft_baseline(monkeypatch):
    commander, interaction_cards, ramp_cards, draw_cards, artifact_cards, _generic_cards, synergy_cards, lookup = _make_artifact_fixture()

    monkeypatch.setattr(
        CardDataService,
        "search_candidates",
        _fake_search_factory(interaction_cards, ramp_cards, draw_cards, synergy_cards, artifact_cards=artifact_cards),
    )
    monkeypatch.setattr(CardDataService, "get_cards_by_name", lambda self, names: {name: lookup[name] for name in names if name in lookup})

    svc = RandomDeckService(random.Random(22))
    context = svc._build_context([commander], 3)
    pool = svc._fetch_candidate_pool(context)
    candidates = svc._tag_candidate_pool(context, pool)
    baseline = svc._draft_candidate_deck(context, candidates)
    reranked = svc._select_final_deck(svc._generate_candidate_decks(context, candidates, count=12))

    assert reranked is not None
    assert reranked.score >= baseline.score
