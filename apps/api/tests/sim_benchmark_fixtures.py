from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SimBenchmarkFixture:
    slug: str
    display_name: str
    cards: list[dict]
    commanders: tuple[str, ...]
    expected_primary_plan: str
    parity_supported: bool = False
    unsupported_risk_expected: bool = False


def _card(
    name: str,
    *,
    qty: int = 1,
    section: str = "deck",
    tags: list[str] | None = None,
    mana_value: int = 2,
    type_line: str = "",
    oracle_text: str = "",
    keywords: list[str] | None = None,
    is_creature: bool = False,
    is_permanent: bool = False,
    power: float = 0.0,
    toughness: float = 0.0,
    has_haste: bool = False,
    evasion_score: float = 0.0,
    combat_buff: float = 0.0,
    commander_buff: float = 0.0,
    token_attack_power: float = 0.0,
    token_bodies: float = 0.0,
    extra_combat_factor: float = 1.0,
    infect: bool = False,
    toxic: float = 0.0,
    proliferate: bool = False,
    burn_value: float = 0.0,
    repeatable_burn: float = 0.0,
    mill_value: float = 0.0,
    repeatable_mill: float = 0.0,
    alt_win_kind: str | None = None,
    produced_mana: list[str] | None = None,
) -> dict:
    return {
        "name": name,
        "qty": qty,
        "section": section,
        "tags": list(tags or []),
        "mana_value": mana_value,
        "type_line": type_line,
        "oracle_text": oracle_text,
        "keywords": list(keywords or []),
        "is_creature": is_creature,
        "is_permanent": is_permanent,
        "power": power,
        "toughness": toughness,
        "has_haste": has_haste,
        "evasion_score": evasion_score,
        "combat_buff": combat_buff,
        "commander_buff": commander_buff,
        "token_attack_power": token_attack_power,
        "token_bodies": token_bodies,
        "extra_combat_factor": extra_combat_factor,
        "infect": infect,
        "toxic": toxic,
        "proliferate": proliferate,
        "burn_value": burn_value,
        "repeatable_burn": repeatable_burn,
        "mill_value": mill_value,
        "repeatable_mill": repeatable_mill,
        "alt_win_kind": alt_win_kind,
        "produced_mana": list(produced_mana or []),
    }


def _lands(count: int, *, fixing_every: int = 0, tapped_every: int = 0) -> list[dict]:
    lands: list[dict] = []
    for idx in range(count):
        tags = ["#Land"]
        if fixing_every and idx % fixing_every == 0:
            tags.append("#Fixing")
        oracle = "Enters tapped." if tapped_every and idx % tapped_every == 0 else ""
        lands.append(
            _card(
                f"Land {idx + 1}",
                tags=tags,
                mana_value=0,
                type_line="Land",
                oracle_text=oracle,
                is_permanent=True,
                produced_mana=["C"],
            )
        )
    return lands


def _copies(prefix: str, count: int, **kwargs) -> list[dict]:
    return [_card(f"{prefix} {idx + 1}", **kwargs) for idx in range(count)]


def _single_commander_fixture(
    slug: str,
    display_name: str,
    commander_card: dict,
    deck_cards: list[dict],
    *,
    expected_primary_plan: str,
    parity_supported: bool = False,
    unsupported_risk_expected: bool = False,
) -> SimBenchmarkFixture:
    cards = [commander_card] + deck_cards
    assert sum(int(card.get("qty", 1)) for card in cards) == 100, slug
    return SimBenchmarkFixture(
        slug=slug,
        display_name=display_name,
        cards=cards,
        commanders=(str(commander_card["name"]),),
        expected_primary_plan=expected_primary_plan,
        parity_supported=parity_supported,
        unsupported_risk_expected=unsupported_risk_expected,
    )


def _dual_commander_fixture(
    slug: str,
    display_name: str,
    commanders: list[dict],
    deck_cards: list[dict],
    *,
    expected_primary_plan: str,
    parity_supported: bool = False,
) -> SimBenchmarkFixture:
    cards = list(commanders) + deck_cards
    assert sum(int(card.get("qty", 1)) for card in cards) == 100, slug
    return SimBenchmarkFixture(
        slug=slug,
        display_name=display_name,
        cards=cards,
        commanders=tuple(str(card["name"]) for card in commanders),
        expected_primary_plan=expected_primary_plan,
        parity_supported=parity_supported,
    )


