from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sim.config import resolve_sim_config
from sim.engine import run_simulation_batch as run_python
from sim.engine_vectorized import run_simulation_batch_vectorized as run_vectorized


TESTS_DIR = Path(__file__).resolve().parents[1] / "tests"
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from sim_benchmark_fixtures import SIM_BENCHMARK_FIXTURES  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Debug-only shadow validator for simulator backend drift.")
    parser.add_argument("--fixture", help="Benchmark fixture slug to run.", default=None)
    parser.add_argument("--cards-file", help="JSON file containing card payloads.", default=None)
    parser.add_argument("--commander", action="append", default=[], help="Commander name. Repeat for partners.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--runs", type=int, default=64)
    parser.add_argument("--turn-limit", type=int, default=8)
    parser.add_argument("--policy", default="optimized")
    parser.add_argument("--color-identity-size", type=int, default=3)
    parser.add_argument("--threat-model", action="store_true")
    return parser.parse_args()


def _load_cards(args: argparse.Namespace) -> tuple[list[dict[str, Any]], str | list[str] | None]:
    if args.fixture:
        fixture = SIM_BENCHMARK_FIXTURES[args.fixture]
        commander: str | list[str] | None
        if not fixture.commanders:
            commander = None
        elif len(fixture.commanders) == 1:
            commander = fixture.commanders[0]
        else:
            commander = list(fixture.commanders)
        return fixture.cards, commander
    if not args.cards_file:
        raise SystemExit("Provide either --fixture or --cards-file.")
    cards = json.loads(Path(args.cards_file).read_text())
    if len(args.commander) == 0:
        commander: str | list[str] | None = None
    elif len(args.commander) == 1:
        commander = args.commander[0]
    else:
        commander = list(args.commander)
    return cards, commander


def _shared_summary(summary: dict[str, Any]) -> dict[str, Any]:
    win_metrics = summary.get("win_metrics", {})
    milestones = summary.get("milestones", {})
    trace = summary.get("reference_trace", {})
    turns = trace.get("turns", [])
    first_turn = turns[0] if turns else {}
    return {
        "backend_used": summary.get("backend_used"),
        "resolved_policy": summary.get("resolved_policy", {}).get("resolved_policy"),
        "commander_slots": summary.get("commander_slots", []),
        "opening_hand": trace.get("opening_hand", []),
        "mulligans_taken": trace.get("mulligans_taken"),
        "first_turn_land": first_turn.get("land"),
        "first_turn_casts": first_turn.get("casts", []),
        "p_mana4_t3": milestones.get("p_mana4_t3"),
        "p_mana5_t4": milestones.get("p_mana5_t4"),
        "median_commander_cast_turn": milestones.get("median_commander_cast_turn"),
        "p_win_by_turn_limit": win_metrics.get("p_win_by_turn_limit"),
        "support_confidence": summary.get("support_confidence"),
    }


def main() -> int:
    args = _parse_args()
    cards, commander = _load_cards(args)
    resolved = resolve_sim_config(
        commander=commander,
        requested_policy=args.policy,
        bracket=3,
        turn_limit=args.turn_limit,
        multiplayer=True,
        threat_model=args.threat_model,
        primary_wincons=None,
        color_identity_size=args.color_identity_size,
        seed=args.seed,
    )
    kwargs = {
        "cards": cards,
        "commander": commander,
        "runs": args.runs,
        "turn_limit": args.turn_limit,
        "policy": args.policy,
        "multiplayer": True,
        "threat_model": args.threat_model,
        "seed": args.seed,
        "resolved_config": resolved.to_payload(),
    }
    py = run_python(**kwargs)["summary"]
    vec = run_vectorized(**kwargs, batch_size=min(256, max(32, args.runs)))["summary"]

    py_shared = _shared_summary(py)
    vec_shared = _shared_summary(vec)
    diffs = {
        key: {"python": py_shared.get(key), "vectorized": vec_shared.get(key)}
        for key in sorted(set(py_shared) | set(vec_shared))
        if py_shared.get(key) != vec_shared.get(key)
    }
    payload = {
        "status": "match" if not diffs else "drift",
        "input": {
            "fixture": args.fixture,
            "runs": args.runs,
            "seed": args.seed,
            "policy": args.policy,
            "turn_limit": args.turn_limit,
            "threat_model": args.threat_model,
        },
        "python": py_shared,
        "vectorized": vec_shared,
        "diffs": diffs,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
