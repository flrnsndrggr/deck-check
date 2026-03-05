# Deck.Check: Design Review and Improvement Brief

This document proposes improvements to product UX, simulation fidelity, analytics quality, and technical architecture for Deck.Check.

## Constraints
- Deterministic and reproducible for a given seed and configuration.
- No full Magic rules engine.
- Recommendations must remain explainable.
- Must remain operable in local Docker Compose development.
- Simulation should remain asynchronous and scalable.

## Objective
Transform the tool from a goldfish simulator with analytics into a decision-support system for Commander deck design and play guidance.

## 1. Product UX and Information Architecture

### Deck Health Summary
Introduce a top-level diagnostic summary synthesizing analysis outputs into a small number of interpretable signals.

Recommended dimensions:
- Mana base stability
- Early game reliability
- Interaction density
- Game plan clarity
- Deck consistency

Each dimension should include:
- Status indicator (`healthy` / `warning` / `critical`)
- Short explanation
- Link to relevant detailed analysis

Reason:
Current outputs are detailed but fragmented; users need immediate structural interpretation.

Impact:
Lower cognitive load and faster interpretation.

Complexity:
Low.

Dependencies:
Analyzer outputs.

### Actionable Optimization Panel
Introduce a dedicated section translating findings into prioritized actions.

Examples:
- Add early ramp
- Increase draw engines
- Replace inefficient removal
- Increase win condition redundancy

Each action should:
- Link to affected deck section
- Link to suggested replacements
- Explain reasoning

Reason:
Users should not derive solutions manually from metrics.

Impact:
Converts analytics to practical guidance.

Complexity:
Low.

### Deck Plan Visualization
Introduce a visualization of expected strategic phases:
- Setup
- Engine development
- Win attempt

Overlay:
- Mana development
- Engine activation probability
- Win attempt timing

Reason:
Players think in plans, not isolated numbers.

Impact:
Improves strategy execution clarity.

Complexity:
Medium.

### Contextual Card Insight Panel
Use contextual right panel on card selection:
- Card importance score
- Typical cast turn distribution
- Synergy relationships
- Suggested replacements
- Simulation observations

Reason:
Card-level exploration should stay in-context.

Impact:
Better role understanding.

Complexity:
Low.

### Semantic Simulation Controls
Use mental-model controls instead of internal terms:
- Pod speed
- Interaction density
- Mulligan aggressiveness
- Removal frequency

Reason:
Players reason about metagame, not engine internals.

Impact:
Higher usability and trust.

Complexity:
Low.

## 2. Simulation Fidelity Improvements

### Priority-Based Casting Model
Layered action model:
1. Land drops
2. Mana acceleration
3. Card advantage engines
4. Commander deployment
5. Interaction
6. Win attempts

Context modifiers should adjust based on board state.

Reason:
Actual play is hierarchical and conditional.

Impact:
More realistic sequencing.

Complexity:
Medium.

### Synergy Trigger System
Introduce conditional behavioral triggers.

Examples:
- Commander in play boosts synergy card priority
- Draw engine online lowers urgency of additional draw
- Combo piece discovery shifts priorities

Reason:
Deck behavior changes after engine state changes.

Impact:
Substantial realism gain.

Complexity:
Medium.

### Win Condition Pattern Detection
Move from single-card win markers to pattern detection.

Patterns:
- Combat thresholds
- Resource loops
- Deterministic combo lines
- Token swarm finishes

Reason:
Most Commander wins are combinational.

Impact:
More accurate win outcome reporting.

Complexity:
Medium.

### Probabilistic Opponent Interaction
Model disruption events probabilistically:
- Spot removal
- Board wipes
- Counterspells

Scale by:
- Pod power level
- Turn number

Reason:
Pure goldfish inflates performance.

Impact:
Closer to real table behavior.

Complexity:
Medium.

## 3. Improved Outcome Metrics

### Consistency Score
Composite reliability metric from:
- Mulligan frequency
- Mana screw
- Flood
- Engine assembly reliability

Reason:
Users need one high-signal reliability indicator.

Impact:
Faster interpretation.

Complexity:
Low.

### Tempo Development Curve
Plot:
- Mana by turn
- Cards seen
- Board development proxy

Reason:
Tempo failures are common root causes.

