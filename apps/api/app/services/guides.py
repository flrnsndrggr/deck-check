from __future__ import annotations

from typing import Dict


def _lines(items):
    return "\n".join(items) if items else "- none"


def _to_pct(v) -> str:
    try:
        return f"{float(v):.1%}"
    except Exception:
        return "n/a"


def _as_names(items, limit: int = 6):
    out = []
    for x in items or []:
        if isinstance(x, str) and x.strip():
            out.append(x.strip())
        if len(out) >= limit:
            break
    return out


def _fmt_cards(items, fallback: str = "key cards", limit: int = 4) -> str:
    names = _as_names(items, limit=limit)
    if not names:
        return fallback
    wrapped = [f"`{n}`" for n in names]
    if len(wrapped) == 1:
        return wrapped[0]
    if len(wrapped) == 2:
        return f"{wrapped[0]} and {wrapped[1]}"
    return ", ".join(wrapped[:-1]) + f", and {wrapped[-1]}"


def _fmt_variant(v: Dict, near_miss: bool = False) -> str:
    if not v:
        return "- none"
    vid = v.get("variant_id") or "unknown variant"
    present = _fmt_cards(v.get("present_cards", []), fallback="present pieces", limit=4)
    if near_miss:
        missing = _fmt_cards(v.get("missing_cards", []), fallback="missing piece(s)", limit=2)
        return f"- **{vid}**: present {present}; missing {missing}."
    return f"- **{vid}**: present {present}."


def _score_band(v: float, high: float = 0.55, medium: float = 0.4) -> str:
    if v >= high:
        return "strong"
    if v >= medium:
        return "medium"
    return "low"


