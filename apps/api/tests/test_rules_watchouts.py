from app.schemas.deck import CardEntry
from app.services.rules_watchouts import _complexity_flags, _rule_keywords


def test_complexity_flags_detects_common_patterns():
    txt = (
        "At the beginning of your upkeep, if you control another creature, "
        "you may cast this card from your graveyard instead. "
        "As an additional cost to cast this spell, sacrifice a creature."
    )
    flags = _complexity_flags(txt)
    assert "Triggered timing" in flags
    assert "Conditional replacement" in flags
    assert "Additional casting costs" in flags


def test_rules_watchout_request_schema_compiles():
    req = [CardEntry(qty=1, name="Sol Ring", section="deck")]
    assert req[0].name == "Sol Ring"


def test_rule_keyword_mapping():
    keys = _rule_keywords(["Replacement effect", "Stack interaction"])
    assert "replacement effect" in keys
    assert "counter target spell" in keys
