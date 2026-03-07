from app.schemas.deck import CardEntry
from app.services.replacements import (
    CardProfile,
    DeckContext,
    ManaCostProfile,
    ReplacementContract,
    ThemeParticipation,
    _build_candidate_query_plan,
    _build_contract,
    _build_deck_context,
    _evaluate_candidate,
    _preserves_themes,
    _profile_from_card,
    _role_is_covered,
    _selected_theme_obligations,
    _split_type_line,
    strict_replacement_shadow_report,
    strictly_better_replacements,
)


def _manual_ctx(*active_theme_keys: str, commander_ci: set[str] | None = None) -> DeckContext:
    return DeckContext(
        commander_names=("Commander",),
        commander_color_identity=set(commander_ci or set()),
        deck_names=set(),
        active_theme_keys=set(active_theme_keys),
        active_theme_strengths={key: 1.0 for key in active_theme_keys},
        type_profile={},
    )


def _manual_profile(
    name: str,
    *,
    main_types: tuple[str, ...],
    replacement_family: str,
    comparison_class: str | None,
    comparison_data: dict,
    comparable_roles: tuple[str, ...] = (),
    theme_participation: tuple[ThemeParticipation, ...] = (),
    strict_comparable: bool = True,
    unsupported_reasons: tuple[str, ...] = (),
) -> CardProfile:
    return CardProfile(
        schema_version=1,
        name=name,
        oracle_id=name.lower().replace(" ", "-"),
        main_types=main_types,
        subtypes=(),
        color_identity=set(),
        mana_cost=ManaCostProfile(
            mana_value=float(comparison_data.get("mana_value", 0) or 0),
            pip_counts={},
            distinct_colors_required=0,
            has_x=False,
            has_hybrid=False,
            has_phyrexian=False,
            has_alt_cost=False,
        ),
        normalized_roles=set(comparable_roles),
        replacement_family=replacement_family,
        comparison_class=comparison_class,
        comparison_data=comparison_data,
        theme_participation=theme_participation,
        comparable_utility_roles=comparable_roles,
        strict_comparable=strict_comparable,
        unsupported_reasons=unsupported_reasons,
        evidence={},
    )


def _manual_contract(
    selected: CardProfile,
    *,
    required_roles: set[str] | None = None,
    required_theme_obligations: tuple[ThemeParticipation, ...] = (),
    budget_cap_usd: float | None = None,
) -> ReplacementContract:
    return ReplacementContract(
        selected_profile=selected,
        exact_main_types=selected.main_types,
        replacement_family=selected.replacement_family,
        comparison_class=selected.comparison_class or "",
        selected_comparison_data=dict(selected.comparison_data),
        required_roles=set(required_roles or set(selected.comparable_utility_roles)),
        required_theme_obligations=required_theme_obligations,
        budget_cap_usd=budget_cap_usd,
        commander_color_identity=set(),
        exclude_names=set(),
    )


def test_strictly_better_excludes_existing_and_respects_budget(monkeypatch):
    cards = [
        CardEntry(qty=1, name="Commander", section="commander"),
        CardEntry(qty=1, name="Arcane Signet", section="deck", tags=["#Ramp"]),
    ]

    class FakeSvc:
        def get_cards_by_name(self, names):
            out = {}
            for n in names:
                if n == "Commander":
                    out[n] = {"name": n, "color_identity": ["W", "U"], "type_line": "Legendary Creature — Human Wizard", "oracle_text": "", "cmc": 4}
                elif n == "Arcane Signet":
                    out[n] = {
                        "name": n,
                        "cmc": 2,
                        "oracle_id": "arcane-signet",
                        "type_line": "Artifact",
                        "oracle_text": "{T}: Add one mana of any color.",
                        "produced_mana": [],
                        "prices": {"usd": "1.0"},
                        "color_identity": [],
                    }
            return out

        def search_union(self, queries, color_identity):
            return [
                {
                    "name": "Arcane Signet",
                    "cmc": 2,
                    "oracle_id": "arcane-signet",
                    "type_line": "Artifact",
                    "oracle_text": "{T}: Add one mana of any color.",
                    "prices": {"usd": "1.0"},
                    "color_identity": [],
                },
                {
                    "name": "Mox Amber",
                    "cmc": 0,
                    "oracle_id": "mox-amber",
                    "type_line": "Artifact",
                    "oracle_text": "{T}: Add one mana of any color among legendary creatures and planeswalkers you control.",
                    "prices": {"usd": "35.0"},
                    "color_identity": [],
                },
                {
                    "name": "Mind Stone",
                    "cmc": 2,
                    "oracle_id": "mind-stone",
                    "type_line": "Artifact",
                    "oracle_text": "{T}: Add {C}.",
                    "produced_mana": ["C"],
                    "prices": {"usd": "1.0"},
                    "color_identity": [],
                },
            ]

        def card_display(self, card):
            return {"scryfall_uri": "https://example.com", "cardmarket_url": "https://example.com/cm"}

    monkeypatch.setattr("app.services.replacements.CardDataService", FakeSvc)

    out = strictly_better_replacements(cards, "Arcane Signet", commander="Commander", budget_max_usd=5)
    assert out["options"] == []


def test_strictly_better_prefers_exact_main_type_and_mana_efficiency(monkeypatch):
    cards = [
        CardEntry(qty=1, name="Commander", section="commander"),
        CardEntry(qty=1, name="Hedron Archive", section="deck", tags=["#Ramp", "#Draw", "#Rock"]),
    ]

    class FakeSvc:
        def get_cards_by_name(self, names):
            out = {}
            for n in names:
                if n == "Commander":
                    out[n] = {"name": n, "color_identity": [], "type_line": "Legendary Creature — Construct", "oracle_text": "", "cmc": 4}
                elif n == "Hedron Archive":
                    out[n] = {
                        "name": n,
                        "cmc": 4,
                        "oracle_id": "hedron-archive",
                        "type_line": "Artifact",
                        "oracle_text": "{T}: Add {C}{C}.\n{2}, {T}, Sacrifice Hedron Archive: Draw two cards.",
                        "produced_mana": ["C"],
                    }
            return out

        def search_union(self, queries, color_identity):
            return [
                {
                    "name": "Sol Ring",
                    "cmc": 1,
                    "oracle_id": "sol-ring",
                    "type_line": "Artifact",
                    "oracle_text": "{T}: Add {C}{C}.",
                    "produced_mana": ["C"],
                    "prices": {"usd": "1.0"},
                    "color_identity": [],
                },
                {
                    "name": "Temple of the False God",
                    "cmc": 0,
                    "oracle_id": "temple-false-god",
                    "type_line": "Land",
                    "oracle_text": "{T}: Add {C}{C}. Activate only if you control five or more lands.",
                    "produced_mana": ["C"],
                    "prices": {"usd": "0.2"},
                    "color_identity": [],
                },
            ]

        def card_display(self, card):
            return {"scryfall_uri": "https://example.com", "cardmarket_url": "https://example.com/cm"}

    monkeypatch.setattr("app.services.replacements.CardDataService", FakeSvc)

    out = strictly_better_replacements(cards, "Hedron Archive", commander="Commander", budget_max_usd=5)
    names = [x["card"] for x in out["options"]]
    assert names == ["Sol Ring"]
    assert any("Lower mana value" in reason for reason in out["options"][0]["reasons"])


