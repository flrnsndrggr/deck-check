from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from app.core.config import settings
from app.services.scryfall import CardDataService


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite-path", default=settings.card_cache_db)
    parser.add_argument("--batch-size", type=int, default=1000)
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite_path)
    if not sqlite_path.exists():
      print(f"sqlite cache not found: {sqlite_path}")
      return

    target = CardDataService(backend="postgres")
    moved = 0

    with sqlite3.connect(str(sqlite_path)) as conn:
        rows = conn.execute("SELECT payload FROM cards").fetchall()
        batch = []
        for row in rows:
            try:
                payload = json.loads(row[0])
            except Exception:
                continue
            batch.append(payload)
            if len(batch) >= args.batch_size:
                target._store_cards(batch)  # noqa: SLF001
                moved += len(batch)
                batch = []
        if batch:
            target._store_cards(batch)  # noqa: SLF001
            moved += len(batch)

    print(f"migrated {moved} card payloads into postgres cache")


if __name__ == "__main__":
    main()
