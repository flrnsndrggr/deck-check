from sim.ir import compile_card_execs, summarize_compiled_execs


def test_compile_card_execs_marks_supported_primitives_executable() -> None:
    cards = [
        {
            "name": "Sol Ring",
            "oracle_id": "sol-ring",
            "type_line": "Artifact",
            "oracle_text": "{T}: Add {C}{C}.",
            "mana_value": 1,
            "is_permanent": True,
            "tags": ["#Ramp", "#Rock"],
            "produced_mana": ["C"],
        },
        {
            "name": "Felidar Sovereign",
            "oracle_id": "felidar",
            "type_line": "Creature — Cat Beast",
            "oracle_text": "At the beginning of your upkeep, if you have 40 or more life, you win the game.",
            "mana_value": 6,
            "is_creature": True,
            "is_permanent": True,
            "power": 4,
            "tags": ["#Wincon"],
            "alt_win_kind": "life40",
        },
    ]

    compiled = compile_card_execs(cards)

    sol_ring = compiled[0]
    assert sol_ring.coverage == "executable"
    assert "mana_source" in sol_ring.coverage_summary.executable
    assert "fast_mana" in sol_ring.coverage_summary.executable

    felidar = compiled[1]
    assert felidar.coverage == "executable"
    assert felidar.alt_win_rules
    assert "alt_win_rule" in felidar.coverage_summary.executable


def test_compile_card_execs_reports_unsupported_alt_win_explicitly() -> None:
    cards = [
        {
            "name": "Happily Ever After",
            "oracle_id": "hea",
            "type_line": "Enchantment",
            "oracle_text": (
                "When Happily Ever After enters the battlefield, each player gains 5 life and draws a card. "
                "At the beginning of your upkeep, if there are five colors among permanents you control, "
                "there are six or more card types among permanents you control and/or cards in your graveyard, "
                "and your life total is greater than or equal to your starting life total, you win the game."
            ),
            "mana_value": 4,
            "is_permanent": True,
            "tags": ["#Wincon", "#Engine"],
            "alt_win_kind": "generic",
        }
    ]

    compiled = compile_card_execs(cards)
    card = compiled[0]
    assert "Unsupported alternate-win predicate." in card.coverage_summary.unsupported
    assert card.coverage in {"evaluative-only", "unsupported"}


def test_summarize_compiled_execs_exposes_support_confidence_and_important_unsupported() -> None:
    cards = [
        {
            "name": "Mana Rock",
            "oracle_id": "rock",
            "type_line": "Artifact",
            "oracle_text": "{T}: Add {C}.",
            "mana_value": 2,
            "is_permanent": True,
            "tags": ["#Ramp"],
            "produced_mana": ["C"],
        },
        {
            "name": "Fragile Engine",
            "oracle_id": "engine",
            "type_line": "Enchantment",
            "oracle_text": "Cascade. Whenever you cast a spell, copy target spell you control.",
            "mana_value": 5,
            "is_permanent": True,
            "tags": ["#Engine", "#Combo"],
        },
    ]

    summary = summarize_compiled_execs(compile_card_execs(cards))

    assert summary["support_confidence"] < 1.0
    assert any(item["name"] == "Fragile Engine" for item in summary["important_cards"])
    assert any(item["effect"] == "Cascade unsupported." for item in summary["unsupported_effects"])