def test_strictly_better_fails_closed_when_candidate_loses_tempo_or_color_utility(monkeypatch):
    cards = [
        CardEntry(qty=1, name="Commander", section="commander"),
        CardEntry(qty=1, name="Heraldic Banner", section="deck", tags=["#Ramp", "#Rock", "#Payoff"]),
    ]

    class FakeSvc:
        def get_cards_by_name(self, names):
            out = {}
            for n in names:
                if n == "Commander":
                    out[n] = {"name": n, "color_identity": ["W"], "type_line": "Legendary Creature — Bird", "oracle_text": "", "cmc": 3}
                elif n == "Heraldic Banner":
                    out[n] = {
                        "name": n,
                        "cmc": 3,
                        "oracle_id": "heraldic-banner",
                        "type_line": "Artifact",
                        "oracle_text": "As Heraldic Banner enters, choose a color.\nCreatures you control of the chosen color get +1/+0.\n{T}: Add one mana of the chosen color.",
                        "prices": {"usd": "0.2"},
                    }
            return out

        def search_union(self, queries, color_identity):
            return [
                {
                    "name": "Sol Ring",
                    "cmc": 1,
                    "oracle_id": "sol-ring",
                    "type_line": "Artifact",
                    "oracle_text": "{T}: Add {C}{C}.",
                    "produced_mana": ["C"],
                    "prices": {"usd": "1.0"},
                    "color_identity": [],
                },
                {
                    "name": "Marble Diamond",
                    "cmc": 2,
                    "oracle_id": "marble-diamond",
                    "type_line": "Artifact",
                    "oracle_text": "Marble Diamond enters tapped.\n{T}: Add {W}.",
                    "produced_mana": ["W"],
                    "prices": {"usd": "0.3"},
                    "color_identity": [],
                },
            ]

        def card_display(self, card):
            return {"scryfall_uri": "https://example.com", "cardmarket_url": "https://example.com/cm"}

    monkeypatch.setattr("app.services.replacements.CardDataService", FakeSvc)

    out = strictly_better_replacements(cards, "Heraldic Banner", commander="Commander", budget_max_usd=5)
    assert out["options"] == []


def test_strictly_better_preserves_active_typal_theme_on_supported_class():
    cards = [
        CardEntry(qty=1, name="Marwyn, the Nurturer", section="commander"),
        CardEntry(qty=1, name="Elvish Mystic", section="deck"),
        CardEntry(qty=1, name="Elvish Visionary", section="deck"),
        CardEntry(qty=1, name="Imperious Perfect", section="deck"),
        CardEntry(qty=1, name="Elvish Warmaster", section="deck"),
        CardEntry(qty=1, name="Dwynen's Elite", section="deck"),
        CardEntry(qty=1, name="Llanowar Tribe", section="deck"),
    ]
    card_map = {
        "Marwyn, the Nurturer": {
            "name": "Marwyn, the Nurturer",
            "oracle_id": "marwyn",
            "type_line": "Legendary Creature — Elf Druid",
            "oracle_text": "Whenever another Elf enters the battlefield under your control, put a +1/+1 counter on Marwyn, the Nurturer.\n{T}: Add an amount of {G} equal to Marwyn's power.",
            "color_identity": ["G"],
            "cmc": 3,
        },
        "Elvish Mystic": {
            "name": "Elvish Mystic",
            "oracle_id": "elvish-mystic",
            "type_line": "Creature — Elf Druid",
            "oracle_text": "{T}: Add {G}.",
            "produced_mana": ["G"],
            "color_identity": ["G"],
            "cmc": 1,
        },
        "Elvish Visionary": {
            "name": "Elvish Visionary",
            "oracle_id": "elvish-visionary",
            "type_line": "Creature — Elf Shaman",
            "oracle_text": "When Elvish Visionary enters the battlefield, draw a card.",
            "color_identity": ["G"],
            "cmc": 2,
        },
        "Imperious Perfect": {
            "name": "Imperious Perfect",
            "oracle_id": "imperious-perfect",
            "type_line": "Creature — Elf Warrior",
            "oracle_text": "Other Elf creatures you control get +1/+1.\n{G}, {T}: Create a 1/1 green Elf Warrior creature token.",
            "color_identity": ["G"],
            "cmc": 3,
        },
        "Elvish Warmaster": {
            "name": "Elvish Warmaster",
            "oracle_id": "elvish-warmaster",
            "type_line": "Creature — Elf Warrior",
            "oracle_text": "Whenever one or more other Elves enter the battlefield under your control, create a 1/1 green Elf Warrior creature token.",
            "color_identity": ["G"],
            "cmc": 2,
        },
        "Dwynen's Elite": {
            "name": "Dwynen's Elite",
            "oracle_id": "dwynens-elite",
            "type_line": "Creature — Elf Warrior",
            "oracle_text": "When Dwynen's Elite enters the battlefield, if you control another Elf, create a 1/1 green Elf Warrior creature token.",
            "color_identity": ["G"],
            "cmc": 2,
        },
        "Llanowar Tribe": {
            "name": "Llanowar Tribe",
            "oracle_id": "llanowar-tribe",
            "type_line": "Creature — Elf Druid",
            "oracle_text": "{T}: Add {G}{G}{G}.",
            "produced_mana": ["G"],
            "color_identity": ["G"],
            "cmc": 3,
        },
    }

    deck_context = _build_deck_context(cards, card_map, ["Marwyn, the Nurturer"])
    selected = _profile_from_card(card_map["Elvish Mystic"], deck_context)
    contract = _build_contract(selected, deck_context)
    assert contract is not None

    candidate = _profile_from_card(
        {
            "name": "Birds of Paradise",
            "oracle_id": "birds-of-paradise",
            "type_line": "Creature — Bird Druid",
            "oracle_text": "Flying\n{T}: Add one mana of any color.",
            "color_identity": ["G"],
            "cmc": 1,
        },
        deck_context,
    )
    decision = _evaluate_candidate(candidate, contract)
    assert not decision.accepted
    assert any("Missing active theme obligation" in reason for reason in decision.reasons)


def test_card_profile_normalizes_shared_schema_fields():
    cards = [CardEntry(qty=1, name="Commander", section="commander")]
    card_map = {
        "Commander": {
            "name": "Commander",
            "oracle_id": "commander",
            "type_line": "Legendary Creature — Human Wizard",
            "oracle_text": "",
            "color_identity": ["U"],
            "cmc": 3,
        }
    }
    ctx = _build_deck_context(cards, card_map, ["Commander"])
    profile = _profile_from_card(
        {
            "name": "Reasoned Response",
            "oracle_id": "reasoned-response",
            "type_line": "Instant",
            "mana_cost": "{1}{U/P}{U}",
            "oracle_text": "Counter target spell.",
            "color_identity": ["U"],
            "cmc": 3,
        },
        ctx,
        entry=CardEntry(qty=1, name="Reasoned Response", section="deck", tags=["#Counter"]),
    )
    assert profile.schema_version == 1
    assert profile.main_types == ("instant",)
    assert profile.mana_cost.pip_counts["U"] == 2
    assert profile.mana_cost.has_phyrexian is True
    assert profile.replacement_family == "counterspell"
    assert profile.comparison_class == "counter:hard:any"
    assert profile.comparable_utility_roles == ("#Counter",)
    assert "oracle" in profile.evidence
    assert "type-line" in profile.evidence