Impact:
Exposes pacing problems.

Complexity:
Medium.

### Card Sensitivity Analysis
Run leave-one-out card experiments:
- Delta win probability
- Delta median win turn
- Delta failure modes

Reason:
Find truly influential cards.

Impact:
Better importance ranking.

Complexity:
Medium.

### Statistical Uncertainty Reporting
Add confidence intervals to key outputs.

Reason:
Avoid false precision from simulation noise.

Impact:
Higher trust.

Complexity:
Low.

## 4. Recommendation Engine Improvements

### Archetype Detection
Detect archetypes using:
- Tag clustering
- Commander signals
- Win pattern outputs

Examples:
- Aristocrats
- Spellslinger
- Stax
- Voltron
- Artifact combo
- Reanimator

Reason:
Recommendations must match identity.

Impact:
Higher relevance.

Complexity:
Medium.

### Role-Based Replacement Suggestions
For cuts, prioritize:
- Low impact
- Poor synergy
- Inefficient mana value

Suggest adds that:
- Keep same role
- Improve efficiency
- Improve synergy

Reason:
Users prefer concrete swaps.

Impact:
Higher adoption.

Complexity:
Medium.

### Commander-Specific Knowledge
Maintain commander-specific synergy datasets.

Reason:
Commander defines strategic identity.

Impact:
Strong relevance gains.

Complexity:
Medium.

### Budget-Aware Suggestions
Enable price-tier filtering (Scryfall prices).

Reason:
Budget constraints are common.

Impact:
Broader usability.

Complexity:
Low.

## 5. Data Quality and Update Pipeline

### Automated Scryfall Bulk Sync
Scheduled Oracle bulk ingestion.

Reason:
Avoid stale card data.

Complexity:
Low.

### Commander Rules Dataset
Maintain local dataset of:
- Banned cards
- Command zone exceptions
- Format-specific exceptions

Reason:
Commander legality has nontrivial exceptions.

Complexity:
Low.

### Curated Role Overrides
Curated card-role overrides for ambiguous staples.

Reason:
Many cards are multi-role or context-dependent.

Complexity:
Medium.

## 6. Performance and Scalability

### Vectorized Simulation
Refactor run loops for batched numerical ops.

Reason:
Large-run simulation benefits significantly.

Expected impact:
Potential order-of-magnitude speedup.

Complexity:
Medium.

### Deck Result Caching
Cache by:
- Deck hash
- Simulation config hash

Reason:
Users rerun similar configurations often.

Complexity:
Low.

### Worker Parallelization
Parallelize simulation batches across worker processes.

Reason:
Workload is embarrassingly parallel.

Complexity:
Low.

## 7. Testing Strategy

### Deck Regression Suite
Maintain representative deck corpus:
- Precons
- Casual
- Mid-power
- cEDH-like combo

Reason:
Detect realism regressions in behavior.

Complexity:
Low.

### Tagging Accuracy Tests
Golden tests for known cards.

Reason:
Tag quality propagates into all analytics.

Complexity:
Low.

### Simulation Sanity Tests
Statistical sanity checks for:
- Land drop rates
- Commander cast distributions
- Failure mode stability

Reason:
Keeps simulation outputs plausible.

Complexity:
Low.

## Strategic Outcome
If implemented, Deck.Check becomes:
- Deck diagnostics system
- Commander simulation lab
- Decision-support system for optimization
- Practical play-guidance generator

Most impactful priorities:
1. Priority-based casting model
2. Deck health summary
3. Consistency score
4. Commander-aware recommendations
5. Card sensitivity ranking

Together these improve analytical credibility and practical usefulness.

---

## Execution-Oriented Roadmap

### Next 2 Weeks
1. Ship Deck Health Summary cards + consistency score.
2. Replace remaining raw outputs with explained findings blocks.
3. Add uncertainty intervals to headline metrics.
4. Implement semantic sim controls mapping and tooltips across the app.
5. Add budget filter to recommendation generation and UI.

### Next 2 Months
1. Implement priority-based casting with context modifiers.
2. Add synergy trigger system and pattern-based win detection.
3. Add card sensitivity analysis pipeline with cached batched runs.
4. Introduce commander-specific recommendation packs.
5. Add deck regression benchmark suite and simulation sanity dashboards.
