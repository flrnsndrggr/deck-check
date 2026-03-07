# Next Release Included Work

This file defines the intended scope for the next release cut. It exists to make sure the large local workstreams are not omitted just because they are spread across many files.

## Included Workstreams

### 1. Simulator Rewrite

The next release must include the compiled goldfish-engine work that currently lives in:

- `/Users/fs/Documents/15 CDX/Commander in Training/packages/sim/sim/config.py`
- `/Users/fs/Documents/15 CDX/Commander in Training/packages/sim/sim/ir.py`
- `/Users/fs/Documents/15 CDX/Commander in Training/packages/sim/sim/rng.py`
- `/Users/fs/Documents/15 CDX/Commander in Training/packages/sim/sim/tiebreak.py`
- `/Users/fs/Documents/15 CDX/Commander in Training/packages/sim/sim/state.py`
- `/Users/fs/Documents/15 CDX/Commander in Training/packages/sim/sim/planner.py`
- `/Users/fs/Documents/15 CDX/Commander in Training/packages/sim/sim/opponents.py`
- `/Users/fs/Documents/15 CDX/Commander in Training/packages/sim/sim/engine.py`
- `/Users/fs/Documents/15 CDX/Commander in Training/packages/sim/sim/engine_vectorized.py`
- `/Users/fs/Documents/15 CDX/Commander in Training/apps/api/app/workers/tasks.py`

This scope includes:

- canonical IR and resolved policy config
- deterministic RNG partitioning
- two-commander state model
- card compiler and coverage reporting
- trigger queue and activated ability support
- deck fingerprinting, winlines, mulligan, and intent policy
- hard/model/dominant win tiers
- latent opponent model
- parity and benchmark harness files under `apps/api/tests/`

### 2. Random Deck Generator V2

The next release must include the random-deck-generator redesign in:

- `/Users/fs/Documents/15 CDX/Commander in Training/apps/api/app/services/random_deck.py`
- `/Users/fs/Documents/15 CDX/Commander in Training/apps/api/app/services/scryfall.py`
- `/Users/fs/Documents/15 CDX/Commander in Training/apps/api/tests/test_random_deck.py`

This scope includes:

- neutral Scryfall retrieval
- commander plan inference
- package-core drafting
- coverage-based shell construction
- multi-factor card scoring
- multi-deck generation and reranking
- expanded deck-quality tests

### 3. Strictly Better Refactor

The next release must include the proof-based replacement evaluator in:

- `/Users/fs/Documents/15 CDX/Commander in Training/apps/api/app/services/replacements.py`
- `/Users/fs/Documents/15 CDX/Commander in Training/apps/api/app/schemas/deck.py`
- `/Users/fs/Documents/15 CDX/Commander in Training/apps/api/app/api/routes.py`
- `/Users/fs/Documents/15 CDX/Commander in Training/apps/api/tests/test_replacements.py`
- `/Users/fs/Documents/15 CDX/Commander in Training/apps/api/scripts/replacements_shadow_report.py`

This scope includes:

- shared normalized card profile
- deck context and theme obligations
- replacement contract and candidate query planning
- hard filters and strict evaluators
- explain mode
- regression and shadow-rollout support

## Release Gate

Do not call the next version complete unless these three workstreams are all present in the release branch:

1. simulator rewrite
2. random deck generator v2
3. proof-based strictly better evaluator

## Validation Expectation

The next release should use CI or a stable environment as the execution gate for these areas, because local runtime verification in the current machine state has been intermittent.