def test_deck_context_builds_active_themes_and_strengths():
    cards = [
        CardEntry(qty=1, name="Commander", section="commander"),
        CardEntry(qty=1, name="Goblin Chieftain", section="deck"),
        CardEntry(qty=1, name="Goblin Instigator", section="deck"),
        CardEntry(qty=1, name="Goblin Warchief", section="deck"),
        CardEntry(qty=1, name="Goblin Matron", section="deck"),
        CardEntry(qty=1, name="Goblin Ringleader", section="deck"),
        CardEntry(qty=1, name="Goblin Trashmaster", section="deck"),
        CardEntry(qty=1, name="Herald's Horn", section="deck", tags=["#Artifacts"]),
        CardEntry(qty=1, name="Vanquisher's Banner", section="deck", tags=["#Artifacts"]),
        CardEntry(qty=1, name="Skullclamp", section="deck", tags=["#Artifacts"]),
        CardEntry(qty=1, name="Swiftfoot Boots", section="deck", tags=["#Artifacts"]),
        CardEntry(qty=1, name="Banner of Kinship", section="deck", tags=["#Artifacts"]),
        CardEntry(qty=1, name="Idol of Oblivion", section="deck", tags=["#Artifacts"]),
    ]
    card_map = {
        "Commander": {"name": "Commander", "oracle_id": "c", "type_line": "Legendary Creature — Goblin Shaman", "oracle_text": "", "color_identity": ["R"], "cmc": 3},
        "Goblin Chieftain": {"name": "Goblin Chieftain", "oracle_id": "1", "type_line": "Creature — Goblin Warrior", "oracle_text": "Other Goblin creatures you control get +1/+1 and have haste.", "color_identity": ["R"], "cmc": 3},
        "Goblin Instigator": {"name": "Goblin Instigator", "oracle_id": "2", "type_line": "Creature — Goblin Rogue", "oracle_text": "When Goblin Instigator enters the battlefield, create a 1/1 red Goblin creature token.", "color_identity": ["R"], "cmc": 2},
        "Goblin Warchief": {"name": "Goblin Warchief", "oracle_id": "3", "type_line": "Creature — Goblin Warrior", "oracle_text": "Goblin spells you cast cost {1} less to cast.", "color_identity": ["R"], "cmc": 3},
        "Goblin Matron": {"name": "Goblin Matron", "oracle_id": "4", "type_line": "Creature — Goblin", "oracle_text": "When Goblin Matron enters the battlefield, you may search your library for a Goblin card.", "color_identity": ["R"], "cmc": 3},
        "Goblin Ringleader": {"name": "Goblin Ringleader", "oracle_id": "5", "type_line": "Creature — Goblin", "oracle_text": "When Goblin Ringleader enters the battlefield, reveal the top four cards of your library.", "color_identity": ["R"], "cmc": 4},
        "Goblin Trashmaster": {"name": "Goblin Trashmaster", "oracle_id": "6", "type_line": "Creature — Goblin Warrior", "oracle_text": "Other Goblins you control get +1/+1.", "color_identity": ["R"], "cmc": 4},
        "Herald's Horn": {"name": "Herald's Horn", "oracle_id": "7", "type_line": "Artifact", "oracle_text": "", "color_identity": [], "cmc": 3},
        "Vanquisher's Banner": {"name": "Vanquisher's Banner", "oracle_id": "8", "type_line": "Artifact", "oracle_text": "", "color_identity": [], "cmc": 5},
        "Skullclamp": {"name": "Skullclamp", "oracle_id": "9", "type_line": "Artifact — Equipment", "oracle_text": "", "color_identity": [], "cmc": 1},
        "Swiftfoot Boots": {"name": "Swiftfoot Boots", "oracle_id": "10", "type_line": "Artifact — Equipment", "oracle_text": "", "color_identity": [], "cmc": 2},
        "Banner of Kinship": {"name": "Banner of Kinship", "oracle_id": "11", "type_line": "Artifact", "oracle_text": "", "color_identity": [], "cmc": 3},
        "Idol of Oblivion": {"name": "Idol of Oblivion", "oracle_id": "12", "type_line": "Artifact", "oracle_text": "", "color_identity": [], "cmc": 2},
    }
    ctx = _build_deck_context(cards, card_map, ["Commander"])
    assert "typal:goblin" in ctx.active_theme_keys
    assert "package:artifacts" in ctx.active_theme_keys
    assert ctx.active_theme_strengths["typal:goblin"] > 0.5
    assert ctx.theme_profile_version == "type-theme:v1"
    assert ctx.theme_profile_source == "compute_type_theme_profile"


def test_theme_participation_is_deck_aware_for_generic_tutor_domains():
    cards = [
        CardEntry(qty=1, name="Commander", section="commander"),
        CardEntry(qty=1, name="Skullclamp", section="deck"),
        CardEntry(qty=1, name="Swiftfoot Boots", section="deck"),
        CardEntry(qty=1, name="Sword of the Animist", section="deck"),
        CardEntry(qty=1, name="Bonesplitter", section="deck"),
        CardEntry(qty=1, name="Open the Armory", section="deck"),
    ]
    card_map = {
        "Commander": {"name": "Commander", "oracle_id": "c", "type_line": "Legendary Creature — Human Soldier", "oracle_text": "", "color_identity": ["W"], "cmc": 2},
        "Skullclamp": {"name": "Skullclamp", "oracle_id": "1", "type_line": "Artifact — Equipment", "oracle_text": "", "color_identity": [], "cmc": 1},
        "Swiftfoot Boots": {"name": "Swiftfoot Boots", "oracle_id": "2", "type_line": "Artifact — Equipment", "oracle_text": "", "color_identity": [], "cmc": 2},
        "Sword of the Animist": {"name": "Sword of the Animist", "oracle_id": "3", "type_line": "Artifact — Equipment", "oracle_text": "", "color_identity": [], "cmc": 2},
        "Bonesplitter": {"name": "Bonesplitter", "oracle_id": "5", "type_line": "Artifact — Equipment", "oracle_text": "", "color_identity": [], "cmc": 1},
        "Open the Armory": {
            "name": "Open the Armory",
            "oracle_id": "4",
            "type_line": "Sorcery",
            "oracle_text": "Search your library for an Aura or Equipment card, reveal it, put it into your hand, then shuffle.",
            "color_identity": ["W"],
            "cmc": 2,
        },
    }
    ctx = _build_deck_context(cards, card_map, ["Commander"])
    profile = _profile_from_card(card_map["Open the Armory"], ctx)
    themes = {(theme.theme_key, theme.mode) for theme in profile.theme_participation}
    assert ("package:equipment", "tutor") in themes


