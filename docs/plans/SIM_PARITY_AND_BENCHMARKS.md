# Simulator Parity And Benchmarks

This document defines the WP8 rollout contract for simulator trust.

## Benchmark fixture suite

The benchmark deck suite lives in:

- `apps/api/tests/sim_benchmark_fixtures.py`

It covers:

- combat go-wide
- voltron
- toxic / proliferate
- aristocrats / drain
- spellslinger combo
- artifact combo
- graveyard combo
- lands engine
- control / stax
- explicit alt-win
- multi-commander
- text-dense unsupported canary

`parity_supported=True` means the fixture is valid for Python vs NumPy parity checks.

`unsupported_risk_expected=True` means the fixture should surface unsupported-effect risk rather than pretending full support.

## Test layers

### 1. Micro mechanics

Focused unit tests validate:

- commander tax increments
- partner commander-damage separation
- infect / toxic correctness
- selective untap behavior
- upkeep alt-win timing
- tutor choice based on missing winline piece

### 2. Benchmark smoke

Every benchmark fixture must:

- compile into a deck fingerprint
- produce coverage summary and support confidence
- emit outcome tiers in the Python reference backend

### 3. Supported-subset backend parity

NumPy parity is intentionally limited to fixtures marked `parity_supported=True`.

The current parity gate checks:

- resolved policy agreement
- opening hand
- mulligan count
- first-turn land
- first-turn cast sequence
- mana milestone bands
- commander-slot preservation

This is deliberate. The Python backend currently leads semantic coverage.

## Shadow validator

Debug-only CLI:

```bash
./.venv/bin/python apps/api/scripts/sim_shadow_validate.py --fixture artifact_combo --seed 42 --runs 64
```

It compares the shared summary slice across:

- Python reference backend
- NumPy backend

The shadow validator is for replay/debug inspection only. It is not the production runtime path.

## Rollout policy

- Python remains the semantic reference interpreter.
- NumPy remains opt-in / bounded by the parity-supported subset until later work packages close the remaining semantic gap.
- Unsupported-effect risk must stay visible in benchmark outputs and coverage summaries.
