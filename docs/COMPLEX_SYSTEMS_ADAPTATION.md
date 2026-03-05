# Complex Systems Methods Adapted to Commander Deck Analysis

This note captures methods borrowed from complex-systems analysis and how they are mapped to Deck.Check.

## Methods adapted

1. Entropy (diversity / distribution spread)
- Classic use: measure uncertainty/diversity in state distributions.
- Deck mapping: `role_entropy_bits` over tag-role counts.
- Interpretation:
  - very low entropy: one-dimensional plan, brittle to disruption.
  - very high entropy: broad toolkit but possible focus dilution.

2. Concentration and bottleneck analysis
- Classic use: identify concentrated dependency on a small set of nodes/resources.
- Deck mapping:
  - `bottleneck_index`: top-5 impact share.
  - `impact_inequality`: gini-like concentration over impact scores.
- Interpretation:
  - high concentration means the deck depends on few cards and needs redundancy/protection.

3. Resilience scoring
- Classic use: system stability under stress/failures.
- Deck mapping:
  - `resilience_score` from observed failure modes (mana screw, flood, no-action).
- Interpretation:
  - high resilience means the deck reliably functions despite draw variance.

4. Redundancy scoring
- Classic use: fault tolerance through alternative pathways/components.
- Deck mapping:
  - `redundancy_score` inverse of top-impact concentration.
- Interpretation:
  - high redundancy indicates multiple viable lines and better recovery.

## Why this helps Commander analysis

Commander decks are nonlinear systems with path dependency: opening resources, role overlap, and line availability create branching trajectories. Pure averages hide fragility. These metrics expose:
- where plans collapse,
- how concentrated success is,
- and whether the deck has enough alternative pathways.

## Current implementation in Deck.Check

- `systems_metrics` in `POST /api/analyze` response.
- Deck Analysis and Lenses UI sections render these metrics with plain-English interpretation.

## Future extensions

- Shock-response simulations (forced piece removal and recovery curves).
- Regime shifts by pod-speed bands (casual/mid/high-power) as separate resilience surfaces.
- Sensitivity topology (clustered card removals, not only single-card deltas).
