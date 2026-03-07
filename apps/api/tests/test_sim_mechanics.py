from __future__ import annotations

from sim.engine import (
    Card,
    _add_permanent,
    _allocate_attacks,
    _attacker_units,
    _build_sim_deck,
    _evaluate_outcome,
    _normalize_name,
    _pick_tutor_target,
    _record_commander_cast,
    _resolve_card_effect,
)
from sim.ir import CoverageSummary, DeckFingerprint, Winline, compile_card_execs
from sim.opponents import VirtualOpponent, VirtualTable
from sim.state import GameState, PermanentState


class _Exec:
    def __init__(self, executable=(), support_score=1.0):
        self.coverage_summary = CoverageSummary(
            executable=tuple(executable),
            evaluative_only=(),
            unsupported=(),
            support_score=support_score,
        )
        self.alt_win_rules = ()
        self.activated = ()
        self.triggers = {}


def _goldfish_table() -> VirtualTable:
    return VirtualTable(
        opponents=[
            VirtualOpponent("goldfish", 0.0, 0.0, 0, 0, 0, 0.0, 0.0, 1.0, 0, 0),
            VirtualOpponent("goldfish", 0.0, 0.0, 0, 0, 0, 0.0, 0.0, 1.0, 0, 0),
            VirtualOpponent("goldfish", 0.0, 0.0, 0, 0, 0, 0.0, 0.0, 1.0, 0, 0),
        ],
        base_table_noise=0.0,
    )


def _deck_card(raw_card: dict) -> Card:
    deck, _ = _build_sim_deck([raw_card], None)
    return deck[0]


def test_commander_tax_increments_per_cast():
    state = GameState()
    state.commander_zone[0] = Card(name="Commander One", is_commander=True, is_creature=True, is_permanent=True)

    _record_commander_cast(state, 0)
    assert state.commander_casts[0] == 1
    assert state.commander_tax[0] == 2
    assert state.commander_zone[0] is None

    state.commander_zone[0] = Card(name="Commander One", is_commander=True, is_creature=True, is_permanent=True)
    _record_commander_cast(state, 0)
    assert state.commander_casts[0] == 2
    assert state.commander_tax[0] == 4


def test_partner_commander_damage_is_tracked_separately():
    state = GameState(
        opp_life=[40.0, 40.0, 40.0],
        opp_cmdr_dmg=[
            [10.0, 21.0, 21.0],
            [11.0, 0.0, 0.0],
        ],
    )
    fingerprint = DeckFingerprint(
        primary_plan="combat",
        secondary_plan=None,
        commander_role="payoff",
        speed_tier="optimized",
        prefers_focus_fire=True,
        protection_density=0.0,
        resource_profile=(),
        conversion_profile=("combat",),
        wipe_recovery=0.0,
        support_confidence=1.0,
    )

    outcome = _evaluate_outcome(
        state=state,
        selected_wincons=["Commander Damage"],
        fingerprint=fingerprint,
        opponent_table=_goldfish_table(),
        current_window="combat",
        combat_snapshot=None,
        commanders=["Partner A", "Partner B"],
        combo_variants=[],
        combo_source_live=False,
        commander_live_names=set(),
    )

    assert outcome.tier.value != "hard_win"


def test_infect_updates_poison_and_commander_damage_without_life_loss():
    commander_name = "Plague Captain"
    state = GameState(turn=4)
    attacker = PermanentState(
        permanent_id=1,
        card=Card(
            name=commander_name,
            is_commander=True,
            is_creature=True,
            is_permanent=True,
            power=5.0,
            infect=True,
            evasion_score=0.45,
        ),
        card_exec=None,
    )
    state.battlefield = [attacker]
    fingerprint = DeckFingerprint(
        primary_plan="poison",
        secondary_plan=None,
        commander_role="payoff",
        speed_tier="optimized",
        prefers_focus_fire=True,
        protection_density=0.0,
        resource_profile=(),
        conversion_profile=("poison",),
        wipe_recovery=0.0,
        support_confidence=1.0,
    )

    units = _attacker_units(state, [attacker], (commander_name,))
    snapshot = _allocate_attacks(state, units, (commander_name,), _goldfish_table(), fingerprint)

    assert snapshot["projected_life"][0] == 40.0
    assert snapshot["projected_poison"][0] >= 5.0
    assert snapshot["projected_cmdr_dmg"][0][0] >= 5.0


