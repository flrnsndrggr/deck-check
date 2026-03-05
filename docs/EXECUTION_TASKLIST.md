# Deck.Check Execution Tasklist

Status legend: `[x] done`, `[-] in progress`, `[ ] pending`

## P0: Immediate product impact
- [x] Deck health summary model (mana stability, early reliability, interaction density, plan clarity, consistency)
- [x] Consistency score (0-100) from failure + reliability metrics
- [x] Uncertainty intervals for key probability metrics
- [x] Budget-aware recommendation filtering (max USD)
- [x] Surface health + consistency + uncertainty in UI outcomes
- [x] Sim result caching by deck/config hash

## P1: High-value simulation realism
- [ ] Priority-based casting model with context modifiers
- [ ] Synergy trigger system (commander online / engine online state)
- [ ] Pattern-based win condition detection upgrades
- [ ] Probabilistic opponent disruption model by pod speed and turn

## P1: Recommendation quality
- [ ] Archetype classifier normalization + confidence output
- [ ] Role-preserving swap engine with efficiency delta scoring
- [ ] Commander-specific recommendation packs

## P1: UX + IA
- [ ] Actionable Optimization panel with ranked actions
- [ ] Deck plan visualization (setup -> engine -> win)
- [ ] Contextual card insight side panel (cast turn, synergy edges, replacements)

## P2: Data and scaling
- [ ] Curated role override table for ambiguous staples
- [ ] Regression deck corpus and simulation sanity benchmark suite
- [ ] Batched/vectorized simulation path
- [ ] Worker sharding controls and throughput dashboard