def test_selected_theme_obligations_only_include_active_themes():
    cards = [
        CardEntry(qty=1, name="Commander", section="commander"),
        CardEntry(qty=1, name="Goblin Chieftain", section="deck"),
        CardEntry(qty=1, name="Goblin Instigator", section="deck"),
        CardEntry(qty=1, name="Goblin Warchief", section="deck"),
        CardEntry(qty=1, name="Goblin Matron", section="deck"),
        CardEntry(qty=1, name="Goblin Ringleader", section="deck"),
        CardEntry(qty=1, name="Goblin Trashmaster", section="deck"),
    ]
    card_map = {
        "Commander": {"name": "Commander", "oracle_id": "c", "type_line": "Legendary Creature — Goblin Shaman", "oracle_text": "", "color_identity": ["R"], "cmc": 3},
        "Goblin Chieftain": {"name": "Goblin Chieftain", "oracle_id": "1", "type_line": "Creature — Goblin Warrior", "oracle_text": "Other Goblin creatures you control get +1/+1 and have haste.", "color_identity": ["R"], "cmc": 3},
        "Goblin Instigator": {"name": "Goblin Instigator", "oracle_id": "2", "type_line": "Creature — Goblin Rogue", "oracle_text": "When Goblin Instigator enters the battlefield, create a 1/1 red Goblin creature token.", "color_identity": ["R"], "cmc": 2},
        "Goblin Warchief": {"name": "Goblin Warchief", "oracle_id": "3", "type_line": "Creature — Goblin Warrior", "oracle_text": "Goblin spells you cast cost {1} less to cast.", "color_identity": ["R"], "cmc": 3},
        "Goblin Matron": {"name": "Goblin Matron", "oracle_id": "4", "type_line": "Creature — Goblin", "oracle_text": "When Goblin Matron enters the battlefield, you may search your library for a Goblin card.", "color_identity": ["R"], "cmc": 3},
        "Goblin Ringleader": {"name": "Goblin Ringleader", "oracle_id": "5", "type_line": "Creature — Goblin", "oracle_text": "When Goblin Ringleader enters the battlefield, reveal the top four cards of your library.", "color_identity": ["R"], "cmc": 4},
        "Goblin Trashmaster": {"name": "Goblin Trashmaster", "oracle_id": "6", "type_line": "Creature — Goblin Warrior", "oracle_text": "Other Goblins you control get +1/+1.", "color_identity": ["R"], "cmc": 4},
        "Adaptive Automaton": {
            "name": "Adaptive Automaton",
            "oracle_id": "7",
            "type_line": "Artifact Creature — Construct",
            "oracle_text": "As Adaptive Automaton enters the battlefield, choose a creature type. Adaptive Automaton is the chosen type in addition to its other types. Other creatures you control of the chosen type get +1/+1.",
            "color_identity": [],
            "cmc": 3,
        },
    }
    ctx = _build_deck_context(cards, card_map, ["Commander"])
    profile = _profile_from_card(card_map["Adaptive Automaton"], ctx)
    obligations = {(theme.theme_key, theme.mode) for theme in _selected_theme_obligations(profile, ctx)}
    assert ("typal:goblin", "payoff") in obligations
    assert ("package:artifacts", "member") not in obligations


def test_profile_resolves_initial_supported_comparison_classes():
    cards = [CardEntry(qty=1, name="Commander", section="commander")]
    card_map = {
        "Commander": {
            "name": "Commander",
            "oracle_id": "commander",
            "type_line": "Legendary Creature — Human Wizard",
            "oracle_text": "",
            "color_identity": ["W", "U", "B", "R", "G"],
            "cmc": 5,
        }
    }
    ctx = _build_deck_context(cards, card_map, ["Commander"])

    land_profile = _profile_from_card(
        {
            "name": "Mystic Gate",
            "oracle_id": "mystic-gate",
            "type_line": "Land",
            "oracle_text": "{T}: Add {C}.",
            "color_identity": [],
            "cmc": 0,
        },
        ctx,
    )
    dork_profile = _profile_from_card(
        {
            "name": "Elvish Mystic",
            "oracle_id": "elvish-mystic",
            "type_line": "Creature — Elf Druid",
            "oracle_text": "{T}: Add {G}.",
            "color_identity": ["G"],
            "cmc": 1,
        },
        ctx,
    )
    removal_profile = _profile_from_card(
        {
            "name": "Cleanse the Workshop",
            "oracle_id": "cleanse-the-workshop",
            "type_line": "Instant",
            "oracle_text": "Destroy target artifact or enchantment.",
            "color_identity": ["W"],
            "cmc": 2,
        },
        ctx,
    )
    tutor_profile = _profile_from_card(
        {
            "name": "Archive Petition",
            "oracle_id": "archive-petition",
            "type_line": "Sorcery",
            "oracle_text": "Search your library for an artifact or enchantment card, reveal it, put it into your hand, then shuffle.",
            "color_identity": ["W"],
            "cmc": 2,
        },
        ctx,
    )
    draw_profile = _profile_from_card(
        {
            "name": "Deep Analysis Lite",
            "oracle_id": "deep-analysis-lite",
            "type_line": "Sorcery",
            "oracle_text": "Draw two cards.",
            "color_identity": ["U"],
            "cmc": 3,
        },
        ctx,
    )

    assert land_profile.comparison_class == "mana:land:repeatable"
    assert dork_profile.comparison_class == "mana:creature:repeatable"
    assert removal_profile.comparison_class == "remove:spot:artifact-enchantment:destroy"
    assert tutor_profile.comparison_class == "tutor:artifact-or-enchantment:to-hand"
    assert draw_profile.comparison_class == "draw:sorcery:fixed"
    assert all(
        profile.strict_comparable
        for profile in (land_profile, dork_profile, removal_profile, tutor_profile, draw_profile)
    )


def test_replacement_contract_captures_strict_obligations():
    cards = [
        CardEntry(qty=1, name="Commander", section="commander"),
        CardEntry(qty=1, name="Skullclamp", section="deck"),
        CardEntry(qty=1, name="Swiftfoot Boots", section="deck"),
        CardEntry(qty=1, name="Sword of the Animist", section="deck"),
        CardEntry(qty=1, name="Bonesplitter", section="deck"),
        CardEntry(qty=1, name="Open the Armory", section="deck"),
    ]
    card_map = {
        "Commander": {"name": "Commander", "oracle_id": "c", "type_line": "Legendary Creature — Human Soldier", "oracle_text": "", "color_identity": ["W"], "cmc": 2},
        "Skullclamp": {"name": "Skullclamp", "oracle_id": "1", "type_line": "Artifact — Equipment", "oracle_text": "", "color_identity": [], "cmc": 1},
        "Swiftfoot Boots": {"name": "Swiftfoot Boots", "oracle_id": "2", "type_line": "Artifact — Equipment", "oracle_text": "", "color_identity": [], "cmc": 2},
        "Sword of the Animist": {"name": "Sword of the Animist", "oracle_id": "3", "type_line": "Artifact — Equipment", "oracle_text": "", "color_identity": [], "cmc": 2},
        "Bonesplitter": {"name": "Bonesplitter", "oracle_id": "5", "type_line": "Artifact — Equipment", "oracle_text": "", "color_identity": [], "cmc": 1},
        "Open the Armory": {
            "name": "Open the Armory",
            "oracle_id": "4",
            "type_line": "Sorcery",
            "oracle_text": "Search your library for an Aura or Equipment card, reveal it, put it into your hand, then shuffle.",
            "color_identity": ["W"],
            "cmc": 2,
        },
    }
    ctx = _build_deck_context(cards, card_map, ["Commander"])
    profile = _profile_from_card(card_map["Open the Armory"], ctx)
    contract = _build_contract(profile, ctx, budget_cap_usd=3)
    assert contract is not None
    assert contract.exact_main_types == ("sorcery",)
    assert contract.replacement_family == "tutor"
    assert contract.comparison_class == "tutor:artifact-or-enchantment:to-hand"
    assert contract.selected_comparison_data["mana_value"] == 2
    assert contract.required_theme_obligations == _selected_theme_obligations(profile, ctx)
    assert contract.budget_cap_usd == 3
    assert "Open the Armory" not in contract.exclude_names


