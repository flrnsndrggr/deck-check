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
    assert sum(c.qty for c in parsed.cards if c.section in {"deck", "commander"}) == 100
    assert not parsed.errors
