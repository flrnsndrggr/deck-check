from app.services.parser import parse_decklist, strip_about_block


def test_strip_about_block():
    text = "1 Sol Ring\nAbout\nmetadata\n1 Arcane Signet"
    assert strip_about_block(text).strip() == "1 Sol Ring"


def test_parse_headers_quantities_and_commander():
    raw = """Commander
1 Atraxa, Praetors' Voice
Deck
1x Sol Ring
98 Island
"""
    parsed = parse_decklist(raw)
    assert parsed.commander == "Atraxa, Praetors' Voice"
    assert parsed.commanders == ["Atraxa, Praetors' Voice"]
    assert sum(c.qty for c in parsed.cards if c.section in {"deck", "commander"}) == 100
    assert not parsed.errors


def test_parse_supports_two_commanders():
    raw = """Commander
1 Tymna the Weaver
1 Kraum, Ludevic's Opus
Deck
98 Island
"""
    parsed = parse_decklist(raw)
    assert parsed.commander == "Tymna the Weaver"
    assert parsed.commanders == ["Tymna the Weaver", "Kraum, Ludevic's Opus"]
    assert not parsed.errors


def test_parse_strips_trailing_moxfield_tags():
    raw = """Commander
1 Atraxa, Praetors' Voice #CommanderSynergy
Deck
1 Sol Ring #!Ramp #!Rock
98 Island
"""
    parsed = parse_decklist(raw)
    assert parsed.commander == "Atraxa, Praetors' Voice"
    names = [c.name for c in parsed.cards]
    assert "Sol Ring" in names
    assert "Sol Ring #!Ramp #!Rock" not in names
    assert not parsed.errors


def test_parse_strips_tags_from_split_cards():
    raw = """Commander
1 Narset, Enlightened Exile
Deck
1 Dusk // Dawn #Setup #Spellslinger
98 Island
"""
    parsed = parse_decklist(raw)
    names = [c.name for c in parsed.cards]
    assert "Dusk // Dawn" in names
    assert "Dusk // Dawn #Setup #Spellslinger" not in names
    assert not parsed.errors