def test_candidate_query_plan_is_separate_from_strict_contract_and_carries_theme_hints():
    cards = [
        CardEntry(qty=1, name="Commander", section="commander"),
        CardEntry(qty=1, name="Skullclamp", section="deck"),
        CardEntry(qty=1, name="Swiftfoot Boots", section="deck"),
        CardEntry(qty=1, name="Sword of the Animist", section="deck"),
        CardEntry(qty=1, name="Bonesplitter", section="deck"),
        CardEntry(qty=1, name="Open the Armory", section="deck"),
    ]
    card_map = {
        "Commander": {"name": "Commander", "oracle_id": "c", "type_line": "Legendary Creature — Human Soldier", "oracle_text": "", "color_identity": ["W"], "cmc": 2},
        "Skullclamp": {"name": "Skullclamp", "oracle_id": "1", "type_line": "Artifact — Equipment", "oracle_text": "", "color_identity": [], "cmc": 1},
        "Swiftfoot Boots": {"name": "Swiftfoot Boots", "oracle_id": "2", "type_line": "Artifact — Equipment", "oracle_text": "", "color_identity": [], "cmc": 2},
        "Sword of the Animist": {"name": "Sword of the Animist", "oracle_id": "3", "type_line": "Artifact — Equipment", "oracle_text": "", "color_identity": [], "cmc": 2},
        "Bonesplitter": {"name": "Bonesplitter", "oracle_id": "5", "type_line": "Artifact — Equipment", "oracle_text": "", "color_identity": [], "cmc": 1},
        "Open the Armory": {
            "name": "Open the Armory",
            "oracle_id": "4",
            "type_line": "Sorcery",
            "oracle_text": "Search your library for an Aura or Equipment card, reveal it, put it into your hand, then shuffle.",
            "color_identity": ["W"],
            "cmc": 2,
        },
    }
    ctx = _build_deck_context(cards, card_map, ["Commander"])
    profile = _profile_from_card(card_map["Open the Armory"], ctx)
    contract = _build_contract(profile, ctx, budget_cap_usd=5)
    assert contract is not None
    plan = _build_candidate_query_plan(contract)
    assert plan.exact_main_types == ("sorcery",)
    assert plan.replacement_family == "tutor"
    assert plan.comparison_class == "tutor:artifact-or-enchantment:to-hand"
    assert plan.budget_cap_usd == 5
    assert "Open the Armory" in plan.exclude_names
    assert "package:equipment" in plan.theme_hints
    assert any(spec.label == "family:tutor-artifact-enchantment" for spec in plan.scryfall_specs)
    assert any(spec.label == "theme:equipment" for spec in plan.scryfall_specs)


def test_counter_any_can_cover_counter_noncreature_when_not_worse():
    cards = [CardEntry(qty=1, name="Commander", section="commander")]
    card_map = {
        "Commander": {
            "name": "Commander",
            "oracle_id": "commander",
            "type_line": "Legendary Creature — Human Wizard",
            "oracle_text": "",
            "color_identity": ["U"],
            "cmc": 3,
        }
    }
    ctx = _build_deck_context(cards, card_map, ["Commander"])
    selected = _profile_from_card(
        {
            "name": "Negate",
            "oracle_id": "negate",
            "type_line": "Instant",
            "mana_cost": "{1}{U}",
            "oracle_text": "Counter target noncreature spell.",
            "color_identity": ["U"],
            "cmc": 2,
        },
        ctx,
        entry=CardEntry(qty=1, name="Negate", section="deck", tags=["#Counter", "#StackInteraction"]),
    )
    candidate = _profile_from_card(
        {
            "name": "Counterspell",
            "oracle_id": "counterspell",
            "type_line": "Instant",
            "mana_cost": "{U}{U}",
            "oracle_text": "Counter target spell.",
            "color_identity": ["U"],
            "cmc": 2,
        },
        ctx,
    )
    contract = _build_contract(selected, ctx)
    assert contract is not None
    decision = _evaluate_candidate(candidate, contract)
    assert decision.accepted
    assert any("wider spell target range" in reason.lower() for reason in decision.reasons)


def test_strictly_better_rejects_unknown_price_when_budget_cap_exists(monkeypatch):
    cards = [
        CardEntry(qty=1, name="Commander", section="commander"),
        CardEntry(qty=1, name="Divination", section="deck", tags=["#Draw"]),
    ]

    class FakeSvc:
        def get_cards_by_name(self, names):
            out = {}
            for n in names:
                if n == "Commander":
                    out[n] = {"name": n, "color_identity": ["U"], "type_line": "Legendary Creature — Human Wizard", "oracle_text": "", "cmc": 3}
                elif n == "Divination":
                    out[n] = {
                        "name": n,
                        "cmc": 3,
                        "oracle_id": "divination",
                        "type_line": "Sorcery",
                        "oracle_text": "Draw two cards.",
                        "prices": {"usd": "0.1"},
                        "color_identity": ["U"],
                    }
            return out

        def search_union(self, queries, color_identity):
            return [
                {
                    "name": "Quick Study",
                    "cmc": 3,
                    "oracle_id": "quick-study",
                    "type_line": "Sorcery",
                    "oracle_text": "Draw two cards.",
                    "prices": {"usd": None},
                    "color_identity": ["U"],
                }
            ]

        def card_display(self, card):
            return {"scryfall_uri": "https://example.com", "cardmarket_url": "https://example.com/cm"}

    monkeypatch.setattr("app.services.replacements.CardDataService", FakeSvc)
    out = strictly_better_replacements(cards, "Divination", commander="Commander", budget_max_usd=2)
    assert out["options"] == []


def test_explain_mode_returns_selected_profile_and_proof_summary(monkeypatch):
    cards = [
        CardEntry(qty=1, name="Commander", section="commander"),
        CardEntry(qty=1, name="Hedron Archive", section="deck", tags=["#Ramp", "#Draw", "#Rock"]),
    ]

    class FakeSvc:
        def get_cards_by_name(self, names):
            out = {}
            for n in names:
                if n == "Commander":
                    out[n] = {"name": n, "color_identity": [], "type_line": "Legendary Creature — Construct", "oracle_text": "", "cmc": 4}
                elif n == "Hedron Archive":
                    out[n] = {
                        "name": n,
                        "cmc": 4,
                        "oracle_id": "hedron-archive",
                        "type_line": "Artifact",
                        "oracle_text": "{T}: Add {C}{C}.\n{2}, {T}, Sacrifice Hedron Archive: Draw two cards.",
                        "produced_mana": ["C"],
                    }
            return out

        def search_union(self, queries, color_identity):
            return [
                {
                    "name": "Sol Ring",
                    "cmc": 1,
                    "oracle_id": "sol-ring",
                    "type_line": "Artifact",
                    "oracle_text": "{T}: Add {C}{C}.",
                    "produced_mana": ["C"],
                    "prices": {"usd": "1.0"},
                    "color_identity": [],
                    "popularity_pct": 0.99,
                },
            ]

        def card_display(self, card):
            return {"scryfall_uri": "https://example.com", "cardmarket_url": "https://example.com/cm"}

    monkeypatch.setattr("app.services.replacements.CardDataService", FakeSvc)
    out = strictly_better_replacements(cards, "Hedron Archive", commander="Commander", budget_max_usd=5, explain=True)
    assert out["selected_profile"]["comparison_class"] == "mana:artifact:repeatable"
    assert out["options"][0]["better_axes"]
    assert "Strictly better on" in out["options"][0]["proof_summary"]


