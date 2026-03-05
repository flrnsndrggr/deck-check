# Analysis Lenses (Deck.Check)

Deck.Check evaluates Commander decks through multiple complementary lenses.

## 1) Reliability and Mana Lens
- Mana percentile curve by turn (P50/P75/P90)
- On-curve land-drop probability by turn
- Color-access curve by turn

How to use:
- Slow mana curve + low on-curve land hits means the deck stalls before the plan begins.

## 2) Plan Execution Lens
- Setup/engine/win-attempt phase timeline
- Win-turn CDF
- Commander cast distribution
- Engine-online distribution

How to use:
- Setup should decline by turns 4-5 while engine and win-attempt phases rise.

## 3) Risk Lens
- No-action funnel by turn
- Dead-card concentration (cards stranded in hand)
- Failure mode rates (screw/flood/no-action)

How to use:
- If no-action is high early, lower curve and add cheap setup.
- If dead cards cluster in expensive spells, cut top-end or improve ramp.

## 4) Complex Systems Lens
- Resilience score
- Redundancy score
- Bottleneck index (top-5 impact concentration)
- Impact inequality (gini-like)
- Role entropy

How to use:
- High bottleneck + low redundancy means the deck is fragile and over-dependent on few cards.

## 5) Rules/Interaction Lens
- Oracle-text complexity flags
- Official rulings snippets
- Rule-query hints for deeper rules lookup

How to use:
- Review flagged cards to avoid sequencing errors and misunderstood replacements/triggers.