def test_toxic_adds_poison_without_replacing_damage():
    attacker = PermanentState(
        permanent_id=1,
        card=Card(
            name="Toxic Striker",
            is_creature=True,
            is_permanent=True,
            power=3.0,
            toxic=2.0,
            evasion_score=0.45,
        ),
        card_exec=None,
    )
    state = GameState(turn=4, battlefield=[attacker])
    fingerprint = DeckFingerprint(
        primary_plan="poison",
        secondary_plan=None,
        commander_role="support",
        speed_tier="optimized",
        prefers_focus_fire=True,
        protection_density=0.0,
        resource_profile=(),
        conversion_profile=("poison",),
        wipe_recovery=0.0,
        support_confidence=1.0,
    )

    units = _attacker_units(state, [attacker], ())
    snapshot = _allocate_attacks(state, units, (), _goldfish_table(), fingerprint)

    assert snapshot["projected_life"][0] <= 37.0
    assert snapshot["projected_poison"][0] >= 2.0


def test_selective_untap_prefers_best_tapped_creature_when_converting():
    untap_card = Card(name="Mobilize", type_line="Instant")
    mana_source = PermanentState(
        permanent_id=1,
        card=Card(name="Mind Stone", tags=["#Ramp"], is_permanent=True),
        card_exec=_Exec(executable=("mana_source",)),
        tapped=True,
        used_this_turn=True,
    )
    attacker = PermanentState(
        permanent_id=2,
        card=Card(name="Threat", is_creature=True, is_permanent=True, power=4.0, evasion_score=0.4),
        card_exec=_Exec(),
        tapped=True,
        used_this_turn=True,
    )
    state = GameState(battlefield=[mana_source, attacker], used_this_turn={1, 2})

    _resolve_card_effect(state, untap_card, _Exec(), "selective_untap", current_intent="convert")

    assert attacker.tapped is False
    assert mana_source.tapped is True


def test_upkeep_alt_win_only_fires_in_correct_window():
    raw = {
        "name": "Felidar Gate",
        "qty": 1,
        "type_line": "Creature - Cat Beast",
        "oracle_text": "At the beginning of your upkeep, if you have 40 or more life, you win the game.",
        "mana_value": 6,
        "alt_win_kind": "life40",
        "is_creature": True,
        "is_permanent": True,
    }
    exec_lookup = {_normalize_name(card_exec.name): card_exec for card_exec in compile_card_execs([raw])}
    state = GameState(self_life=40.0)
    _add_permanent(state, _deck_card(raw), exec_lookup["felidar gate"])
    fingerprint = DeckFingerprint(
        primary_plan="alt-win",
        secondary_plan=None,
        commander_role="engine",
        speed_tier="optimized",
        prefers_focus_fire=False,
        protection_density=0.0,
        resource_profile=(),
        conversion_profile=("alt-win",),
        wipe_recovery=0.0,
        support_confidence=1.0,
    )

    upkeep = _evaluate_outcome(
        state=state,
        selected_wincons=["Alt Win"],
        fingerprint=fingerprint,
        opponent_table=_goldfish_table(),
        current_window="upkeep",
        combat_snapshot=None,
        commanders=None,
        combo_variants=[],
        combo_source_live=False,
        commander_live_names=set(),
    )
    draw_step = _evaluate_outcome(
        state=state,
        selected_wincons=["Alt Win"],
        fingerprint=fingerprint,
        opponent_table=_goldfish_table(),
        current_window="draw",
        combat_snapshot=None,
        commanders=None,
        combo_variants=[],
        combo_source_live=False,
        commander_live_names=set(),
    )

    assert upkeep.tier.value == "hard_win"
    assert draw_step.tier.value != "hard_win"


def test_tutor_selects_missing_piece_over_generic_payoff():
    commander = Card(name="Storm Savant", tags=["#Engine"], mana_value=3, is_creature=True, is_permanent=True)
    engine_piece = Card(name="Engine Piece", tags=["#Engine"], mana_value=3, is_permanent=True)
    combo_piece = Card(name="Combo Piece", tags=["#Combo"], mana_value=2)
    payoff = Card(name="Burn Payoff", tags=["#Payoff", "#Wincon"], mana_value=4)
    state = GameState(hand=[payoff], library=[payoff, combo_piece])
    fingerprint = DeckFingerprint(
        primary_plan="combo",
        secondary_plan=None,
        commander_role="engine",
        speed_tier="optimized",
        prefers_focus_fire=True,
        protection_density=0.0,
        resource_profile=("tutors",),
        conversion_profile=("combo",),
        wipe_recovery=0.0,
        support_confidence=1.0,
    )
    winlines = (
        Winline(
            kind="combo",
            requirements=("combo_piece", "engine"),
            support=("tutor",),
            sink_requirements=("sink",),
            horizon_class="now",
        ),
    )
    state.battlefield = [PermanentState(1, commander, _Exec()), PermanentState(2, engine_piece, _Exec())]

    pick = _pick_tutor_target(state, fingerprint, winlines)

    assert pick is not None
    assert pick.name == "Combo Piece"