def test_no_result_reasons_explain_empty_result(monkeypatch):
    cards = [
        CardEntry(qty=1, name="Commander", section="commander"),
        CardEntry(qty=1, name="Heraldic Banner", section="deck", tags=["#Ramp", "#Rock", "#Payoff"]),
    ]

    class FakeSvc:
        def get_cards_by_name(self, names):
            out = {}
            for n in names:
                if n == "Commander":
                    out[n] = {"name": n, "color_identity": ["W"], "type_line": "Legendary Creature — Bird", "oracle_text": "", "cmc": 3}
                elif n == "Heraldic Banner":
                    out[n] = {
                        "name": n,
                        "cmc": 3,
                        "oracle_id": "heraldic-banner",
                        "type_line": "Artifact",
                        "oracle_text": "As Heraldic Banner enters, choose a color.\nCreatures you control of the chosen color get +1/+0.\n{T}: Add one mana of the chosen color.",
                        "prices": {"usd": "0.2"},
                    }
            return out

        def search_union(self, queries, color_identity):
            return [
                {
                    "name": "Sol Ring",
                    "cmc": 1,
                    "oracle_id": "sol-ring",
                    "type_line": "Artifact",
                    "oracle_text": "{T}: Add {C}{C}.",
                    "produced_mana": ["C"],
                    "prices": {"usd": "1.0"},
                    "color_identity": [],
                },
            ]

        def card_display(self, card):
            return {"scryfall_uri": "https://example.com", "cardmarket_url": "https://example.com/cm"}

    monkeypatch.setattr("app.services.replacements.CardDataService", FakeSvc)
    out = strictly_better_replacements(cards, "Heraldic Banner", commander="Commander", budget_max_usd=5, explain=True)
    assert out["options"] == []
    assert out["no_result_reasons"]


def test_main_type_parsing_is_exact_and_order_insensitive():
    main_types, subtypes = _split_type_line("Enchantment Artifact — Shrine")
    assert main_types == ("artifact", "enchantment")
    assert subtypes == ("shrine",)


def test_selected_and_candidate_share_same_profile_normalization_path():
    ctx = _manual_ctx(commander_ci={"U"})
    card = {
        "name": "Cancel",
        "oracle_id": "cancel",
        "type_line": "Instant",
        "mana_cost": "{1}{U}{U}",
        "oracle_text": "Counter target spell.",
        "color_identity": ["U"],
        "cmc": 3,
    }
    selected_profile = _profile_from_card(card, ctx, entry=CardEntry(qty=1, name="Cancel", section="deck", tags=["#Counter"]))
    candidate_profile = _profile_from_card(card, ctx)
    assert selected_profile.main_types == candidate_profile.main_types
    assert selected_profile.replacement_family == candidate_profile.replacement_family
    assert selected_profile.comparison_class == candidate_profile.comparison_class


def test_modal_or_unsupported_cards_fail_closed():
    ctx = _manual_ctx(commander_ci={"U"})
    profile = _profile_from_card(
        {
            "name": "Cryptic Command",
            "oracle_id": "cryptic-command",
            "type_line": "Instant",
            "mana_cost": "{1}{U}{U}{U}",
            "oracle_text": "Choose two — Counter target spell; or return target permanent to its owner's hand; or tap all creatures your opponents control; or draw a card.",
            "color_identity": ["U"],
            "cmc": 4,
        },
        ctx,
    )
    assert not profile.strict_comparable
    assert profile.unsupported_reasons


def test_theme_preservation_for_equipment_tutor_requires_equipment_participation():
    ctx = _manual_ctx("package:equipment", commander_ci={"W"})
    selected = _profile_from_card(
        {
            "name": "Open the Armory",
            "oracle_id": "open-the-armory",
            "type_line": "Sorcery",
            "mana_cost": "{1}{W}",
            "oracle_text": "Search your library for an Aura or Equipment card, reveal it, put it into your hand, then shuffle.",
            "color_identity": ["W"],
            "cmc": 2,
        },
        ctx,
    )
    candidate = _profile_from_card(
        {
            "name": "Idyllic Tutor",
            "oracle_id": "idyllic-tutor",
            "type_line": "Sorcery",
            "mana_cost": "{2}{W}",
            "oracle_text": "Search your library for an enchantment card, reveal it, put it into your hand, then shuffle.",
            "color_identity": ["W"],
            "cmc": 3,
        },
        ctx,
    )
    contract = _manual_contract(selected, required_theme_obligations=_selected_theme_obligations(selected, ctx))
    ok, missing = _preserves_themes(candidate, contract)
    assert not ok
    assert "package:equipment:tutor" in missing


def test_theme_preservation_for_aura_member_rejects_generic_enchantment():
    ctx = _manual_ctx("package:aura", commander_ci={"W"})
    selected = _profile_from_card(
        {
            "name": "Ethereal Armor",
            "oracle_id": "ethereal-armor",
            "type_line": "Enchantment — Aura",
            "mana_cost": "{W}",
            "oracle_text": "Enchant creature",
            "color_identity": ["W"],
            "cmc": 1,
        },
        ctx,
    )
    candidate = _profile_from_card(
        {
            "name": "Glorious Anthem",
            "oracle_id": "glorious-anthem",
            "type_line": "Enchantment",
            "mana_cost": "{1}{W}{W}",
            "oracle_text": "Creatures you control get +1/+1.",
            "color_identity": ["W"],
            "cmc": 3,
        },
        ctx,
    )
    contract = _manual_contract(selected, required_theme_obligations=_selected_theme_obligations(selected, ctx))
    ok, missing = _preserves_themes(candidate, contract)
    assert not ok
    assert "package:aura:member" in missing


def test_theme_preservation_for_shrine_member_rejects_generic_enchantment():
    ctx = _manual_ctx("package:shrine", commander_ci={"W"})
    selected = _profile_from_card(
        {
            "name": "Honden of Cleansing Fire",
            "oracle_id": "honden",
            "type_line": "Legendary Enchantment — Shrine",
            "mana_cost": "{3}{W}",
            "oracle_text": "At the beginning of your upkeep, you gain 2 life for each Shrine you control.",
            "color_identity": ["W"],
            "cmc": 4,
        },
        ctx,
    )
    candidate = _profile_from_card(
        {
            "name": "Authority of the Consuls",
            "oracle_id": "authority",
            "type_line": "Enchantment",
            "mana_cost": "{W}",
            "oracle_text": "Creatures your opponents control enter tapped.",
            "color_identity": ["W"],
            "cmc": 1,
        },
        ctx,
    )
    contract = _manual_contract(selected, required_theme_obligations=_selected_theme_obligations(selected, ctx))
    ok, missing = _preserves_themes(candidate, contract)
    assert not ok
    assert "package:shrine:member" in missing


def test_theme_preservation_for_background_member_rejects_generic_enchantment():
    ctx = _manual_ctx("package:background", commander_ci={"W"})
    selected = _profile_from_card(
        {
            "name": "Noble Heritage",
            "oracle_id": "noble-heritage",
            "type_line": "Legendary Enchantment — Background",
            "mana_cost": "{2}{W}",
            "oracle_text": "Commander creatures you own have \"When this creature enters...\"",
            "color_identity": ["W"],
            "cmc": 3,
        },
        ctx,
    )
    candidate = _profile_from_card(
        {
            "name": "Smothering Tithe",
            "oracle_id": "smothering-tithe",
            "type_line": "Enchantment",
            "mana_cost": "{3}{W}",
            "oracle_text": "Whenever an opponent draws a card, that player may pay {2}. If the player doesn't, you create a Treasure token.",
            "color_identity": ["W"],
            "cmc": 4,
        },
        ctx,
    )
    contract = _manual_contract(selected, required_theme_obligations=_selected_theme_obligations(selected, ctx))
    ok, missing = _preserves_themes(candidate, contract)
    assert not ok
    assert "package:background:member" in missing


def test_off_theme_selected_card_does_not_create_theme_obligation():
    ctx = _manual_ctx("package:equipment", commander_ci={"W"})
    selected = _profile_from_card(
        {
            "name": "Swords to Plowshares",
            "oracle_id": "swords-to-plowshares",
            "type_line": "Instant",
            "mana_cost": "{W}",
            "oracle_text": "Exile target creature. Its controller gains life equal to its power.",
            "color_identity": ["W"],
            "cmc": 1,
        },
        ctx,
    )
    assert _selected_theme_obligations(selected, ctx) == ()


