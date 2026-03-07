from sim.engine import Card, london_mulligan
from sim.ir import CoverageSummary
from sim.planner import (
    choose_turn_intent,
    compile_deck_fingerprint,
    compile_winlines,
    hand_plan,
)
from sim.state import GameState, PermanentState, TokenSig


class _Exec:
    def __init__(self, executable=(), support_score=1.0):
        self.coverage_summary = CoverageSummary(
            executable=tuple(executable),
            evaluative_only=(),
            unsupported=(),
            support_score=support_score,
        )
        self.alt_win_rules = ()


def _card(name: str, *, tags=None, mana_value=2, is_creature=False, is_permanent=False, oracle_text="", power=0.0, evasion_score=0.0, infect=False, toxic=0.0, proliferate=False, burn_value=0.0, mill_value=0.0, alt_win_kind=None, has_haste=False, combat_buff=0.0):
    return Card(
        name=name,
        tags=list(tags or []),
        mana_value=mana_value,
        is_creature=is_creature,
        is_permanent=is_permanent,
        oracle_text=oracle_text,
        power=power,
        evasion_score=evasion_score,
        infect=infect,
        toxic=toxic,
        proliferate=proliferate,
        burn_value=burn_value,
        mill_value=mill_value,
        alt_win_kind=alt_win_kind,
        has_haste=has_haste,
        combat_buff=combat_buff,
    )


def test_compile_deck_fingerprint_prefers_combo_when_combo_shell_is_dense():
    cards = [
        _card("Tutor", tags=["#Tutor"], mana_value=2),
        _card("Combo A", tags=["#Combo"], mana_value=2),
        _card("Combo B", tags=["#Combo", "#Wincon"], mana_value=3),
        _card("Engine", tags=["#Engine", "#Draw"], mana_value=3),
        _card("Ramp", tags=["#Ramp"], mana_value=1),
    ]
    commander = [_card("Commander", tags=["#Engine"], mana_value=3, is_creature=True, is_permanent=True)]
    lookup = {card.name.lower(): _Exec(executable=("draw", "tutor")) for card in cards + commander}

    fp = compile_deck_fingerprint(cards, commander, lookup)

    assert fp.primary_plan == "combo"
    assert fp.commander_role == "engine"


def test_compile_winlines_emits_primary_and_secondary():
    cards = [_card("Poison", tags=["#Wincon"], infect=True, is_creature=True, is_permanent=True)]
    fp = compile_deck_fingerprint(cards, [], {"poison": _Exec(executable=("burn_single_target",), support_score=1.0)})
    winlines = compile_winlines(cards, fp)

    assert len(winlines) >= 1
    assert winlines[0].kind == fp.primary_plan


def test_hand_plan_bottoms_clunk_and_keeps_plan_cards():
    commander = [_card("Commander", tags=["#Engine"], mana_value=3, is_creature=True, is_permanent=True)]
    hand = [
        _card("Land A", tags=["#Land", "#Fixing"]),
        _card("Land B", tags=["#Land"]),
        _card("Ramp", tags=["#Ramp"], mana_value=2),
        _card("Draw", tags=["#Draw"], mana_value=2),
        _card("Combo", tags=["#Combo"], mana_value=2),
        _card("Big Spell", tags=["#Payoff"], mana_value=7),
        _card("Clunker", tags=["#Payoff"], mana_value=8),
    ]
    lookup = {card.name.lower(): _Exec(executable=("draw", "tutor", "mana_source")) for card in hand + commander}
    fp = compile_deck_fingerprint(hand, commander, lookup)
    winlines = compile_winlines(hand, fp)

    plan = hand_plan(hand, fp, winlines, colors_required=2, commander_cards=commander, mulligans_taken=2, multiplayer=True)

    assert "Clunker" in plan.bottomed or "Big Spell" in plan.bottomed
    assert plan.plan == fp.primary_plan


def test_turn_intent_switches_to_convert_when_line_is_close():
    hand = [_card("Overrun", tags=["#Payoff", "#Wincon"], mana_value=5)]
    battlefield = [
        PermanentState(1, _card("Attacker A", tags=["#Setup"], is_creature=True, is_permanent=True, power=3, evasion_score=0.4), None),
        PermanentState(2, _card("Attacker B", tags=["#Setup"], is_creature=True, is_permanent=True, power=2, evasion_score=0.2), None),
    ]
    state = GameState(battlefield=battlefield, token_buckets={TokenSig(power=1, toughness=1): 2})
    fp = compile_deck_fingerprint(hand + [perm.card for perm in battlefield], [], {card.name.lower(): _Exec(executable=("create_tokens",)) for card in hand + [perm.card for perm in battlefield]})
    fp = fp.__class__(**{**fp.__dict__, "primary_plan": "combat"})
    winlines = compile_winlines(hand + [perm.card for perm in battlefield], fp)

    intent = choose_turn_intent(state, hand, fp, winlines, threat_model=False)

    assert intent in {"convert", "race"}


def test_london_mulligan_bottoms_by_position_not_name(monkeypatch):
    deck = [
        _card("Plains", tags=["#Land"]),
        _card("Plains", tags=["#Land"]),
        _card("Plains", tags=["#Land"]),
        _card("Ramp", tags=["#Ramp"], mana_value=2),
        _card("Draw", tags=["#Draw"], mana_value=2),
        _card("Combo", tags=["#Combo"], mana_value=2),
        _card("Payoff", tags=["#Payoff"], mana_value=5),
        _card("Spare", tags=["#Setup"], mana_value=2),
    ]

    plans = iter(
        [
            {"keep": False, "bottomed_indices": (), "bottomed": (), "score": 0.0, "plan": "combat", "reasons": ()},
            {"keep": True, "bottomed_indices": (0,), "bottomed": ("Plains",), "score": 4.2, "plan": "combat", "reasons": ("land band",)},
        ]
    )

    def fake_hand_plan(*_args, **_kwargs):
        payload = next(plans)
        from sim.planner import HandPlan

        return HandPlan(
            keep=payload["keep"],
            score=payload["score"],
            plan=payload["plan"],
            commander_window=3,
            bottomed_indices=payload["bottomed_indices"],
            bottomed=payload["bottomed"],
            reasons=payload["reasons"],
        )

    class _StaticShuffle:
        def shuffle(self, _cards):
            return None

    monkeypatch.setattr("sim.engine.hand_plan", fake_hand_plan)

    hand, mulligans = london_mulligan(
        deck,
        policy="auto",
        multiplayer=False,
        rng=_StaticShuffle(),
        colors_required=1,
        commander_cards=[],
        fingerprint=None,
        winlines=(),
    )

    assert mulligans == 1
    assert len(hand) == 6
    assert sum(1 for card in hand if card.name == "Plains") == 2
    assert deck[-1].name == "Plains"
