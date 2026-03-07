# Strict Replacement Shadow Rollout

This rollout compares the current proof-based strict evaluator against a deliberately looser shadow baseline so we can inspect where the new system is more conservative and whether those conservatisms are justified.

## Goal

Confirm that the strict evaluator rejects flashy false positives for the right reasons without silently dropping obviously valid replacements in the currently supported comparison classes.

## Shadow Modes

- `strict`
  - exact main type preservation
  - active theme preservation
  - required role preservation
  - no worse axes
  - no unknown axes
  - at least one better axis
- `legacy_relaxed`
  - exact main type preservation
  - family/class compatibility
  - no worse axes
  - does **not** require theme preservation or comparable-role preservation

The relaxed mode is not product truth. It exists only to surface `old-pass / new-fail` comparisons for review.

## How To Run

```bash
./.venv/bin/python apps/api/scripts/replacements_shadow_report.py \
  --cards-file /path/to/cards.json \
  --selected-card "Elvish Mystic" \
  --commander "Marwyn, the Nurturer" \
  --budget-max-usd 5
```

`cards.json` should contain either:

- a JSON list of `CardEntry` rows
- or an object with a top-level `"cards"` key containing those rows

## What To Inspect

Focus on these fields:

- `old_pass_new_fail`
  - candidates accepted by relaxed mode but rejected by strict mode
- `new_pass_old_fail`
  - candidates accepted only by strict mode
- `dominant_rejection_reasons`
  - top strict-mode rejection reasons
- `relaxed_rejection_reasons`
  - top relaxed-mode rejection reasons

## Review Priorities

Sample these first:

1. mana sources
2. typal decks
3. equipment package cards
4. aura package cards
5. shrine and background package cards
6. removal and counterspell swaps

For each sampled case, check:

- exact main types still match
- active deck themes are preserved when relevant
- budget filtering did not hide a valid result
- strict rejection reason is defensible and not merely accidental

## Success Criteria

The shadow rollout is successful when:

- most `old-pass / new-fail` cases are rejected for exact type, active theme, or unknown-axis reasons that are clearly correct
- `new-pass / old-fail` cases are either empty or trivially defensible
- supported families show stable, explainable pass rates
- no returned strict candidate violates:
  - exact main-type preservation
  - active theme preservation
  - budget constraints
  - no-worse / no-unknown axis guarantees

## Non-Goals

- This is not a legacy production path.
- This is not user-facing.
- This does not broaden supported comparison classes.
- This does not relax strict semantics to rescue marginal candidates.