def test_exact_main_type_preservation_rejects_instant_to_creature():
    selected = _manual_profile(
        "Negate",
        main_types=("instant",),
        replacement_family="counterspell",
        comparison_class="counter:hard:noncreature",
        comparison_data={"mana_value": 2.0, "scope_rank": 1.0, "cast_color_burden": 1.0},
        comparable_roles=("#Counter",),
    )
    candidate = _manual_profile(
        "Mystic Snake",
        main_types=("creature",),
        replacement_family="counterspell",
        comparison_class="counter:hard:any",
        comparison_data={"mana_value": 4.0, "scope_rank": 2.0, "cast_color_burden": 2.0},
        comparable_roles=("#Counter",),
    )
    decision = _evaluate_candidate(candidate, _manual_contract(selected))
    assert not decision.accepted
    assert "Exact main card type is not preserved." in decision.reasons


def test_exact_main_type_preservation_rejects_artifact_creature_to_creature():
    selected = _manual_profile(
        "Support Automaton",
        main_types=("artifact", "creature"),
        replacement_family="mana-rock",
        comparison_class="mana:artifact:repeatable",
        comparison_data={
            "mana_value": 2.0,
            "output_amount": 1.0,
            "color_support": 0.0,
            "enters_tapped": False,
            "activation_burden": 0.0,
            "life_cost": 0.0,
            "sacrifice_cost": 0.0,
            "summoning_delay": 1.0,
            "cast_color_burden": 0.0,
        },
        comparable_roles=("#Ramp",),
    )
    candidate = _manual_profile(
        "Elvish Mystic",
        main_types=("creature",),
        replacement_family="mana-rock",
        comparison_class="mana:artifact:repeatable",
        comparison_data={
            "mana_value": 1.0,
            "output_amount": 1.0,
            "color_support": 1.0,
            "enters_tapped": False,
            "activation_burden": 0.0,
            "life_cost": 0.0,
            "sacrifice_cost": 0.0,
            "summoning_delay": 1.0,
            "cast_color_burden": 0.0,
        },
        comparable_roles=("#Ramp",),
    )
    decision = _evaluate_candidate(candidate, _manual_contract(selected))
    assert not decision.accepted
    assert "Exact main card type is not preserved." in decision.reasons


def test_land_never_replaced_by_artifact_ramp_in_strict_mode():
    selected = _manual_profile(
        "Skycloud Expanse",
        main_types=("land",),
        replacement_family="mana-land",
        comparison_class="mana:land:repeatable",
        comparison_data={
            "mana_value": 0.0,
            "output_amount": 1.0,
            "color_support": 2.0,
            "enters_tapped": False,
            "activation_burden": 1.0,
            "life_cost": 0.0,
            "sacrifice_cost": 0.0,
            "summoning_delay": 0.0,
            "cast_color_burden": 0.0,
        },
        comparable_roles=("#Ramp", "#Fixing"),
    )
    candidate = _manual_profile(
        "Arcane Signet",
        main_types=("artifact",),
        replacement_family="mana-rock",
        comparison_class="mana:artifact:repeatable",
        comparison_data={
            "mana_value": 2.0,
            "output_amount": 1.0,
            "color_support": 4.0,
            "enters_tapped": False,
            "activation_burden": 0.0,
            "life_cost": 0.0,
            "sacrifice_cost": 0.0,
            "summoning_delay": 0.0,
            "cast_color_burden": 0.0,
        },
        comparable_roles=("#Ramp", "#Fixing"),
    )
    decision = _evaluate_candidate(candidate, _manual_contract(selected))
    assert not decision.accepted
    assert "Exact main card type is not preserved." in decision.reasons


def test_exact_main_type_preservation_rejects_artifact_enchantment_to_plain_enchantment():
    selected = _manual_profile(
        "Relic Ward",
        main_types=("artifact", "enchantment"),
        replacement_family="unsupported",
        comparison_class="draw:sorcery:fixed",
        comparison_data={"mana_value": 3.0, "cards_drawn": 2.0, "cast_color_burden": 1.0},
        strict_comparable=True,
    )
    candidate = _manual_profile(
        "Phyrexian Arena",
        main_types=("enchantment",),
        replacement_family="unsupported",
        comparison_class="draw:sorcery:fixed",
        comparison_data={"mana_value": 3.0, "cards_drawn": 2.0, "cast_color_burden": 1.0},
        strict_comparable=True,
    )
    decision = _evaluate_candidate(candidate, _manual_contract(selected))
    assert not decision.accepted
    assert "Exact main card type is not preserved." in decision.reasons


def test_role_subsumption_is_directional():
    assert _role_is_covered("#Counter", {"#StackInteraction"})
    assert not _role_is_covered("#StackInteraction", {"#Counter"})
    assert _role_is_covered("#Removal", {"#SpotRemoval"})
    assert not _role_is_covered("#SpotRemoval", {"#Removal"})


def test_draw_comparator_requires_one_better_axis_without_worse_axes():
    selected = _manual_profile(
        "Divination",
        main_types=("sorcery",),
        replacement_family="draw",
        comparison_class="draw:sorcery:fixed",
        comparison_data={"mana_value": 3.0, "cards_drawn": 2.0, "cast_color_burden": 1.0},
        comparable_roles=("#Draw",),
    )
    candidate = _manual_profile(
        "Quick Study",
        main_types=("sorcery",),
        replacement_family="draw",
        comparison_class="draw:sorcery:fixed",
        comparison_data={"mana_value": 2.0, "cards_drawn": 2.0, "cast_color_burden": 1.0},
        comparable_roles=("#Draw",),
    )
    decision = _evaluate_candidate(candidate, _manual_contract(selected))
    assert decision.accepted
    assert "mana_value" in decision.better_axes


def test_tutor_comparator_rejects_harder_to_cast_candidate():
    selected = _manual_profile(
        "Open the Armory",
        main_types=("sorcery",),
        replacement_family="tutor",
        comparison_class="tutor:artifact-or-enchantment:to-hand",
        comparison_data={"mana_value": 2.0, "destination_rank": 1.0, "cast_color_burden": 1.0},
        comparable_roles=("#Tutor",),
    )
    candidate = _manual_profile(
        "Steelshaper's Boon",
        main_types=("sorcery",),
        replacement_family="tutor",
        comparison_class="tutor:artifact-or-enchantment:to-hand",
        comparison_data={"mana_value": 2.0, "destination_rank": 1.0, "cast_color_burden": 2.0},
        comparable_roles=("#Tutor",),
    )
    decision = _evaluate_candidate(candidate, _manual_contract(selected))
    assert not decision.accepted
    assert any("Harder to cast in color terms." in reason for reason in decision.reasons)


def test_removal_comparator_rejects_higher_mana_candidate():
    selected = _manual_profile(
        "Terminate",
        main_types=("instant",),
        replacement_family="spot-removal",
        comparison_class="remove:spot:creature:destroy",
        comparison_data={"mana_value": 2.0, "effect_rank": 1.0, "cast_color_burden": 2.0},
        comparable_roles=("#Removal", "#SpotRemoval"),
    )
    candidate = _manual_profile(
        "Murder",
        main_types=("instant",),
        replacement_family="spot-removal",
        comparison_class="remove:spot:creature:destroy",
        comparison_data={"mana_value": 3.0, "effect_rank": 1.0, "cast_color_burden": 1.0},
        comparable_roles=("#Removal", "#SpotRemoval"),
    )
    decision = _evaluate_candidate(candidate, _manual_contract(selected))
    assert not decision.accepted
    assert any("Higher mana value." in reason for reason in decision.reasons)


