from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.schemas.deck import CardEntry
from app.services.replacements import strict_replacement_shadow_report


def _load_cards(path: Path) -> list[CardEntry]:
    payload = json.loads(path.read_text())
    if isinstance(payload, dict) and "cards" in payload:
        payload = payload["cards"]
    if not isinstance(payload, list):
        raise ValueError("cards file must be a JSON list or an object with a 'cards' key")
    return [CardEntry(**row) for row in payload]


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare strict replacement output against a relaxed shadow baseline.")
    parser.add_argument("--cards-file", required=True, help="Path to JSON file containing CardEntry rows or {'cards': [...]} payload")
    parser.add_argument("--selected-card", required=True, help="Name of the selected card to evaluate")
    parser.add_argument("--commander", default=None, help="Optional commander display name override")
    parser.add_argument("--budget-max-usd", type=float, default=None, help="Optional budget ceiling")
    parser.add_argument("--limit", type=int, default=10, help="Max accepted options to include per mode")
    args = parser.parse_args()

    report = strict_replacement_shadow_report(
        cards=_load_cards(Path(args.cards_file)),
        selected_card=args.selected_card,
        commander=args.commander,
        budget_max_usd=args.budget_max_usd,
        limit=args.limit,
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
