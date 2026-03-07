from sim.engine import (
    Card,
    _activated_actions,
    _add_permanent,
    _build_sim_deck,
    _normalize_name,
    _queue_upkeep_triggers,
    _resolve_trigger_queue,
)
from sim.ir import compile_card_execs
from sim.state import GameState


def _raw_card(
    name: str,
    *,
    type_line: str,
    oracle_text: str,
    mana_value: int = 2,
    is_creature: bool = False,
    is_permanent: bool = True,
    tags: list[str] | None = None,
) -> dict:
    return {
        "name": name,
        "qty": 1,
        "type_line": type_line,
        "oracle_text": oracle_text,
        "mana_value": mana_value,
        "is_creature": is_creature,
        "is_permanent": is_permanent,
        "tags": tags or [],
    }


def _compile_lookup(*raw_cards: dict) -> dict:
    compiled = compile_card_execs(list(raw_cards))
    return {_normalize_name(card_exec.name): card_exec for card_exec in compiled}


def _deck_card(raw_card: dict) -> Card:
    deck, _ = _build_sim_deck([raw_card], None)
    return deck[0]


def test_etb_trigger_queue_draws_from_library():
    raw = _raw_card(
        "Wall of Omens",
        type_line="Creature - Wall",
        oracle_text="When Wall of Omens enters the battlefield, draw a card.",
        mana_value=2,
        is_creature=True,
        is_permanent=True,
    )
    lookup = _compile_lookup(raw)
    card = _deck_card(raw)
    state = GameState(library=[Card(name="Plains", type_line="Land", is_permanent=True)])

    _add_permanent(state, card, lookup[_normalize_name(card.name)])
    assert len(state.pending_triggers) == 1

    _resolve_trigger_queue(state)

    assert [drawn.name for drawn in state.hand] == ["Plains"]
    assert not state.pending_triggers


def test_upkeep_trigger_can_create_tokens_into_bucketed_state():
    raw = _raw_card(
        "Assemble the Troops",
        type_line="Enchantment",
        oracle_text="At the beginning of your upkeep, create a 1/1 white Soldier creature token.",
        mana_value=3,
        is_creature=False,
        is_permanent=True,
    )
    lookup = _compile_lookup(raw)
    card = _deck_card(raw)
    state = GameState()

    _add_permanent(state, card, lookup[_normalize_name(card.name)])
    _queue_upkeep_triggers(state)
    _resolve_trigger_queue(state)

    assert state.token_buckets
    token_sig, count = next(iter(state.token_buckets.items()))
    assert count >= 1
    assert token_sig.power >= 1.0


def test_mana_source_activated_ability_is_repeatable_across_turn_reset():
    raw = _raw_card(
        "Mind Stone",
        type_line="Artifact",
        oracle_text="{T}: Add {C}.",
        mana_value=2,
        is_permanent=True,
        tags=["#Ramp", "#Rock"],
    )
    lookup = _compile_lookup(raw)
    card = _deck_card(raw)
    state = GameState()
    permanent = _add_permanent(state, card, lookup[_normalize_name(card.name)])

    actions = _activated_actions(state)
    assert any(effect_kind == "mana_source" for _, _, effect_kind in actions)

    permanent.tapped = True
    permanent.used_this_turn = True
    state.used_this_turn.add(permanent.permanent_id)
    assert _activated_actions(state) == []

    permanent.tapped = False
    permanent.used_this_turn = False
    state.used_this_turn.clear()

    actions = _activated_actions(state)
    assert any(effect_kind == "mana_source" for _, _, effect_kind in actions)


def test_sac_outlet_requires_external_fodder_and_death_payoff():
    sac_raw = _raw_card(
        "Viscera Seer",
        type_line="Creature - Vampire Wizard",
        oracle_text="Sacrifice another creature: Scry 1.",
        mana_value=1,
        is_creature=True,
        is_permanent=True,
    )
    payoff_raw = _raw_card(
        "Blood Artist",
        type_line="Creature - Vampire",
        oracle_text="Whenever a creature dies, target player loses 1 life and you gain 1 life.",
        mana_value=2,
        is_creature=True,
        is_permanent=True,
    )
    lookup = _compile_lookup(sac_raw, payoff_raw)
    sac_card = _deck_card(sac_raw)
    payoff_card = _deck_card(payoff_raw)
    state = GameState()

    _add_permanent(state, sac_card, lookup[_normalize_name(sac_card.name)])
    _add_permanent(state, payoff_card, lookup[_normalize_name(payoff_card.name)])
    assert not any(effect_kind == "sac_outlet" for _, _, effect_kind in _activated_actions(state))

    helper_raw = _raw_card(
        "Doomed Traveler",
        type_line="Creature - Human Soldier",
        oracle_text="When Doomed Traveler dies, create a 1/1 white Spirit creature token with flying.",
        mana_value=1,
        is_creature=True,
        is_permanent=True,
    )
    helper_lookup = _compile_lookup(helper_raw)
    helper_card = _deck_card(helper_raw)
    _add_permanent(state, helper_card, helper_lookup[_normalize_name(helper_card.name)])

    assert any(effect_kind == "sac_outlet" for _, _, effect_kind in _activated_actions(state))