def test_invariant_returned_candidates_preserve_main_types_themes_and_budget(monkeypatch):
    cards = [
        CardEntry(qty=1, name="Commander", section="commander"),
        CardEntry(qty=1, name="Elvish Mystic", section="deck"),
        CardEntry(qty=1, name="Elvish Visionary", section="deck"),
        CardEntry(qty=1, name="Imperious Perfect", section="deck"),
        CardEntry(qty=1, name="Elvish Warmaster", section="deck"),
        CardEntry(qty=1, name="Dwynen's Elite", section="deck"),
        CardEntry(qty=1, name="Llanowar Tribe", section="deck"),
    ]

    class FakeSvc:
        def get_cards_by_name(self, names):
            data = {
                "Commander": {"name": "Commander", "oracle_id": "commander", "type_line": "Legendary Creature — Elf Druid", "oracle_text": "", "color_identity": ["G"], "cmc": 3},
                "Elvish Mystic": {"name": "Elvish Mystic", "oracle_id": "mystic", "type_line": "Creature — Elf Druid", "oracle_text": "{T}: Add {G}.", "produced_mana": ["G"], "color_identity": ["G"], "cmc": 1, "prices": {"usd": "0.5"}},
                "Elvish Visionary": {"name": "Elvish Visionary", "oracle_id": "visionary", "type_line": "Creature — Elf Shaman", "oracle_text": "When Elvish Visionary enters the battlefield, draw a card.", "color_identity": ["G"], "cmc": 2},
                "Imperious Perfect": {"name": "Imperious Perfect", "oracle_id": "perfect", "type_line": "Creature — Elf Warrior", "oracle_text": "Other Elf creatures you control get +1/+1.", "color_identity": ["G"], "cmc": 3},
                "Elvish Warmaster": {"name": "Elvish Warmaster", "oracle_id": "warmaster", "type_line": "Creature — Elf Warrior", "oracle_text": "Whenever one or more other Elves enter the battlefield under your control, create a 1/1 green Elf Warrior creature token.", "color_identity": ["G"], "cmc": 2},
                "Dwynen's Elite": {"name": "Dwynen's Elite", "oracle_id": "elite", "type_line": "Creature — Elf Warrior", "oracle_text": "When Dwynen's Elite enters the battlefield, if you control another Elf, create a 1/1 green Elf Warrior creature token.", "color_identity": ["G"], "cmc": 2},
                "Llanowar Tribe": {"name": "Llanowar Tribe", "oracle_id": "tribe", "type_line": "Creature — Elf Druid", "oracle_text": "{T}: Add {G}{G}{G}.", "produced_mana": ["G"], "color_identity": ["G"], "cmc": 3},
            }
            return {name: data[name] for name in names if name in data}

        def search_union(self, queries, color_identity):
            return [
                {"name": "Fyndhorn Elves", "oracle_id": "fyndhorn", "type_line": "Creature — Elf Druid", "oracle_text": "{T}: Add {G}.", "produced_mana": ["G"], "color_identity": ["G"], "cmc": 1, "prices": {"usd": "2.0"}},
                {"name": "Birds of Paradise", "oracle_id": "birds", "type_line": "Creature — Bird Druid", "oracle_text": "Flying\n{T}: Add one mana of any color.", "produced_mana": ["W", "U", "B", "R", "G"], "color_identity": ["G"], "cmc": 1, "prices": {"usd": "1.0"}},
            ]

        def card_display(self, card):
            return {"scryfall_uri": "https://example.com", "cardmarket_url": "https://example.com/cm"}

    monkeypatch.setattr("app.services.replacements.CardDataService", FakeSvc)
    out = strictly_better_replacements(cards, "Elvish Mystic", commander="Commander", budget_max_usd=5, explain=True)
    assert out["options"] == []
    assert out["no_result_reasons"]
    assert out["selected_profile"]["theme_obligations"]


def test_shadow_report_surfaces_old_pass_new_fail_cases(monkeypatch):
    cards = [
        CardEntry(qty=1, name="Commander", section="commander"),
        CardEntry(qty=1, name="Elvish Mystic", section="deck"),
        CardEntry(qty=1, name="Elvish Visionary", section="deck"),
        CardEntry(qty=1, name="Imperious Perfect", section="deck"),
        CardEntry(qty=1, name="Elvish Warmaster", section="deck"),
        CardEntry(qty=1, name="Dwynen's Elite", section="deck"),
        CardEntry(qty=1, name="Llanowar Tribe", section="deck"),
    ]

    class FakeSvc:
        def get_cards_by_name(self, names):
            data = {
                "Commander": {"name": "Commander", "oracle_id": "commander", "type_line": "Legendary Creature — Elf Druid", "oracle_text": "", "color_identity": ["G"], "cmc": 3},
                "Elvish Mystic": {"name": "Elvish Mystic", "oracle_id": "mystic", "type_line": "Creature — Elf Druid", "oracle_text": "{T}: Add {G}.", "produced_mana": ["G"], "color_identity": ["G"], "cmc": 1},
                "Elvish Visionary": {"name": "Elvish Visionary", "oracle_id": "visionary", "type_line": "Creature — Elf Shaman", "oracle_text": "When Elvish Visionary enters the battlefield, draw a card.", "color_identity": ["G"], "cmc": 2},
                "Imperious Perfect": {"name": "Imperious Perfect", "oracle_id": "perfect", "type_line": "Creature — Elf Warrior", "oracle_text": "Other Elf creatures you control get +1/+1.", "color_identity": ["G"], "cmc": 3},
                "Elvish Warmaster": {"name": "Elvish Warmaster", "oracle_id": "warmaster", "type_line": "Creature — Elf Warrior", "oracle_text": "Whenever one or more other Elves enter the battlefield under your control, create a 1/1 green Elf Warrior creature token.", "color_identity": ["G"], "cmc": 2},
                "Dwynen's Elite": {"name": "Dwynen's Elite", "oracle_id": "elite", "type_line": "Creature — Elf Warrior", "oracle_text": "When Dwynen's Elite enters the battlefield, if you control another Elf, create a 1/1 green Elf Warrior creature token.", "color_identity": ["G"], "cmc": 2},
                "Llanowar Tribe": {"name": "Llanowar Tribe", "oracle_id": "tribe", "type_line": "Creature — Elf Druid", "oracle_text": "{T}: Add {G}{G}{G}.", "produced_mana": ["G"], "color_identity": ["G"], "cmc": 3},
            }
            return {name: data[name] for name in names if name in data}

        def search_union(self, queries, color_identity):
            return [
                {"name": "Birds of Paradise", "oracle_id": "birds", "type_line": "Creature — Bird Druid", "oracle_text": "Flying\n{T}: Add one mana of any color.", "produced_mana": ["W", "U", "B", "R", "G"], "color_identity": ["G"], "cmc": 1, "prices": {"usd": "1.0"}},
            ]

        def card_display(self, card):
            return {"scryfall_uri": "https://example.com", "cardmarket_url": "https://example.com/cm"}

    monkeypatch.setattr("app.services.replacements.CardDataService", FakeSvc)
    report = strict_replacement_shadow_report(cards, "Elvish Mystic", commander="Commander", budget_max_usd=5)
    assert "Birds of Paradise" in report["old_pass_new_fail"]
    assert report["shadow_mode"] == "relaxed-family-proof-v1"
