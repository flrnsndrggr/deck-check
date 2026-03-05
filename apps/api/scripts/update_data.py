from __future__ import annotations

import argparse

from app.db.session import SessionLocal
import app.models  # noqa: F401
from app.services.updates import update_all_data, update_banned_and_brackets
from app.services.rules_index import refresh_rules_index
from app.services.scryfall import CardDataService


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--scryfall", action="store_true")
    parser.add_argument("--rules", action="store_true")
    parser.add_argument("--brackets", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()

    if args.all:
        update_all_data(db)
    else:
        if args.scryfall:
            svc = CardDataService()
            svc.refresh_bulk_snapshot()
            svc.ingest_bulk_snapshot(limit=20000)
        if args.rules:
            refresh_rules_index(db)
        if args.brackets:
            update_banned_and_brackets(db)

    db.close()


if __name__ == "__main__":
    main()