def build_sim_benchmark_fixtures() -> dict[str, SimBenchmarkFixture]:
    fixtures: dict[str, SimBenchmarkFixture] = {}

    fixtures["combat_go_wide"] = _single_commander_fixture(
        "combat_go_wide",
        "Combat Go-Wide",
        _card(
            "Marshal of Banners",
            section="commander",
            tags=["#CommanderSynergy", "#Engine"],
            mana_value=4,
            type_line="Legendary Creature - Soldier",
            oracle_text="Whenever one or more creatures attack, create a 1/1 token.",
            is_creature=True,
            is_permanent=True,
            power=3,
            token_bodies=1,
            token_attack_power=1,
        ),
        _lands(38, fixing_every=5)
        + _copies("Mana Rock", 10, tags=["#Ramp"], mana_value=2, type_line="Artifact", oracle_text="{T}: Add {C}.", is_permanent=True, produced_mana=["C"])
        + _copies("Cantrip", 8, tags=["#Draw"], mana_value=2, type_line="Sorcery", oracle_text="Draw a card.")
        + _copies("Removal", 8, tags=["#Removal"], mana_value=2, type_line="Instant", oracle_text="Destroy target creature.")
        + _copies("Token Maker", 12, tags=["#Setup"], mana_value=3, type_line="Sorcery", oracle_text="Create two 1/1 white Soldier creature tokens.", token_bodies=2, token_attack_power=1)
        + _copies("Anthem", 10, tags=["#Payoff", "#Wincon"], mana_value=4, type_line="Enchantment", oracle_text="Creatures you control get +1/+0.", is_permanent=True, combat_buff=1.0)
        + _copies("Body", 13, tags=["#Setup"], mana_value=3, type_line="Creature - Soldier", oracle_text="", is_creature=True, is_permanent=True, power=2, toughness=2),
        expected_primary_plan="combat",
        parity_supported=True,
    )

    fixtures["voltron"] = _single_commander_fixture(
        "voltron",
        "Voltron Commander Damage",
        _card(
            "Skyblade Duelist",
            section="commander",
            tags=["#CommanderSynergy", "#Payoff", "#Wincon"],
            mana_value=3,
            type_line="Legendary Creature - Human Knight",
            oracle_text="Flying, haste",
            is_creature=True,
            is_permanent=True,
            power=4,
            has_haste=True,
            evasion_score=0.6,
        ),
        _lands(38, fixing_every=4)
        + _copies("Stone", 10, tags=["#Ramp"], mana_value=2, type_line="Artifact", oracle_text="{T}: Add {C}.", is_permanent=True, produced_mana=["C"])
        + _copies("Refuel", 8, tags=["#Draw"], mana_value=2, type_line="Sorcery", oracle_text="Draw a card.")
        + _copies("Shield", 8, tags=["#Protection"], mana_value=1, type_line="Instant", oracle_text="Target creature gains hexproof.")
        + _copies("Sword", 12, tags=["#Setup", "#Payoff"], mana_value=2, type_line="Artifact - Equipment", oracle_text="Equipped creature gets +2/+0.", is_permanent=True, commander_buff=1.5)
        + _copies("Aura", 10, tags=["#Setup"], mana_value=2, type_line="Enchantment - Aura", oracle_text="Enchant creature. Enchanted creature gets +1/+1 and flying.", is_permanent=True, commander_buff=1.0)
        + _copies("Duelist Support", 13, tags=["#Draw", "#Protection"], mana_value=2, type_line="Instant", oracle_text="Draw a card."),
        expected_primary_plan="combat",
        parity_supported=True,
    )

    fixtures["toxic_proliferate"] = _single_commander_fixture(
        "toxic_proliferate",
        "Toxic Proliferate",
        _card(
            "Viral Harrier",
            section="commander",
            tags=["#CommanderSynergy", "#Wincon"],
            mana_value=4,
            type_line="Legendary Creature - Horror",
            oracle_text="Toxic 2",
            is_creature=True,
            is_permanent=True,
            power=3,
            toxic=2.0,
            evasion_score=0.35,
        ),
        _lands(38, fixing_every=4)
        + _copies("Ramp Node", 10, tags=["#Ramp"], mana_value=2, type_line="Artifact", oracle_text="{T}: Add {C}.", is_permanent=True, produced_mana=["C"])
        + _copies("Draw Growth", 8, tags=["#Draw"], mana_value=2, type_line="Sorcery", oracle_text="Draw a card.")
        + _copies("Interaction", 8, tags=["#Removal"], mana_value=2, type_line="Instant", oracle_text="Destroy target creature.")
        + _copies("Toxic Body", 12, tags=["#Wincon"], mana_value=2, type_line="Creature - Phyrexian", oracle_text="Toxic 1", is_creature=True, is_permanent=True, power=2, toxic=1.0, evasion_score=0.2)
        + _copies("Proliferator", 10, tags=["#Engine"], mana_value=3, type_line="Sorcery", oracle_text="Proliferate.", proliferate=True)
        + _copies("Evasive Setup", 13, tags=["#Setup", "#Protection"], mana_value=2, type_line="Instant", oracle_text="Target creature can't be blocked this turn."),
        expected_primary_plan="poison",
    )

    fixtures["aristocrats_drain"] = _single_commander_fixture(
        "aristocrats_drain",
        "Aristocrats Drain",
        _card(
            "Carrion Magistrate",
            section="commander",
            tags=["#CommanderSynergy", "#Engine"],
            mana_value=4,
            type_line="Legendary Creature - Warlock",
            oracle_text="Whenever a creature dies, each opponent loses 1 life and you gain 1 life.",
            is_creature=True,
            is_permanent=True,
            power=3,
            repeatable_burn=1.0,
        ),
        _lands(38, fixing_every=4)
        + _copies("Ramp Relic", 10, tags=["#Ramp"], mana_value=2, type_line="Artifact", oracle_text="{T}: Add {C}.", is_permanent=True, produced_mana=["C"])
        + _copies("Blood Ledger", 8, tags=["#Draw"], mana_value=2, type_line="Sorcery", oracle_text="Draw a card.")
        + _copies("Kill Spell", 8, tags=["#Removal"], mana_value=2, type_line="Instant", oracle_text="Destroy target creature.")
        + _copies("Fodder Maker", 12, tags=["#Setup"], mana_value=3, type_line="Sorcery", oracle_text="Create two 1/1 tokens.", token_bodies=2, token_attack_power=1)
        + _copies("Outlet", 8, tags=["#Engine"], mana_value=1, type_line="Creature - Cleric", oracle_text="Sacrifice another creature: Scry 1.", is_creature=True, is_permanent=True, power=1)
        + _copies("Death Payoff", 8, tags=["#Payoff", "#Wincon"], mana_value=3, type_line="Creature - Vampire", oracle_text="Whenever a creature dies, each opponent loses 1 life and you gain 1 life.", is_creature=True, is_permanent=True, repeatable_burn=1.0, power=2)
        + _copies("Recur", 7, tags=["#Recursion"], mana_value=2, type_line="Sorcery", oracle_text="Return target creature card from your graveyard to your hand."),
        expected_primary_plan="drain",
    )

    fixtures["spellslinger_combo"] = _single_commander_fixture(
        "spellslinger_combo",
        "Spellslinger Combo",
        _card(
            "Storm Savant",
            section="commander",
            tags=["#CommanderSynergy", "#Engine"],
            mana_value=3,
            type_line="Legendary Creature - Wizard",
            oracle_text="Whenever you cast an instant or sorcery spell, draw a card.",
            is_creature=True,
            is_permanent=True,
            power=2,
        ),
        _lands(38, fixing_every=4)
        + _copies("Cheap Rock", 8, tags=["#Ramp"], mana_value=2, type_line="Artifact", oracle_text="{T}: Add {C}.", is_permanent=True, produced_mana=["C"])
        + _copies("Ritual", 6, tags=["#Ramp", "#FastMana"], mana_value=1, type_line="Instant", oracle_text="Add {R}{R}{R}.")
        + _copies("Cantrip Bolt", 10, tags=["#Draw", "#Engine"], mana_value=1, type_line="Instant", oracle_text="Draw a card.")
        + _copies("Counter", 8, tags=["#Counter", "#Protection"], mana_value=2, type_line="Instant", oracle_text="Counter target spell.")
        + _copies("Tutor", 8, tags=["#Tutor"], mana_value=2, type_line="Sorcery", oracle_text="Search your library for an artifact or enchantment card, reveal it, put it into your hand.")
        + _copies("Engine Piece", 10, tags=["#Combo", "#Engine"], mana_value=3, type_line="Artifact", oracle_text="{T}: Add {C}. Draw a card.", is_permanent=True, produced_mana=["C"])
        + _copies("Burn Payoff", 11, tags=["#Combo", "#Payoff", "#Wincon"], mana_value=4, type_line="Enchantment", oracle_text="Whenever you cast a spell, each opponent loses 1 life.", is_permanent=True, repeatable_burn=1.0),
        expected_primary_plan="combo",
        parity_supported=True,
    )

    fixtures["artifact_combo"] = _single_commander_fixture(
        "artifact_combo",
        "Artifact Combo",
        _card(
            "Foundry Overseer",
            section="commander",
            tags=["#CommanderSynergy", "#Engine"],
            mana_value=4,
            type_line="Legendary Artifact Creature - Artificer",
            oracle_text="{T}: Add {C}.",
            is_creature=True,
            is_permanent=True,
            power=3,
            produced_mana=["C"],
        ),
        _lands(38, fixing_every=5)
        + _copies("Mana Artifact", 14, tags=["#Ramp", "#Rock"], mana_value=2, type_line="Artifact", oracle_text="{T}: Add {C}.", is_permanent=True, produced_mana=["C"])
        + _copies("Tinker Draw", 8, tags=["#Draw"], mana_value=2, type_line="Sorcery", oracle_text="Draw a card.")
        + _copies("Shield Counter", 6, tags=["#Counter", "#Protection"], mana_value=2, type_line="Instant", oracle_text="Counter target spell.")
        + _copies("Tutor Assembly", 8, tags=["#Tutor"], mana_value=2, type_line="Sorcery", oracle_text="Search your library for an artifact or enchantment card, reveal it, put it into your hand.")
        + _copies("Combo Engine", 12, tags=["#Combo", "#Engine"], mana_value=3, type_line="Artifact", oracle_text="{T}: Add {C}{C}.", is_permanent=True, produced_mana=["C"])
        + _copies("Mana Sink", 13, tags=["#Payoff", "#Wincon"], mana_value=4, type_line="Artifact", oracle_text="{T}: Add {C}. Each opponent loses 1 life.", is_permanent=True, repeatable_burn=1.0, produced_mana=["C"]),
        expected_primary_plan="combo",
        parity_supported=True,
    )

    fixtures["graveyard_combo"] = _single_commander_fixture(
        "graveyard_combo",
        "Graveyard Combo",
        _card(
            "Crypt Archivist",
            section="commander",
            tags=["#CommanderSynergy", "#Engine", "#Recursion"],
            mana_value=4,
            type_line="Legendary Creature - Warlock",
            oracle_text="Whenever a creature enters the battlefield from your graveyard, draw a card.",
            is_creature=True,
            is_permanent=True,
            power=3,
        ),
        _lands(38, fixing_every=5)
        + _copies("Stone", 10, tags=["#Ramp"], mana_value=2, type_line="Artifact", oracle_text="{T}: Add {C}.", is_permanent=True, produced_mana=["C"])
        + _copies("Self Mill", 12, tags=["#Setup"], mana_value=2, type_line="Sorcery", oracle_text="Each player mills three cards.", mill_value=3.0)
        + _copies("Reanimate", 10, tags=["#Recursion", "#Engine"], mana_value=3, type_line="Sorcery", oracle_text="Return target creature card from a graveyard to the battlefield.")
        + _copies("Tutor", 6, tags=["#Tutor"], mana_value=2, type_line="Sorcery", oracle_text="Search your library for an artifact or enchantment card, reveal it, put it into your hand.")
        + _copies("Combo Body", 10, tags=["#Combo", "#Wincon"], mana_value=4, type_line="Creature - Horror", oracle_text="", is_creature=True, is_permanent=True, power=4)
        + _copies("Draw Step", 13, tags=["#Draw"], mana_value=2, type_line="Sorcery", oracle_text="Draw a card."),
        expected_primary_plan="combo",
    )

    fixtures["lands_engine"] = _single_commander_fixture(
        "lands_engine",
        "Lands Engine",
        _card(
            "Frontier Surveyor",
            section="commander",
            tags=["#CommanderSynergy", "#Engine"],
            mana_value=4,
            type_line="Legendary Creature - Scout",
            oracle_text="Whenever a land enters the battlefield under your control, create a 1/1 token.",
            is_creature=True,
            is_permanent=True,
            power=3,
            token_bodies=1,
            token_attack_power=1,
        ),
        _lands(38, fixing_every=3)
        + _copies("Ramp Growth", 14, tags=["#Ramp"], mana_value=2, type_line="Sorcery", oracle_text="Search your library for a land card and put it onto the battlefield tapped.")
        + _copies("Cycle Draw", 8, tags=["#Draw"], mana_value=2, type_line="Sorcery", oracle_text="Draw a card.")
        + _copies("Land Recursion", 10, tags=["#Recursion", "#Engine"], mana_value=3, type_line="Sorcery", oracle_text="Return target land card from your graveyard to the battlefield tapped.")
        + _copies("Landfall Payoff", 10, tags=["#Payoff", "#Wincon"], mana_value=4, type_line="Enchantment", oracle_text="Whenever a land enters the battlefield under your control, each opponent loses 1 life.", is_permanent=True, repeatable_burn=1.0)
        + _copies("Removal", 8, tags=["#Removal"], mana_value=2, type_line="Instant", oracle_text="Destroy target creature.")
        + _copies("Support Body", 11, tags=["#Setup"], mana_value=3, type_line="Creature - Elemental", oracle_text="", is_creature=True, is_permanent=True, power=3),
        expected_primary_plan="drain",
    )

    fixtures["control_stax"] = _single_commander_fixture(
        "control_stax",
        "Control Stax",
        _card(
            "Arbiter of Silence",
            section="commander",
            tags=["#CommanderSynergy", "#Control", "#Stax"],
            mana_value=4,
            type_line="Legendary Creature - Advisor",
            oracle_text="At the beginning of your upkeep, draw a card.",
            is_creature=True,
            is_permanent=True,
            power=2,
        ),
        _lands(38, fixing_every=5)
        + _copies("Stone", 10, tags=["#Ramp"], mana_value=2, type_line="Artifact", oracle_text="{T}: Add {C}.", is_permanent=True, produced_mana=["C"])
        + _copies("Counter", 12, tags=["#Counter", "#Protection"], mana_value=2, type_line="Instant", oracle_text="Counter target spell.")
        + _copies("Removal", 10, tags=["#Removal"], mana_value=2, type_line="Instant", oracle_text="Destroy target creature.")
        + _copies("Stax Piece", 12, tags=["#Stax", "#Control"], mana_value=3, type_line="Artifact", oracle_text="", is_permanent=True)
        + _copies("Draw", 8, tags=["#Draw"], mana_value=2, type_line="Sorcery", oracle_text="Draw a card.")
        + _copies("Clock", 9, tags=["#Payoff"], mana_value=4, type_line="Creature - Angel", oracle_text="Flying", is_creature=True, is_permanent=True, power=4, evasion_score=0.4),
        expected_primary_plan="combat",
    )

    fixtures["explicit_alt_win"] = _single_commander_fixture(
        "explicit_alt_win",
        "Explicit Alternate Win",
        _card(
            "Life Warden",
            section="commander",
            tags=["#CommanderSynergy", "#Engine"],
            mana_value=4,
            type_line="Legendary Creature - Cleric",
            oracle_text="Whenever a creature enters the battlefield under your control, you gain 1 life.",
            is_creature=True,
            is_permanent=True,
            power=2,
        ),
        _lands(38, fixing_every=4)
        + _copies("Stone", 10, tags=["#Ramp"], mana_value=2, type_line="Artifact", oracle_text="{T}: Add {C}.", is_permanent=True, produced_mana=["C"])
        + _copies("Life Gain", 12, tags=["#Engine"], mana_value=2, type_line="Enchantment", oracle_text="Whenever a creature enters the battlefield under your control, you gain 1 life.", is_permanent=True)
        + _copies("Token Maker", 10, tags=["#Setup"], mana_value=3, type_line="Sorcery", oracle_text="Create two 1/1 white Soldier creature tokens.", token_bodies=2, token_attack_power=1)
        + _copies("Felidar Gate", 1, tags=["#Wincon"], mana_value=6, type_line="Creature - Cat Beast", oracle_text="At the beginning of your upkeep, if you have 40 or more life, you win the game.", is_creature=True, is_permanent=True, power=4, alt_win_kind="life40")
        + _copies("Protection", 8, tags=["#Protection"], mana_value=1, type_line="Instant", oracle_text="Target permanent gains hexproof.")
        + _copies("Draw", 10, tags=["#Draw"], mana_value=2, type_line="Sorcery", oracle_text="Draw a card.")
        + _copies("Support", 10, tags=["#Setup"], mana_value=3, type_line="Creature - Cleric", oracle_text="", is_creature=True, is_permanent=True, power=2),
        expected_primary_plan="alt-win",
    )

    fixtures["multi_commander"] = _dual_commander_fixture(
        "multi_commander",
        "Partner Pair",
        [
            _card("Forge Partner", section="commander", tags=["#CommanderSynergy", "#Engine"], mana_value=3, type_line="Legendary Creature - Artificer", oracle_text="{T}: Add {C}.", is_creature=True, is_permanent=True, power=2, produced_mana=["C"]),
            _card("Blade Partner", section="commander", tags=["#CommanderSynergy", "#Payoff"], mana_value=3, type_line="Legendary Creature - Warrior", oracle_text="Whenever equipped creature attacks, draw a card.", is_creature=True, is_permanent=True, power=3, evasion_score=0.3),
        ],
        _lands(38, fixing_every=4)
        + _copies("Stone", 10, tags=["#Ramp"], mana_value=2, type_line="Artifact", oracle_text="{T}: Add {C}.", is_permanent=True, produced_mana=["C"])
        + _copies("Equipment", 12, tags=["#Setup", "#Payoff"], mana_value=2, type_line="Artifact - Equipment", oracle_text="Equipped creature gets +2/+0.", is_permanent=True, commander_buff=1.0)
        + _copies("Tutor", 8, tags=["#Tutor"], mana_value=2, type_line="Sorcery", oracle_text="Search your library for an artifact or enchantment card, reveal it, put it into your hand.")
        + _copies("Counter", 8, tags=["#Counter", "#Protection"], mana_value=2, type_line="Instant", oracle_text="Counter target spell.")
        + _copies("Draw", 8, tags=["#Draw"], mana_value=2, type_line="Sorcery", oracle_text="Draw a card.")
        + _copies("Body", 14, tags=["#Setup"], mana_value=3, type_line="Creature - Soldier", oracle_text="", is_creature=True, is_permanent=True, power=3),
        expected_primary_plan="combat",
        parity_supported=True,
    )

    fixtures["text_dense_canary"] = _single_commander_fixture(
        "text_dense_canary",
        "Unsupported-Text Canary",
        _card(
            "Rules Knot",
            section="commander",
            tags=["#CommanderSynergy", "#Engine"],
            mana_value=5,
            type_line="Legendary Creature - Sphinx",
            oracle_text="Whenever you cast your first spell each turn, copy that spell. Cascade.",
            is_creature=True,
            is_permanent=True,
            power=4,
        ),
        _lands(38, fixing_every=4)
        + _copies("Stone", 10, tags=["#Ramp"], mana_value=2, type_line="Artifact", oracle_text="{T}: Add {C}.", is_permanent=True, produced_mana=["C"])
        + _copies("Storm Line", 10, tags=["#Combo", "#Engine"], mana_value=3, type_line="Sorcery", oracle_text="Storm. Draw a card.")
        + _copies("Cascade Engine", 10, tags=["#Engine"], mana_value=4, type_line="Enchantment", oracle_text="Cascade. Whenever you cast a spell, copy target spell you control.", is_permanent=True)
        + _copies("Modal Value", 10, tags=["#Draw", "#Setup"], mana_value=3, type_line="Instant", oracle_text="Choose one or both — Draw two cards; or create a token.")
        + _copies("Tutor", 8, tags=["#Tutor"], mana_value=2, type_line="Sorcery", oracle_text="Search your library for an artifact or enchantment card, reveal it, put it into your hand.")
        + _copies("Counter", 8, tags=["#Counter", "#Protection"], mana_value=2, type_line="Instant", oracle_text="Counter target spell.")
        + _copies("Payoff", 5, tags=["#Payoff", "#Wincon"], mana_value=5, type_line="Creature - Wizard", oracle_text="", is_creature=True, is_permanent=True, power=4),
        expected_primary_plan="combo",
        unsupported_risk_expected=True,
    )

    return fixtures


SIM_BENCHMARK_FIXTURES = build_sim_benchmark_fixtures()
