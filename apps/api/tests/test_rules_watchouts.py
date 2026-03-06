from app.schemas.deck import CardEntry
from app.services import rules_watchouts as watchouts_mod
from app.services.rules_watchouts import _complexity_flags, _rule_keywords, build_rules_watchouts


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


def test_build_rules_watchouts_uses_scryfall_rulings_as_errata(monkeypatch):
    class _FakeSvc:
        def get_cards_by_name(self, names):
            return {
                "Gerrard's Hourglass Pendant": {
                    "name": "Gerrard's Hourglass Pendant",
                    "oracle_id": "oid-gerrard",
                    "oracle_text": "If a player would begin an extra turn, that player skips that turn instead.",
                    "type_line": "Legendary Artifact",
                    "released_at": "2025-01-01",
                    "scryfall_uri": "https://scryfall.example/gerrard",
                    "keywords": [],
                }
            }

        def get_rulings_by_oracle_id(self, card_map):
            return {
                "oid-gerrard": [
                    {"published_at": "2025-01-01", "comment": "This replacement effect applies before the extra turn begins."}
                ]
            }

    monkeypatch.setattr(watchouts_mod, "CardDataService", lambda: _FakeSvc())
    rows = build_rules_watchouts([CardEntry(qty=1, name="Gerrard's Hourglass Pendant", section="deck")], commander=None)
    assert len(rows) == 1
    assert rows[0]["errata"] == ["2025-01-01: This replacement effect applies before the extra turn begins."]
    assert rows[0]["notes"]
    assert rows[0]["rules_information"]


def test_build_rules_watchouts_includes_legacy_nonintuitive_mechanics(monkeypatch):
    class _FakeSvc:
        def get_cards_by_name(self, names):
            return {
                "Soraya the Falconer": {
                    "name": "Soraya the Falconer",
                    "oracle_id": "oid-soraya",
                    "oracle_text": "All Falcons get +1/+1. {1}{W}: Target Falcon gains banding until end of turn.",
                    "type_line": "Legendary Creature — Human",
                    "released_at": "1995-06-01",
                    "scryfall_uri": "https://scryfall.example/soraya",
                    "keywords": [],
                }
            }

        def get_rulings_by_oracle_id(self, card_map):
            return {}

    monkeypatch.setattr(watchouts_mod, "CardDataService", lambda: _FakeSvc())
    rows = build_rules_watchouts([CardEntry(qty=1, name="Soraya the Falconer", section="commander")], commander="Soraya the Falconer")
    assert len(rows) == 1
    assert "Banding" in rows[0]["complexity_flags"]
    assert any("older rules era" in note.lower() for note in rows[0]["notes"])
    assert any("banding" in info.lower() for info in rows[0]["rules_information"])


def test_build_rules_watchouts_does_not_truncate_qualifying_cards(monkeypatch):
    class _FakeSvc:
        def get_cards_by_name(self, names):
            return {
                name: {
                    "name": name,
                    "oracle_id": f"oid-{name}",
                    "oracle_text": "",
                    "type_line": "Artifact",
                    "released_at": "2024-01-01",
                    "scryfall_uri": f"https://scryfall.example/{name}",
                    "keywords": [],
                }
                for name in names
            }

        def get_rulings_by_oracle_id(self, card_map):
            return {
                card["oracle_id"]: [{"published_at": "2024-01-01", "comment": f"Ruling for {name}."}]
                for name, card in card_map.items()
            }

    monkeypatch.setattr(watchouts_mod, "CardDataService", lambda: _FakeSvc())
    cards = [CardEntry(qty=1, name=f"Card {i}", section="deck") for i in range(25)]
    rows = build_rules_watchouts(cards, commander=None)
    assert len(rows) == 25