def generate_guides(analyze: Dict, sim_summary: Dict) -> Dict[str, str]:
    p_4_mana_t3 = sim_summary.get("milestones", {}).get("p_mana4_t3", 0)
    p_5_mana_t4 = sim_summary.get("milestones", {}).get("p_mana5_t4", 0)
    median_commander = sim_summary.get("milestones", {}).get("median_commander_cast_turn", "N/A")

    combo_intel = analyze.get("combo_intel", {})
    intent = analyze.get("intent_summary", {})
    complete = combo_intel.get("matched_variants", [])
    near = combo_intel.get("near_miss_variants", [])
    failure = sim_summary.get("failure_modes", {})
    win = sim_summary.get("win_metrics", {})
    graph = sim_summary.get("graph_payloads", {})

    support_cards = _as_names(intent.get("key_support_cards", []), limit=8)
    engine_cards = _as_names(intent.get("key_engine_cards", []), limit=8)
    wincon_cards = _as_names(intent.get("main_wincon_cards", []), limit=8)
    interaction_cards = _as_names(intent.get("key_interaction_cards", []), limit=8)
    dead_cards = [x.get("card") for x in (graph.get("dead_cards_top") or []) if x.get("card")][:4]
    required_resources = _as_names(intent.get("required_resources", []), limit=5)

    role_gap_lines = [
        f"- {g.get('role')}: have {g.get('have')}, target {g.get('target')}, missing {g.get('missing')}"
        for g in analyze.get("missing_roles", [])[:8]
    ]
    action_lines = [f"- {a.get('title')}: {a.get('reason')}" for a in analyze.get("actionable_actions", [])[:8]]
    cut_lines = [f"- {c.get('card')}: {c.get('reason')}" for c in analyze.get("cuts", [])[:10]]
    add_lines = [f"- {a.get('card')}: fills {a.get('fills')} ({a.get('why')})" for a in analyze.get("adds", [])[:10]]
    swap_lines = [f"- Cut {s.get('cut')} -> Add {s.get('add')}: {s.get('reason')}" for s in analyze.get("swaps", [])[:10]]
    five_swap_lines = [f"- {s.get('cut')} -> {s.get('add')}" for s in analyze.get("swaps", [])[:5]]

    complete_lines = [_fmt_variant(v, near_miss=False) for v in complete[:5]]
    near_lines = [_fmt_variant(v, near_miss=True) for v in near[:5]]

    win_by_limit = float(win.get("p_win_by_turn_limit") or 0.0)
    win_band = _score_band(win_by_limit, high=0.7, medium=0.45)
    mana_band = _score_band(float(p_4_mana_t3 or 0.0), high=0.58, medium=0.48)
    action_band = _score_band(1.0 - float(failure.get("no_action") or 0.0), high=0.78, medium=0.66)

    optimization = f"""# OPTIMIZATION GUIDE

## Deck identity summary
- Primary plan: {intent.get('primary_plan', 'n/a')}
- Secondary plan: {intent.get('secondary_plan', 'n/a')}
- Combo support score: {combo_intel.get('combo_support_score', 0)}/100
- Complete combo lines: {len(complete)}
- Near-miss combo lines: {len(near)}

## Bracket compliance report
{analyze.get('bracket_report', {})}

## Role gaps and targets
{_lines(role_gap_lines)}

## Priority actions
{_lines(action_lines)}

## Cut list (max 10)
{_lines(cut_lines)}

## Add list (max 10)
{_lines(add_lines)}

## Swap shortlist
{_lines(swap_lines)}

## If you only change 5 cards
{_lines(five_swap_lines)}

## Evidence from simulations
In {sim_summary.get('runs', 0)} runs:
- P(4 mana by T3) = {p_4_mana_t3:.1%}
- P(5 mana by T4) = {p_5_mana_t4:.1%}
- Median commander cast turn = {median_commander}
"""

    play = f"""# COMMANDER PRIMER

## 1. At-a-Glance Plan
- **Primary plan:** {intent.get('primary_plan', 'n/a')}
- **Secondary plan:** {intent.get('secondary_plan', 'n/a')}
- **Main kill vectors:** {', '.join(intent.get('kill_vectors', [])) or 'n/a'}
- **Intent confidence:** {round(intent.get('confidence', 0.0) * 100, 1)}%
- **Performance snapshot:** mana pace is **{mana_band}**, early action reliability is **{action_band}**, and closing speed is **{win_band}**.

In plain language: this deck wants to open with setup ({_fmt_cards(support_cards, 'setup cards')}), transition into engines ({_fmt_cards(engine_cards, 'engine cards')}), and then close with {_fmt_cards(wincon_cards, 'finishers')}.

## 2. Simulation Snapshot (What Actually Happens)
Sample size: **{sim_summary.get('runs', 0)}** runs.

- **P(4 mana by T3):** {_to_pct(p_4_mana_t3)}
- **P(5 mana by T4):** {_to_pct(p_5_mana_t4)}
- **Median commander cast turn:** {median_commander}
- **P(win by turn limit):** {_to_pct(win_by_limit)}
- **Median win turn:** {win.get('median_win_turn', 'n/a')}
- **Most common win route:** {win.get('most_common_wincon') or 'n/a'}
- **Mana screw:** {_to_pct(failure.get('mana_screw', 0))}
- **No-action starts:** {_to_pct(failure.get('no_action', 0))}
- **Flood:** {_to_pct(failure.get('flood', 0))}

How to interpret:
- If P(4 mana by T3) is below ~55%, add early ramp/fixing before adding more finishers.
- If no-action starts are above ~28%, lower your curve and increase cheap setup density.
- If win-by-limit is low but setup is good, reinforce your main finish package rather than adding more generic value cards.

## 3. Deck Packages (With Concrete Card Examples)
### Setup and mana package
Primary setup cards in this list: {_fmt_cards(support_cards, 'setup cards')}.

### Engine package
Cards that usually turn your deck from setup into momentum: {_fmt_cards(engine_cards, 'engine cards')}.

### Win package
Cards most associated with closing lines: {_fmt_cards(wincon_cards, 'win cards')}.

### Interaction package
Cards to preserve tempo or protect your line: {_fmt_cards(interaction_cards, 'interaction cards')}.

### Resource checkpoints
{_lines([f"- {x}" for x in required_resources])}

## 4. Mulligan Framework (Practical, Not Theoretical)
Use London mulligan and evaluate hands with this sequence:
1. **Mana floor:** 2-5 lands, or a 1-land hand only if it includes acceleration + a castable setup card.
2. **Action test:** at least one early card from {_fmt_cards(support_cards, 'setup package')}.
3. **Plan test:** the hand should progress into engines ({_fmt_cards(engine_cards, 'engines')}) by turns 3-4.

Hands to ship more often:
- Hands that only function if you top-deck lands in sequence.
- Hands full of high-cost cards with no setup.
- Hands overloaded with cards that are frequently stranded, such as {_fmt_cards(dead_cards, 'your currently stranded cards')}.

## 5. Turn-by-Turn Sequencing Plan
### Turns 1-2 (stabilize)
1. Prioritize untapped/fixing sources and cast cheap setup from {_fmt_cards(support_cards, 'setup cards')}.
2. Favor acceleration lines that unlock turn-3 engine deployment.
3. Do not spend interaction early unless it protects your mana development.

### Turns 3-4 (convert setup into engine)
1. Deploy your first repeatable value piece ({_fmt_cards(engine_cards, 'engine cards')}).
2. Cast commander when it immediately improves your line quality.
3. If your hand is split between payoff and setup, choose setup first unless your win line is protected.

### Turns 5+ (close cleanly)
1. Commit to your best closing package ({_fmt_cards(wincon_cards, 'win cards')}).
2. Keep at least one interaction/protection slot from {_fmt_cards(interaction_cards, 'interaction cards')} when possible.
3. If a line stalls, pivot back into draw/tutor setup instead of forcing a low-probability finish.

## 6. Commander Deployment Rules
- Baseline from sims: commander median cast turn is **{median_commander}**.
- Cast commander early when hand contains immediate synergy follow-up.
- Hold commander when your hand needs one more setup turn to avoid tempo loss.
- If commander is removed repeatedly, rebuild with setup + engine first, then recast with protection.

## 7. Win Plan Map (Complete and Near-Miss Lines)
- **Complete combo lines detected:** {len(complete)}
- **Near-miss combo lines detected:** {len(near)}
- **Combo support score:** {combo_intel.get('combo_support_score', 0)}/100

Top complete lines:
{_lines(complete_lines)}

Top near-miss lines:
{_lines(near_lines)}

Pilot note:
- If complete lines exist, prioritize protecting those lines before adding new finishers.
- If near-miss lines dominate, prioritize one missing piece at a time and protect that package.

## 8. Pod Archetype Matchup Plans
### vs Fast Combo / Spellslinger Pods
- Mulligan for acceleration + early interaction ({_fmt_cards(interaction_cards, 'your cheapest interaction')}).
- Use tutors/draw to hit pressure plus one answer; do not keep purely slow value openers.
- Deploy commander only when it does not force shields-down into a known combo turn.

### vs Stax / Tax Pods
- Prioritize mana sources and low-cost setup ({_fmt_cards(support_cards, 'cheap setup cards')}) over greedy keepers.
- Sequence flexible removal for lock pieces, not random value permanents.
- Preserve engine cards that function through tax effects ({_fmt_cards(engine_cards, 'durable engines')}).

### vs Graveyard / Reanimator Pods
- Keep hands that can pressure while holding interaction.
- Save key answers for recursion enablers and payoff reanimation windows.
- If your plan is slower, pivot to consistent engines first and avoid racing from behind.

### vs Combat / Tokens Pods
- Stabilize board presence before attempting all-in payoff turns.
- Hold sweepers/interaction for critical overrun turns.
- Close quickly once stabilized instead of extending into another combat cycle.

### vs Draw-Go Control Pods
- Threat-layer with redundant engines ({_fmt_cards(engine_cards, 'engine cards')}) instead of jamming one fragile bomb.
- Force windows with end-step/value plays, then resolve your key payoff on low-shield turns.
- Keep pressure steady; avoid passing too many turns with no board progression.

## 9. Recovery Lines After Disruption
- After a wipe or key counterspell, re-establish mana and card flow before recommitting to payoff cards.
- Use {_fmt_cards(support_cards, 'setup cards')} to rebuild, then redeploy {_fmt_cards(engine_cards, 'engines')}.
- Avoid panic lines that spend your last tutor/card-selection effect on low-impact replacements.

## 10. Common Pilot Mistakes to Avoid
- Keeping speculative openers that do not cast meaningful spells by turn 2.
- Casting commander on curve when your setup line is objectively stronger.
- Firing tutors for flashy cards instead of the role your hand is missing.
- Overcommitting win pieces without protection from {_fmt_cards(interaction_cards, 'interaction support')}.

## 11. Pregame Pilot Checklist
1. Confirm your opening hand passes mana, action, and plan tests.
2. Decide your first two turns before keeping.
3. Identify your highest-probability win package for this pod.
4. Identify which opposing archetype is fastest and reserve one answer for it.
5. Re-evaluate line every turn based on mana + engine + protection state.

## 12. First Upgrade Moves (Highest Impact)
{_lines(action_lines[:6])}
"""
    return {"optimization_guide_md": optimization, "play_guide_md": play}
