import random

import sim.engine as eng
from sim.engine import Card, london_mulligan


def test_london_mulligan_multiplayer_first_free():
    deck = [Card(name=f"Land{i}", tags=["#Land"], mana_value=0) for i in range(40)] + [
        Card(name=f"Spell{i}", tags=["#Draw"], mana_value=2) for i in range(60)
    ]
    rng = random.Random(1)
    hand, mulligans = london_mulligan(deck, policy="casual", multiplayer=True, rng=rng, colors_required=2)
    assert len(hand) <= 7
    if mulligans == 1:
        assert len(hand) == 7


def test_first_mulligan_free_bottoming_is_applied(monkeypatch):
    deck = [Card(name=f"L{i}", tags=["#Land"], mana_value=0) for i in range(40)] + [
        Card(name=f"S{i}", tags=["#Draw"], mana_value=2) for i in range(60)
    ]
    calls = {"n": 0}

    def fake_keep(*args, **kwargs):
        calls["n"] += 1
        return calls["n"] >= 2

    monkeypatch.setattr(eng, "_keep_hand", fake_keep)
    hand, mulligans = london_mulligan(deck, policy="casual", multiplayer=True, rng=random.Random(7), colors_required=2)
    assert mulligans == 1
    assert len(hand) == 7
