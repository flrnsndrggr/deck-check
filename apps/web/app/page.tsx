"use client";

import { Fragment, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  AreaChart,
  Area,
  Legend,
} from "recharts";
import ReactMarkdown from "react-markdown";

const API = process.env.NEXT_PUBLIC_API_BASE || "";

const TABS = [
  "Deck Analysis",
  "Lenses",
  "Tagged Decklist",
  "Role Breakdown",
  "Mana Base",
  "Goldfish Report",
  "Fastet Wins",
  "Card Importance",
  "Optimization",
  "Primer",
  "Diagnostic",
] as const;

const METRIC_HELP: Record<
  string,
  { what: string; xAxis?: string; yAxis?: string; good: string; bad: string; change: string }
> = {
  mana_percentiles: {
    what: "Mana available by turn across all simulations using percentile bands.",
    xAxis: "Turn number (1, 2, 3...).",
    yAxis: "Total mana sources available that turn.",
    good: "By turn 3, p50 near 4+ is usually healthy for most mid-power decks.",
    bad: "If p50 is 3 or less on turn 3, early development is too slow.",
    change: "Add 1-2 mana ramp/fixing and trim expensive cards that do not stabilize.",
  },
  land_hit_cdf: {
    what: "Chance you are still on-curve for land drops each turn.",
    xAxis: "Turn number.",
    yAxis: "Probability (0 to 1).",
    good: "Around 70%+ on-curve by turn 3 is usually stable.",
    bad: "Dropping below ~60% by turn 3 often causes missed development.",
    change: "Increase land count, add draw/filter, and improve low-curve mulligan keeps.",
  },
  color_access: {
    what: "How quickly your deck reaches all colors in its commander color identity.",
    xAxis: "Turn number.",
    yAxis: "Average colors online, plus probability of full color identity access.",
    good: "For multicolor decks, full identity access rises quickly by early-mid game.",
    bad: "If full-identity access stays low, the deck suffers color screw.",
    change: "Add dual/fetch/fixing sources and trim color-intensive early costs.",
  },
  manabase_pip_distribution: {
    what: "Color demand from mana symbols across your deck, split by early/mid/late curve pressure.",
    xAxis: "Mana color.",
    yAxis: "Total pip demand (higher means more colored requirements).",
    good: "Main colors have enough matching sources and early pips are castable on curve.",
    bad: "A color has high pip demand but weak source coverage.",
    change: "Add that color's sources (prefer untapped/flexible lands) or trim early heavy-pip spells.",
  },
  manabase_source_coverage: {
    what: "How many cards produce each color, separated into lands vs nonland mana sources.",
    xAxis: "Mana color.",
    yAxis: "Source counts (plus weighted reliability view).",
    good: "Most required colors have strong land-source baselines with nonland support.",
    bad: "Color supply relies mostly on nonland mana or too few total land sources.",
    change: "Increase stable land sources for stressed colors before adding more greedy spells.",
  },
  manabase_balance_gap: {
    what: "Demand-vs-supply gap by color: compares pip share needed vs source share available.",
    xAxis: "Mana color.",
    yAxis: "Gap percentage points (negative = under-supplied).",
    good: "Gaps near zero; small positive/negative drift is normal.",
    bad: "Large negative gap means that color misses on time in many games.",
    change: "Fix the most negative color first; then re-run before making other deck changes.",
  },
  curve_histogram: {
    what: "Your mana curve split into permanents vs spells, with estimated chance each mana-value bucket is castable on curve.",
    xAxis: "Mana value bucket (0, 1, 2, ...).",
    yAxis: "Number of cards in each bucket.",
    good: "Curve is concentrated where your deck plan needs it, and on-curve odds stay high enough for those buckets.",
    bad: "Too many cards in expensive buckets with weak on-curve odds leads to dead early turns.",
    change: "Lower top-end density or add mana acceleration/fixing until key buckets are reliably castable.",
  },
  phase_timeline: {
    what: "Which phase your deck is in each turn: setup, engine, or win-attempt.",
    xAxis: "Turn number.",
    yAxis: "Share of games in that phase (stacked to 100%).",
    good: "Setup falls by turns 4-5 while engine/win-attempt shares rise.",
    bad: "Setup remains dominant into midgame, indicating stalled execution.",
    change: "Add early enablers and reduce cards that do not impact first 3 turns.",
  },
  win_turn_cdf: {
    what: "Cumulative probability the deck can present a win line by each turn.",
    xAxis: "Turn number.",
    yAxis: "Cumulative probability (0 to 1).",
    good: "Curve should match your pod speed expectations for that bracket.",
    bad: "Flat line into late turns means your close speed is too low.",
    change: "Increase line redundancy, tutors, or card flow into payoffs.",
  },
  no_action_funnel: {
    what: "How often a turn has zero meaningful spells cast.",
    xAxis: "Turn number.",
    yAxis: "Probability of no action.",
    good: "Low on turns 1-3 (typically <25-30%).",
    bad: "High early no-action rate means clunky starts.",
    change: "Lower curve, add setup cantrips/ramp, and mulligan more aggressively for action.",
  },
  dead_cards_top: {
    what: "Cards most frequently stranded in hand and not cast effectively.",
    xAxis: "Cards (top stranded list).",
    yAxis: "Rate of runs where card is stranded.",
    good: "No single card dominates stranded rate.",
    bad: "One cluster of cards repeatedly stranded indicates mismatch with mana/plan.",
    change: "Cut or downshift stranded cards; add ramp/fixing and role overlap.",
  },
  commander_cast_distribution: {
    what: "Distribution of commander cast timing across runs.",
    xAxis: "Turn commander is cast (or never).",
    yAxis: "Rate of games.",
    good: "Tight cluster around intended timing window for your strategy.",
    bad: "Very wide spread means inconsistent setup or mistuned policy.",
    change: "Fix early mana and adjust commander-priority policy.",
  },
  mulligan_funnel: {
    what: "How often hands are kept after 0, 1, or 2+ mulligans.",
    xAxis: "Number of mulligans taken.",
    yAxis: "Rate of games.",
    good: "Most keeps at 0-1 mulligans.",
    bad: "High 2+ mulligan rate indicates unreliable opener composition.",
    change: "Improve land/curve balance and increase cheap keepable cards.",
  },
  plan_progress: {
    what: "Composite plan-progress score over turns.",
    xAxis: "Turn number.",
    yAxis: "Plan progress score (higher is better).",
    good: "Median line rises steadily without long plateaus.",
    bad: "Flat early curve indicates stalled setup.",
    change: "Increase proactive turn-1/2 plays and consistency engines.",
  },
  failure_rates: {
    what: "Breakdown of major ways games fail to execute plan.",
    xAxis: "Failure mode type.",
    yAxis: "Percent of runs.",
    good: "All major failure modes are relatively low and balanced.",
    bad: "Any single mode dominating means a structural deck issue.",
    change: "Target fixes to dominant failure mode first (mana, curve, or action density).",
  },
  wincon_outcomes: {
    what: "Which win route appears most often in simulations.",
    xAxis: "Win condition type.",
    yAxis: "Percent of runs.",
    good: "Primary route is clear, backups exist.",
    bad: "No clear route or very low conversion rates.",
    change: "Increase support density for your main route and reduce off-plan cards.",
  },
  uncertainty: {
    what: "95% confidence interval around headline probabilities.",
    good: "Narrow intervals mean stable estimate.",
    bad: "Wide intervals mean not enough runs or highly volatile behavior.",
    change: "Increase simulation runs and improve consistency of early plays.",
  },
};

const HEALTH_HELP: Record<string, { good: string; bad: string; action: string }> = {
  mana_base_stability: {
    good: "Usually healthy at ~70+.",
    bad: "Below ~55 means mana consistency issues.",
    action: "Add lands/fixing/ramp and reduce expensive hands that do nothing early.",
  },
  early_game_reliability: {
    good: "Usually healthy at ~70+.",
    bad: "Below ~55 means too many slow/non-functional openers.",
    action: "Increase one- to two-mana setup cards and adjust mulligan approach.",
  },
  interaction_density: {
    good: "Enough answers to survive normal pods.",
    bad: "Low score means you may fold to fast engines/combos.",
    action: "Add efficient spot removal/stack interaction.",
  },
  game_plan_clarity: {
    good: "Primary route is clear with repeatable support.",
    bad: "Low means scattered plan and weak conversion to wins.",
    action: "Consolidate around one main route and support package.",
  },
  combo_support_level: {
    good: "Complete or near-complete lines are present and supported.",
    bad: "Low score means combo route is inconsistent or under-supported.",
    action: "Add missing pieces, tutors, and protection before adding new finishers.",
  },
  deck_consistency: {
    good: "Stable outcomes across many draws.",
    bad: "Large swing between good and bad games.",
    action: "Improve mana curve, redundancy, and early action density.",
  },
};

const SAMPLE = `Commander
1 Muldrotha, the Gravetide
Deck
1 Sol Ring
1 Arcane Signet
1 Command Tower
1 Evolving Wilds
1 Terramorphic Expanse
1 Sakura-Tribe Elder
1 Cultivate
1 Kodama's Reach
1 Farseek
1 Nature's Lore
1 Beast Within
1 Counterspell
1 Negate
1 Putrefy
1 Ravenous Chupacabra
1 Eternal Witness
1 Mulldrifter
1 Fact or Fiction
1 Rhystic Study
1 Mystic Remora
1 Baleful Strix
1 Llanowar Elves
1 Elvish Mystic
1 Birds of Paradise
1 Reclamation Sage
1 Acidic Slime
1 Animate Dead
1 Necromancy
1 Victimize
1 Living Death
1 Command Beacon
1 Breeding Pool
1 Overgrown Tomb
1 Watery Grave
1 Hinterland Harbor
1 Woodland Cemetery
1 Drowned Catacomb
1 Zagoth Triome
1 Flooded Grove
1 Twilight Mire
1 Sunken Ruins
1 Myriad Landscape
1 Reliquary Tower
1 Bojuka Bog
1 Ghost Quarter
1 Island
1 Island
1 Island
1 Island
1 Swamp
1 Swamp
1 Swamp
1 Swamp
1 Forest
1 Forest
1 Forest
1 Forest
1 Forest
1 Forest
1 Ponder
1 Preordain
1 Brainstorm
1 Mystic Confluence
1 Dig Through Time
1 Treasure Cruise
1 Season of Growth
1 Guardian Project
1 Beast Whisperer
1 Tireless Tracker
1 Ramunap Excavator
1 Splendid Reclamation
1 Pernicious Deed
1 Toxic Deluge
1 Damnation
1 Cyclonic Rift
1 Arcane Denial
1 Disallow
1 Reality Shift
1 Pongify
1 Rapid Hybridization
1 Seal of Primordium
1 Seal of Removal
1 Siren Stormtamer
1 Fauna Shaman
1 Survival of the Fittest
1 Buried Alive
1 Entomb
1 Life from the Loam
1 Satyr Wayfinder
1 Stitcher's Supplier
1 Grisly Salvage
1 Deadbridge Chant
1 Commander's Sphere
1 Fellwar Stone
1 Thought Vessel
1 Dimir Signet
1 Golgari Signet
1 Simic Signet
1 Reanimate
1 Animate Dead
`;

export default function HomePage() {
  const [decklist, setDecklist] = useState(SAMPLE);
  const [moxfieldUrl, setMoxfieldUrl] = useState("");
  const [tab, setTab] = useState<(typeof TABS)[number]>("Deck Analysis");
  const [bracket, setBracket] = useState(3);
  const [policy, setPolicy] = useState("auto");
  const [simRuns, setSimRuns] = useState(2000);
  const [turnLimit, setTurnLimit] = useState(8);
  const [tablePressure, setTablePressure] = useState(30);
  const [mulliganAggression, setMulliganAggression] = useState(50);
  const [commanderPriority, setCommanderPriority] = useState(50);
  const [budgetMaxUsd, setBudgetMaxUsd] = useState<number | "">("");
  const [detectedWincons, setDetectedWincons] = useState<string[]>([]);
  const [status, setStatus] = useState("idle");

  const [parseRes, setParseRes] = useState<any>(null);
  const [tagRes, setTagRes] = useState<any>(null);
  const [simRes, setSimRes] = useState<any>(null);
  const [analysis, setAnalysis] = useState<any>(null);
  const [guides, setGuides] = useState<any>(null);
  const [displayMap, setDisplayMap] = useState<Record<string, any>>({});
  const [selectedCard, setSelectedCard] = useState<string | null>(null);
  const [selectedCurveMv, setSelectedCurveMv] = useState<number | null>(null);
  const [updatesMeta, setUpdatesMeta] = useState<any>(null);
  const [integrationsMeta, setIntegrationsMeta] = useState<any>(null);
  const [strictlyBetter, setStrictlyBetter] = useState<any[]>([]);
  const [strictlyBetterLoading, setStrictlyBetterLoading] = useState(false);
  const [expandedRoles, setExpandedRoles] = useState<Record<string, boolean>>({});

  const detailOpen = true;

  const chartData = useMemo(() => {
    const progress = simRes?.summary?.plan_progress || {};
    return Object.entries(progress).map(([turn, v]: any) => ({ turn: Number(turn), median: v.median, p90: v.p90 }));
  }, [simRes]);
  const failureData = useMemo(() => {
    const fm = simRes?.summary?.failure_modes || {};
    return [
      { name: "Mana screw", value: num(fm.mana_screw) * 100 },
      { name: "No action", value: num(fm.no_action) * 100 },
      { name: "Flood", value: num(fm.flood) * 100 },
    ];
  }, [simRes]);
  const winconData = useMemo(() => {
    const dist = simRes?.summary?.win_metrics?.wincon_distribution || {};
    return Object.entries(dist).map(([name, v]: any) => ({ name, value: num(v) * 100 }));
  }, [simRes]);
  const parsedCount = useMemo(
    () => (parseRes?.cards || []).filter((c: any) => c.section === "deck" || c.section === "commander").reduce((s: number, c: any) => s + (c.qty || 0), 0),
    [parseRes]
  );
  const topImportance = (analysis?.importance || []).slice(0, 10);
  const importanceChartData = useMemo(
    () => (analysis?.importance || []).slice(0, 10).map((c: any) => ({ card: c.card, score: Number(c.score || 0) })),
    [analysis]
  );
  const topCuts = (analysis?.cuts || []).slice(0, 3);
  const topAdds = (analysis?.adds || []).slice(0, 3);
  const roleGaps = (analysis?.missing_roles || []).slice(0, 4);
  const bracketViolations = analysis?.bracket_report?.violations || [];
  const winMetrics = simRes?.summary?.win_metrics || {};
  const uncertainty = simRes?.summary?.uncertainty || {};
  const fastestWins = simRes?.summary?.fastest_wins || [];
  const comboIntel = analysis?.combo_intel || {};
  const comboNearMiss = comboIntel?.near_miss_variants || [];
  const intentSummary = analysis?.intent_summary || {};
  const graphPayloads = analysis?.graph_payloads || simRes?.summary?.graph_payloads || {};
  const graphExplain = analysis?.graph_explanations || {};
  const graphBlurb = analysis?.graph_deck_blurbs || {};
  const manabase = analysis?.manabase_analysis || {};
  const manabaseRows = manabase?.rows || [];
  const manabaseSummary = manabase?.summary || {};
  const manabaseTopPipCards = manabase?.top_pip_cards || [];
  const curveData = manabase?.curve?.histogram || [];
  const curveCardsByMv = manabase?.curve?.cards_by_mv || {};
  const activeCurveMv = selectedCurveMv != null
    ? selectedCurveMv
    : (curveData?.length ? Number(curveData.reduce((best: any, row: any) => (Number(row?.total || 0) > Number(best?.total || 0) ? row : best), curveData[0])?.mana_value || 0) : null);
  const activeCurveRow = activeCurveMv != null ? curveData.find((x: any) => Number(x.mana_value) === Number(activeCurveMv)) : null;
  const selectedCurveCards = activeCurveMv != null ? (curveCardsByMv?.[String(activeCurveMv)] || []) : [];
  const roleTargets = analysis?.role_targets || {};
  const roleCardsMap = analysis?.role_cards_map || {};
  const roleTargetModel = analysis?.role_target_model || {};
  const colorProfile = analysis?.color_profile || {};
  const colorIdentity = colorProfile?.color_identity || parseRes?.color_identity || tagRes?.color_identity || [];
  const colorIdentitySize = Number(colorProfile?.color_identity_size ?? parseRes?.color_identity_size ?? tagRes?.color_identity_size ?? 0);
  const selectedImportance = (analysis?.importance || []).find((x: any) => x.card === selectedCard);
  const selectedImpact = selectedCard ? (simRes?.summary?.card_impacts || {})[selectedCard] : null;
  const findings = useMemo(() => {
    const out: string[] = [];
    if (num(simRes?.summary?.milestones?.p_mana4_t3) < 0.5) out.push("Early mana development is below target; add low-cost ramp/fixing.");
    if (num(simRes?.summary?.failure_modes?.mana_screw) > 0.22) out.push("Mana screw appears frequently; review land count and source balance.");
    if (num(simRes?.summary?.failure_modes?.no_action) > 0.28) out.push("Too many openers do nothing early; shift curve lower or add setup.");
    if ((analysis?.missing_roles || []).length > 0) out.push(`Role gaps detected: ${(analysis?.missing_roles || []).slice(0, 3).map((g: any) => g.role).join(", ")}.`);
    if (!out.length) out.push("Core goldfish metrics look stable for the chosen policy and bracket.");
    return out;
  }, [simRes, analysis]);

  const roleRows = useMemo(() => {
    const roleCounts = analysis?.role_breakdown?.roles || {};
    const targetEntries = Object.entries(roleTargets || {}).map(([role, meta]: any) => {
      const have = Number(roleCounts?.[role] || 0);
      const minTarget = Number(meta?.min ?? 0);
      const center = Number(meta?.target ?? minTarget);
      const maxTarget = Number(meta?.max ?? center);
      let status = "on_track";
      if (have < minTarget) status = "below";
      else if (have > maxTarget) status = "above";
      return {
        role,
        have,
        minTarget,
        center,
        maxTarget,
        status,
        reason: meta?.reason || "",
        cards: roleCardsMap?.[role] || [],
      };
    });
    const noTargetRows = Object.entries(roleCounts || {})
      .filter(([role]) => !roleTargets?.[role])
      .map(([role, count]: any) => ({
        role,
        have: Number(count || 0),
        minTarget: 0,
        center: 0,
        maxTarget: 0,
        status: "untargeted",
        reason: "Auxiliary tag, tracked for context rather than strict quotas.",
        cards: roleCardsMap?.[role] || [],
      }));
    return [...targetEntries, ...noTargetRows].sort((a, b) => {
      const critical = { below: 0, on_track: 1, above: 2, untargeted: 3 } as Record<string, number>;
      const sa = critical[a.status] ?? 9;
      const sb = critical[b.status] ?? 9;
      if (sa !== sb) return sa - sb;
      return a.role.localeCompare(b.role);
    });
  }, [analysis, roleTargets, roleCardsMap]);

  function pct(v: unknown) {
    const n = typeof v === "number" ? v : 0;
    return `${(n * 100).toFixed(1)}%`;
  }

  function ciLabel(ci: any) {
    if (!ci || typeof ci.low !== "number" || typeof ci.high !== "number") return "n/a";
    return `${(ci.low * 100).toFixed(1)}%-${(ci.high * 100).toFixed(1)}%`;
  }

  function ciWidth(ci: any) {
    if (!ci || typeof ci.low !== "number" || typeof ci.high !== "number") return null;
    return Math.max(0, ci.high - ci.low);
  }

  function ciQuality(ci: any) {
    const w = ciWidth(ci);
    if (w == null) return "unknown";
    if (w <= 0.02) return "tight";
    if (w <= 0.05) return "moderate";
    return "wide";
  }

  function num(v: unknown) {
    return typeof v === "number" ? v : 0;
  }

  function cardDisplay(name: string) {
    return displayMap[name] || {};
  }

  function cardThumb(name: string) {
    return cardDisplay(name)?.small || cardDisplay(name)?.normal || "";
  }

  function toggleRole(role: string) {
    setExpandedRoles((prev) => ({ ...prev, [role]: !prev[role] }));
  }

  function renderMetricHelp(metricKey: string) {
    const m = METRIC_HELP[metricKey];
    if (!m) return null;
    return (
      <div className="metric-help">
        <div><strong>What this shows:</strong> {m.what}</div>
        {m.xAxis ? <div><strong>X-axis:</strong> {m.xAxis}</div> : null}
        {m.yAxis ? <div><strong>Y-axis:</strong> {m.yAxis}</div> : null}
        <div><strong>Good:</strong> {m.good}</div>
        <div><strong>Warning/Bad:</strong> {m.bad}</div>
        <div><strong>What to change:</strong> {m.change}</div>
      </div>
    );
  }

  function renderDeckBlurb(metricKey: string) {
    const text = graphBlurb?.[metricKey];
    if (!text) return null;
    return <p className="deck-blurb">{text}</p>;
  }

  function renderCardChip(name: string, key: string) {
    return (
      <button key={key} className="btn card-chip" onClick={() => setSelectedCard(name)}>
        {cardThumb(name) ? (
          <img src={cardThumb(name)} alt={name} width={24} height={34} loading="lazy" style={{ borderRadius: 4, border: "1px solid #ddd" }} />
        ) : (
          <span style={{ width: 24, height: 34, display: "inline-block", borderRadius: 4, background: "#efefef", border: "1px solid #ddd" }} />
        )}
        <span>{name}</span>
      </button>
    );
  }

  function updateStatus(next: string) {
    setStatus(next);
  }

  async function hydrateDisplay(names: string[]) {
    const toFetch = names.filter((n) => n && !displayMap[n]);
    if (!toFetch.length) return;
    try {
      const q = encodeURIComponent(toFetch.join(","));
      const res = await fetch(`${API}/api/cards/display?names=${q}`);
      if (!res.ok) return;
      const payload = await res.json();
      setDisplayMap((prev) => ({ ...prev, ...(payload.cards || {}) }));
    } catch {
      return;
    }
  }

  function computeEffectivePolicy(): string {
    if (policy !== "auto") return policy;
    if (commanderPriority >= 70) return "commander-centric";
    if (commanderPriority <= 30) return "hold commander";

    const base = bracket >= 5 ? "cedh" : bracket <= 2 ? "casual" : "optimized";
    if (base === "optimized") {
      if (mulliganAggression >= 70) return "cedh";
      if (mulliganAggression <= 30) return "casual";
    }
    return base;
  }

  function inferWinconsFromTagged(tagPayload: any): string[] {
    const tags = new Set<string>();
    for (const c of tagPayload?.cards || []) {
      for (const t of c.tags || []) tags.add(String(t));
    }
    const arch = tagPayload?.archetype_weights || {};
    const out: string[] = [];

    if (tags.has("#Combo") || num(arch.combo) >= 0.55) out.push("Combo");
    if (tags.has("#Voltron") || tags.has("#Wincon")) out.push("Commander Damage");
    if (tags.has("#Control") || tags.has("#Counter") || num(arch.control) >= 0.55) out.push("Control Lock");
    if (tags.has("#Wincon") && !out.includes("Combo")) out.push("Alt Win");
    if (!out.length || tags.has("#Tokens") || tags.has("#Payoff")) out.push("Combat");

    return Array.from(new Set(out));
  }

  async function importFromUrl() {
    if (!moxfieldUrl.trim()) return;
    try {
      updateStatus("importing");
      const imported = await fetch(`${API}/api/decks/import-url`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: moxfieldUrl.trim() }),
      });
      if (!imported.ok) {
        const detail = await imported.text();
        throw new Error(detail || "URL import failed");
      }
      const payload = await imported.json();
      setDecklist(payload.decklist_text);
      if (payload.warnings?.length) {
        alert(`Imported with warnings:\n${payload.warnings.join("\n")}`);
      }
    } catch {
      alert("URL import failed. Paste text export instead.");
    } finally {
      updateStatus("idle");
    }
  }

  async function runPipeline() {
    try {
      updateStatus("parsing");
      const parsed = await fetch(`${API}/api/decks/parse`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decklist_text: decklist, bracket, multiplayer: true }),
      }).then((r) => r.json());
      setParseRes(parsed);

      updateStatus("tagging");
      const tagged = await fetch(`${API}/api/decks/tag`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cards: parsed.cards, commander: parsed.commander, global_tags: true }),
      }).then((r) => r.json());
      setTagRes(tagged);
      setDisplayMap(tagged.card_display || {});
      const inferredWincons = inferWinconsFromTagged(tagged);
      setDetectedWincons(inferredWincons);

      updateStatus("sim-queued");
      const effectivePolicy = computeEffectivePolicy();
      const simJob = await fetch(`${API}/api/sim/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          cards: tagged.cards,
          commander: parsed.commander,
          runs: simRuns,
          turn_limit: turnLimit,
          policy: effectivePolicy,
          bracket,
          multiplayer: true,
          threat_model: tablePressure >= 40,
          primary_wincons: inferredWincons,
          sim_backend: "vectorized",
          batch_size: 512,
          seed: 42,
        }),
      }).then((r) => r.json());

      let simStatus = "queued";
      let simPayload: any = null;
      while (!["done", "failed"].includes(simStatus)) {
        await new Promise((r) => setTimeout(r, 1000));
        const polled = await fetch(`${API}/api/sim/${simJob.job_id}`).then((r) => r.json());
        simStatus = polled.status;
        simPayload = polled.result;
        updateStatus(`sim-${simStatus}`);
      }
      if (simStatus === "failed") {
        updateStatus("failed");
        throw new Error(simPayload?.error || "Simulation failed");
      }
      setSimRes(simPayload);

      updateStatus("analyzing");
      const ana = await fetch(`${API}/api/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          cards: tagged.cards,
          commander: parsed.commander,
          bracket,
          template: "balanced",
          budget_max_usd: budgetMaxUsd === "" ? null : Number(budgetMaxUsd),
          sim_summary: simPayload.summary,
        }),
      }).then((r) => r.json());
      setAnalysis(ana);

      updateStatus("guides");
      const gd = await fetch(`${API}/api/guides/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ analyze: ana, sim_summary: simPayload.summary }),
      }).then((r) => r.json());
      setGuides(gd);
      const bracketCriteriaCards = (ana?.bracket_report?.criteria || [])
        .flatMap((c: any) => (c?.cards || []).map((x: any) => x?.name))
        .filter((n: any) => typeof n === "string" && n.length > 0);
      const manabaseSourceCards = (ana?.manabase_analysis?.rows || [])
        .flatMap((r: any) => (r?.top_sources || []).map((x: any) => x?.name))
        .filter((n: any) => typeof n === "string" && n.length > 0);
      const manabaseDemandCards = (ana?.manabase_analysis?.top_pip_cards || [])
        .map((x: any) => x?.card)
        .filter((n: any) => typeof n === "string" && n.length > 0);
      const curveCards = Object.values(ana?.manabase_analysis?.curve?.cards_by_mv || {})
        .flatMap((arr: any) => (Array.isArray(arr) ? arr.map((x: any) => x?.card) : []))
        .filter((n: any) => typeof n === "string" && n.length > 0);
      const fastestWinCards = (simPayload?.summary?.fastest_wins || [])
        .flatMap((w: any) => [
          ...(w?.opening_hand || []),
          ...(w?.mulligan_steps || []).flatMap((s: any) => [...(s?.hand || []), ...(s?.kept_hand || [])]),
          ...(w?.turns || []).flatMap((t: any) => [t?.draw, t?.land, ...(t?.casts || [])]),
        ])
        .filter((n: any) => typeof n === "string" && n.length > 0);
      await hydrateDisplay([
        ...(ana?.importance || []).slice(0, 20).map((x: any) => x.card),
        ...(ana?.adds || []).slice(0, 20).map((x: any) => x.card),
        ...(ana?.cuts || []).slice(0, 20).map((x: any) => x.card),
        ...bracketCriteriaCards,
        ...manabaseSourceCards,
        ...manabaseDemandCards,
        ...curveCards,
        ...fastestWinCards,
      ]);

      setTab("Deck Analysis");
      updateStatus("done");
    } catch (err: any) {
      updateStatus("failed");
      alert(err?.message || "Run failed");
    }
  }

  useEffect(() => {
    if (!selectedCard) return;
    void hydrateDisplay([selectedCard]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCard]);

  useEffect(() => {
    setExpandedRoles({});
    setSelectedCurveMv(null);
  }, [analysis]);

  useEffect(() => {
    if (!selectedCard || !(tagRes?.cards || []).length) {
      setStrictlyBetter([]);
      return;
    }
    void (async () => {
      setStrictlyBetterLoading(true);
      try {
        const res = await fetch(`${API}/api/cards/strictly-better`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            cards: tagRes.cards,
            selected_card: selectedCard,
            commander: parseRes?.commander,
            budget_max_usd: budgetMaxUsd === "" ? null : Number(budgetMaxUsd),
          }),
        });
        if (!res.ok) {
          setStrictlyBetter([]);
          return;
        }
        const payload = await res.json();
        setStrictlyBetter(payload.options || []);
        await hydrateDisplay((payload.options || []).map((o: any) => o.card));
      } catch {
        setStrictlyBetter([]);
      } finally {
        setStrictlyBetterLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCard, tagRes, parseRes?.commander, budgetMaxUsd]);

  useEffect(() => {
    void (async () => {
      try {
        const res = await fetch(`${API}/api/meta/updates`);
        if (!res.ok) return;
        const payload = await res.json();
        setUpdatesMeta(payload);
      } catch {
        return;
      }
    })();

    void (async () => {
      try {
        const res = await fetch(`${API}/api/meta/integrations`);
        if (!res.ok) return;
        const payload = await res.json();
        setIntegrationsMeta(payload);
      } catch {
        return;
      }
    })();
  }, []);

  return (
    <div className={`ui-shell ${detailOpen ? "detail-open" : ""}`}>
      <aside className="ui-sidebar">
        <div className="stack">
          <h2 className="wordmark" aria-label="Deck.Check">
            <span className="wordmark-glyph">D</span>
            <span className="wordmark-text">
              Deck<span className="wordmark-dot">.</span>Check
            </span>
          </h2>
          <p className="muted">Bracket-aware parser, tags, goldfish, and optimization.</p>
          <p className="control-help">
            Rules/data refresh: {updatesMeta?.sources?.[0]?.last_fetched_at ? new Date(updatesMeta.sources[0].last_fetched_at).toLocaleString() : "not fetched yet"}
          </p>
        </div>

        <div className="block stack">
          <label>Deck URL (best effort)</label>
          <input className="input" value={moxfieldUrl} onChange={(e) => setMoxfieldUrl(e.target.value)} placeholder="Moxfield or Archidekt URL" />
          <button className="btn" onClick={importFromUrl}>Import URL</button>
          <p className="control-help">URL import is best-effort. If blocked, paste the text export directly.</p>
        </div>

        <div className="block stack">
          <label>Bracket</label>
          <select className="select" value={bracket} onChange={(e) => setBracket(Number(e.target.value))}>
            {[1, 2, 3, 4, 5].map((b) => (
              <option key={b} value={b}>{b}</option>
            ))}
          </select>

          <label>Policy</label>
          <select className="select" value={policy} onChange={(e) => setPolicy(e.target.value)}>
            <option value="auto">Auto</option>
            <option value="casual">Casual value</option>
            <option value="optimized">Optimized mid-power</option>
            <option value="cedh">cEDH-like speed</option>
            <option value="commander-centric">Commander-centric</option>
            <option value="hold commander">Hold commander</option>
          </select>
          <p className="control-help">
            If set to Auto, mulligan aggression and commander priority sliders determine the effective policy for the run.
            Effective now: <strong>{computeEffectivePolicy()}</strong>.
          </p>

          <label>Simulation Runs: {simRuns}</label>
          <p className="control-help">How many goldfish games to run. Higher gives more stable percentages, but takes longer.</p>
          <input
            className="slider"
            type="range"
            min={500}
            max={10000}
            step={500}
            value={simRuns}
            onChange={(e) => setSimRuns(Number(e.target.value))}
          />

          <label>Turn Limit: {turnLimit}</label>
          <p className="control-help">How many turns each simulation plays. Raise this for slower decks that stabilize late.</p>
          <input
            className="slider"
            type="range"
            min={5}
            max={14}
            step={1}
            value={turnLimit}
            onChange={(e) => setTurnLimit(Number(e.target.value))}
          />

          <label>Table Pressure: {tablePressure}%</label>
          <p className="control-help">How often we assume opponents present must-answer threats. At 40%+, interaction gets used more actively.</p>
          <input
            className="slider"
            type="range"
            min={0}
            max={100}
            step={10}
            value={tablePressure}
            onChange={(e) => setTablePressure(Number(e.target.value))}
          />

          <label>Mulligan Aggression: {mulliganAggression}%</label>
          <p className="control-help">Higher means greedier keeps for speed; lower means safer keeps for consistency (used in Auto policy).</p>
          <input
            className="slider"
            type="range"
            min={0}
            max={100}
            step={10}
            value={mulliganAggression}
            onChange={(e) => setMulliganAggression(Number(e.target.value))}
          />

          <label>Commander Priority: {commanderPriority}%</label>
          <p className="control-help">Higher casts commander earlier; lower holds commander until setup is established (used in Auto policy).</p>
          <input
            className="slider"
            type="range"
            min={0}
            max={100}
            step={10}
            value={commanderPriority}
            onChange={(e) => setCommanderPriority(Number(e.target.value))}
          />

          <label>Budget Cap (USD/card)</label>
          <p className="control-help">Optional max price per suggested add. Leave empty for no budget filter.</p>
          <input
            className="input"
            type="number"
            min={0}
            step={1}
            value={budgetMaxUsd}
            onChange={(e) => setBudgetMaxUsd(e.target.value === "" ? "" : Number(e.target.value))}
            placeholder="e.g. 10"
          />

          <button className="btn btn-primary" onClick={runPipeline}>Run Full Analysis</button>
        </div>

        <div className="legal-links control-help">
          <Link href="/imprint">Imprint</Link>
          <span>•</span>
          <Link href="/privacy">Privacy</Link>
        </div>

      </aside>

      <section className="ui-detail">
        <div className="stack">
          <h3>Decklist</h3>
          <div className="block stack">
            <div className="kpi-grid">
              <div className="mini-card">
                <div className="mini-label">Commander</div>
                <div className="mini-value">{parseRes?.commander || "n/a"}</div>
              </div>
              <div className="mini-card">
                <div className="mini-label">Card Count</div>
                <div className={`mini-value ${parsedCount === 100 ? "tone-good" : "tone-warn"}`}>{parsedCount || "n/a"}</div>
              </div>
              <div className="mini-card">
                <div className="mini-label">Validation</div>
                <div className={`mini-value ${(parseRes?.errors || []).length === 0 ? "tone-good" : "tone-bad"}`}>
                  {(parseRes?.errors || []).length === 0 ? "No blocking errors" : `${(parseRes?.errors || []).length} blocking issues`}
                </div>
              </div>
              <div className="mini-card">
                <div className="mini-label">Auto Win Plans</div>
                <div className="mini-value">{detectedWincons.length ? detectedWincons.join(", ") : "n/a"}</div>
              </div>
              <div className="mini-card">
                <div className="mini-label">Color Identity</div>
                <div className="mini-value">
                  {colorIdentitySize === 0 ? "Colorless" : (colorIdentity.join("") || "n/a")}
                </div>
              </div>
            </div>
            <textarea className="textarea" value={decklist} onChange={(e) => setDecklist(e.target.value)} />

            {(tagRes?.cards || []).length > 0 && (
              <div>
                <strong>Card Preview</strong>
                <table className="table" style={{ marginTop: 6 }}>
                  <thead>
                    <tr><th>Card</th><th>Role hint</th></tr>
                  </thead>
                  <tbody>
                    {(tagRes?.cards || []).slice(0, 14).map((c: any, i: number) => (
                      <tr key={`${c.name}-${i}`} onClick={() => setSelectedCard(c.name)} style={{ cursor: "pointer" }}>
                        <td style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          {cardThumb(c.name) ? (
                            <img src={cardThumb(c.name)} alt={c.name} width={30} height={42} loading="lazy" style={{ borderRadius: 4, border: "1px solid #ddd" }} />
                          ) : (
                            <div style={{ width: 30, height: 42, borderRadius: 4, background: "#efefef", border: "1px solid #ddd" }} />
                          )}
                          <span>{c.name}</span>
                        </td>
                        <td>{(c.tags || []).slice(0, 2).join(", ") || "n/a"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {(parseRes?.errors || []).length > 0 && (
              <div>
                <strong>Blocking Errors</strong>
                <ul className="list-compact">
                  {(parseRes?.errors || []).map((e: string, i: number) => <li key={i}>{e}</li>)}
                </ul>
              </div>
            )}

            {bracketViolations.length > 0 && (
              <div>
                <strong>Bracket Issues</strong>
                <ul className="list-compact">
                  {bracketViolations.map((e: string, i: number) => <li key={i}>{e}</li>)}
                </ul>
              </div>
            )}
          </div>
        </div>
      </section>

      <main className={`ui-main ${selectedCard ? "insight-open" : ""}`}>
        <div className="outcome-shell">
          <div className="outcome-content">
        <div className="stack" style={{ marginBottom: 12 }}>
          <h3>{tab}</h3>
          <p className="muted">Outcomes and findings for the selected run. Status: {status}</p>
          <div className="tab-list" style={{ marginTop: 4, display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 6 }}>
            {TABS.map((t) => (
              <button key={t} className={`btn tab-btn ${tab === t ? "active" : ""}`} onClick={() => setTab(t)}>{t}</button>
            ))}
          </div>
        </div>

        <div className="block">
          {tab === "Deck Analysis" && (
            <div className="guide-rendered">
              <h2>Key Findings</h2>
              <ul>
                {findings.map((f, i) => <li key={i}>{f}</li>)}
              </ul>

              <h2>Deck Health Summary</h2>
              <div className="kpi-grid">
                {Object.entries(analysis?.health_summary || {}).map(([k, v]: any) => (
                  <div className="mini-card" key={k}>
                    <div className="mini-label">{k.replaceAll("_", " ")}</div>
                    <div className={`mini-value ${v?.status === "healthy" ? "tone-good" : v?.status === "warning" ? "tone-warn" : "tone-bad"}`}>
                      {v?.score ?? "n/a"} ({v?.status || "n/a"})
                    </div>
                    <div className="control-help">{v?.explanation || ""}</div>
                    <div className="control-help"><strong>Good:</strong> {HEALTH_HELP[k]?.good || "Higher is better."}</div>
                    <div className="control-help"><strong>Bad:</strong> {HEALTH_HELP[k]?.bad || "Lower scores indicate structural weakness."}</div>
                    <div className="control-help"><strong>Fix:</strong> {HEALTH_HELP[k]?.action || "Tune cards supporting early consistency."}</div>
                  </div>
                ))}
              </div>
              <ul className="list-compact">
                <li><strong>Resilience:</strong> good around 70+, warning below 55.</li>
                <li><strong>Redundancy:</strong> good around 60+, low means too much dependence on a few cards.</li>
                <li><strong>Bottleneck index:</strong> lower is better; very high means fragile core dependency.</li>
                <li><strong>Role entropy:</strong> very low can mean one-dimensional plan; very high can mean lack of focus.</li>
              </ul>
              <p><strong>Consistency Score:</strong> {analysis?.consistency_score ?? "n/a"} / 100</p>

              <h2>Complex Systems Lens</h2>
              <div className="kpi-grid">
                <div className="mini-card">
                  <div className="mini-label">Resilience</div>
                  <div className="mini-value">{analysis?.systems_metrics?.resilience_score ?? "n/a"}</div>
                  <div className="control-help">{analysis?.systems_metrics?.interpretation?.resilience_score}</div>
                </div>
                <div className="mini-card">
                  <div className="mini-label">Redundancy</div>
                  <div className="mini-value">{analysis?.systems_metrics?.redundancy_score ?? "n/a"}</div>
                  <div className="control-help">{analysis?.systems_metrics?.interpretation?.redundancy_score}</div>
                </div>
                <div className="mini-card">
                  <div className="mini-label">Bottleneck Index</div>
                  <div className="mini-value">{analysis?.systems_metrics?.bottleneck_index ?? "n/a"}</div>
                  <div className="control-help">{analysis?.systems_metrics?.interpretation?.bottleneck_index}</div>
                </div>
                <div className="mini-card">
                  <div className="mini-label">Role Entropy</div>
                  <div className="mini-value">{analysis?.systems_metrics?.role_entropy_bits ?? "n/a"} bits</div>
                  <div className="control-help">{analysis?.systems_metrics?.interpretation?.role_entropy_bits}</div>
                </div>
              </div>

              <h2>Tagging Diagnostics</h2>
              <ul>
                <li>Untagged cards: {analysis?.tag_diagnostics?.untagged_count ?? 0}</li>
                <li>Potentially over-tagged cards: {analysis?.tag_diagnostics?.overloaded_count ?? 0}</li>
                <li>Multi-role cards: {analysis?.tag_diagnostics?.multi_role_count ?? 0}</li>
              </ul>
              <p className="muted">This helps challenge the tagging system and identify where manual overrides or tighter regex rules are needed.</p>

              <h2>Deck Identity</h2>
              <p>
                <strong>Commander:</strong> {parseRes?.commander || "n/a"}
              </p>
              <p>
                <strong>Color identity:</strong>{" "}
                {colorIdentitySize === 0 ? "Colorless" : `${colorIdentity.join("")} (${colorIdentitySize} color${colorIdentitySize > 1 ? "s" : ""})`}
              </p>
              <p className="control-help">
                Recommendations are constrained to this commander color identity.
              </p>
              <p>
                <strong>Primary Win Plan (auto-detected):</strong> {detectedWincons.length ? detectedWincons.join(", ") : "n/a"}
              </p>
              <p>
                <strong>Likely Archetype Signals:</strong>{" "}
                {Object.entries(tagRes?.archetype_weights || {})
                  .sort((a: any, b: any) => b[1] - a[1])
                  .slice(0, 3)
                  .map(([k, v]: any) => `${k} (${(v * 100).toFixed(0)}%)`)
                  .join(", ") || "n/a"}
              </p>

              <h2>Deck Intent</h2>
              <p><strong>Primary plan:</strong> {intentSummary?.primary_plan || "n/a"}</p>
              <p><strong>Secondary plan:</strong> {intentSummary?.secondary_plan || "n/a"}</p>
              <p><strong>Main kill vectors:</strong> {(intentSummary?.kill_vectors || []).join(", ") || "n/a"}</p>
              <p><strong>Confidence:</strong> {typeof intentSummary?.confidence === "number" ? `${(intentSummary.confidence * 100).toFixed(1)}%` : "n/a"}</p>
              <p><strong>Combo support score:</strong> {comboIntel?.combo_support_score ?? 0} / 100</p>
              {comboIntel?.fetched_at ? <p className="control-help">CommanderSpellbook fetched: {new Date(comboIntel.fetched_at).toLocaleString()}</p> : null}

              <h3>Key Support Cards</h3>
              <ul>
                {(intentSummary?.key_support_cards || []).slice(0, 8).map((name: string, i: number) => (
                  <li key={`support-${i}`}>
                    <button className="btn" onClick={() => setSelectedCard(name)}>{name}</button>
                  </li>
                ))}
              </ul>

              <h3>Engine Cards</h3>
              <ul>
                {(intentSummary?.key_engine_cards || []).slice(0, 8).map((name: string, i: number) => (
                  <li key={`engine-${i}`}>
                    <button className="btn" onClick={() => setSelectedCard(name)}>{name}</button>
                  </li>
                ))}
              </ul>

              <h3>Main Wincons</h3>
              <ul>
                {(intentSummary?.main_wincon_cards || []).slice(0, 8).map((name: string, i: number) => (
                  <li key={`wincon-${i}`}>
                    <button className="btn" onClick={() => setSelectedCard(name)}>{name}</button>
                  </li>
                ))}
              </ul>

              <h3>Key Interaction</h3>
              <ul>
                {(intentSummary?.key_interaction_cards || []).slice(0, 8).map((name: string, i: number) => (
                  <li key={`interaction-${i}`}>
                    <button className="btn" onClick={() => setSelectedCard(name)}>{name}</button>
                  </li>
                ))}
              </ul>

              <h3>Detected Combo Lines (CommanderSpellbook)</h3>
              {(intentSummary?.combo_lines || []).length === 0 ? (
                <p className="muted">No complete or near-miss combo lines detected.</p>
              ) : (
                <ul>
                  {(intentSummary?.combo_lines || []).slice(0, 8).map((line: any, i: number) => (
                    <li key={`combo-line-${i}`}>
                      <strong>{line.variant_id}</strong> ({line.status === "complete" ? "complete" : "near miss"})
                      {line.present_cards?.length ? ` | present: ${line.present_cards.slice(0, 4).join(", ")}` : ""}
                      {line.missing_cards?.length ? ` | missing: ${line.missing_cards.join(", ")}` : ""}
                    </li>
                  ))}
                </ul>
              )}
              {comboIntel?.warnings?.length > 0 && (
                <ul className="list-compact">
                  {comboIntel.warnings.map((w: string, i: number) => <li key={i}>{w}</li>)}
                </ul>
              )}

              <h2>Rules Risk Snapshot</h2>
              <p>
                Watchouts detected: <strong>{(analysis?.rules_watchouts || []).length}</strong>. Open the Rules Watchouts tab for rulings and errata-sensitive interactions.
              </p>

              <h2>Mana Sufficiency</h2>
              <div className="metric-help">
                <div><strong>What this shows:</strong> Probability-based mana consistency checks.</div>
                <div><strong>P(4 mana by T3):</strong> chance of reaching four mana sources by turn 3.</div>
                <div><strong>Good:</strong> around 55%+ for many mid-power decks.</div>
                <div><strong>Bad:</strong> much lower means slow starts; high screw means misses are frequent.</div>
                <div><strong>What to change:</strong> add lands/fixing/cheap ramp and trim clunky early dead cards.</div>
              </div>
              <ul>
                <li>Lands tagged: {analysis?.role_breakdown?.lands ?? "n/a"}</li>
                <li>P(4 mana by turn 3): {pct(simRes?.summary?.milestones?.p_mana4_t3)}</li>
                <li>P(5 mana by turn 4): {pct(simRes?.summary?.milestones?.p_mana5_t4)}</li>
                <li>Mana screw rate: {pct(simRes?.summary?.failure_modes?.mana_screw)}</li>
              </ul>
              <p>
                Mana looks{" "}
                {num(simRes?.summary?.failure_modes?.mana_screw) < 0.2 ? "healthy" : "at risk"}
                {" "}for consistent openings in repeated goldfish runs.
              </p>

              <h2>Role & Curve Health</h2>
              <ul>
                {(analysis?.missing_roles || []).slice(0, 4).map((g: any, i: number) => (
                  <li key={i}>
                    {g.role}: have {g.have}, target {g.target}, missing {g.missing}
                  </li>
                ))}
              </ul>
              {(analysis?.missing_roles || []).length === 0 && <p>No major role deficits detected.</p>}

              <h2>Key Risks Observed</h2>
              <div className="metric-help">
                <div><strong>No-action starts:</strong> games where early turns have no meaningful casts.</div>
                <div><strong>Flood tendency:</strong> draws with too much mana and not enough action.</div>
                <div><strong>Median commander cast turn:</strong> midpoint cast timing across all runs.</div>
                <div><strong>Bad:</strong> high no-action or very late commander timing compared to plan speed.</div>
                <div><strong>What to change:</strong> lower curve, increase setup density, and improve color fixing.</div>
              </div>
              <ul>
                <li>No-action starts: {pct(simRes?.summary?.failure_modes?.no_action)}</li>
                <li>Flood tendency: {pct(simRes?.summary?.failure_modes?.flood)}</li>
                <li>Median commander cast turn: {simRes?.summary?.milestones?.median_commander_cast_turn ?? "n/a"}</li>
              </ul>

              <h2>Most Important Cards Overall</h2>
              <ul>
                {topImportance.slice(0, 8).map((c: any, i: number) => (
                  <li key={i}>{c.card} ({(c.score ?? 0).toFixed(3)})</li>
                ))}
              </ul>

              <h2>Data Provenance</h2>
              <ul>
                {(integrationsMeta?.integrations || []).map((i: any, idx: number) => (
                  <li key={idx}>
                    <strong>{i.key}</strong> ({i.status}): {i.purpose} <a href={i.url} target="_blank" rel="noreferrer">[source]</a>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {tab === "Tagged Decklist" && (
            <div className="stack">
              <div className="row">
                <button
                  className="btn"
                  onClick={async () => {
                    const text = tagRes?.tagged_lines?.join("\n") || "";
                    await navigator.clipboard.writeText(text);
                  }}
                >
                  Copy tagged decklist
                </button>
                <span className="muted">Tags are rule-based from type line, oracle text, commander context, and optional curated overrides.</span>
              </div>
              <div className="mono">{tagRes?.tagged_lines?.join("\n") || "Run analysis to populate tagged lines."}</div>
            </div>
          )}

          {tab === "Lenses" && (
            <div className="guide-rendered">
              <h2>Reliability and Mana Lens</h2>
              <p className="muted">
                Percentiles: <strong>p50</strong> means the middle/typical game, <strong>p75</strong> means better-than-typical games, and <strong>p90</strong> means high-roll games.
              </p>
              {renderMetricHelp("mana_percentiles")}
              <div style={{ width: "100%", height: 230 }}>
                <ResponsiveContainer>
                  <LineChart data={graphPayloads?.mana_percentiles || []}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="turn" label={{ value: "Turn", position: "insideBottom", offset: -2 }} />
                    <YAxis label={{ value: "Mana sources", angle: -90, position: "insideLeft" }} />
                    <Tooltip />
                    <Line type="monotone" dataKey="p50" stroke="#111" strokeWidth={2} />
                    <Line type="monotone" dataKey="p75" stroke="#555" strokeWidth={2} />
                    <Line type="monotone" dataKey="p90" stroke="#999" strokeWidth={2} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("mana_percentiles")}

              {renderMetricHelp("land_hit_cdf")}
              <div style={{ width: "100%", height: 220 }}>
                <ResponsiveContainer>
                  <LineChart data={graphPayloads?.land_hit_cdf || []}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="turn" label={{ value: "Turn", position: "insideBottom", offset: -2 }} />
                    <YAxis domain={[0, 1]} label={{ value: "Probability", angle: -90, position: "insideLeft" }} />
                    <Tooltip formatter={(v: any) => `${(Number(v) * 100).toFixed(1)}%`} />
                    <Line type="monotone" dataKey="p_hit_on_curve" stroke="#111" strokeWidth={2.5} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("land_hit_cdf")}

              <h2>Color Access by Turn</h2>
              {renderMetricHelp("color_access")}
              {colorIdentitySize <= 1 ? (
                <div className="metric-help">
                  <div><strong>This deck is {colorIdentitySize === 0 ? "colorless" : "single-color"}.</strong></div>
                  <div>Color-access stress is minimal here, so this metric is less important than total mana development and action density.</div>
                </div>
              ) : (
                <div style={{ width: "100%", height: 240 }}>
                  <ResponsiveContainer>
                    <LineChart data={graphPayloads?.color_access || []}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="turn" label={{ value: "Turn", position: "insideBottom", offset: -2 }} />
                      <YAxis yAxisId="left" domain={[0, Math.max(2, colorIdentitySize)]} label={{ value: "Colors online", angle: -90, position: "insideLeft" }} />
                      <YAxis yAxisId="right" orientation="right" domain={[0, 1]} label={{ value: "P(full identity)", angle: 90, position: "insideRight" }} />
                      <Tooltip formatter={(v: any, k: any) => (String(k).includes("p_") ? `${(Number(v) * 100).toFixed(1)}%` : Number(v).toFixed(2))} />
                      <Legend />
                      <Line yAxisId="left" type="monotone" dataKey="avg_colors" stroke="#333" strokeWidth={2.4} name="Avg colors online" />
                      <Line yAxisId="right" type="monotone" dataKey="p_full_identity" stroke="#7a7a7a" strokeWidth={2} name="P(full identity online)" />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
              {renderDeckBlurb("color_access")}

              <h2>Plan Execution Lens</h2>
              {renderMetricHelp("phase_timeline")}
              <div style={{ width: "100%", height: 260 }}>
                <ResponsiveContainer>
                  <AreaChart data={graphPayloads?.phase_timeline || []}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="turn" label={{ value: "Turn", position: "insideBottom", offset: -2 }} />
                    <YAxis domain={[0, 1]} label={{ value: "Share of games", angle: -90, position: "insideLeft" }} />
                    <Tooltip formatter={(v: any) => `${(Number(v) * 100).toFixed(1)}%`} />
                    <Legend />
                    <Area type="monotone" dataKey="setup" stackId="1" stroke="#bbb" fill="#d8d8d8" />
                    <Area type="monotone" dataKey="engine" stackId="1" stroke="#888" fill="#b7b7b7" />
                    <Area type="monotone" dataKey="win_attempt" stackId="1" stroke="#333" fill="#6e6e6e" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("phase_timeline")}

              {renderMetricHelp("win_turn_cdf")}
              <div style={{ width: "100%", height: 220 }}>
                <ResponsiveContainer>
                  <LineChart data={graphPayloads?.win_turn_cdf || []}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="turn" label={{ value: "Turn", position: "insideBottom", offset: -2 }} />
                    <YAxis domain={[0, 1]} label={{ value: "Cumulative probability", angle: -90, position: "insideLeft" }} />
                    <Tooltip formatter={(v: any) => `${(Number(v) * 100).toFixed(1)}%`} />
                    <Line type="monotone" dataKey="cdf" stroke="#111" strokeWidth={2.5} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("win_turn_cdf")}

              <h2>Risk Lens</h2>
              {renderMetricHelp("no_action_funnel")}
              <div style={{ width: "100%", height: 220 }}>
                <ResponsiveContainer>
                  <LineChart data={graphPayloads?.no_action_funnel || []}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="turn" label={{ value: "Turn", position: "insideBottom", offset: -2 }} />
                    <YAxis domain={[0, 1]} label={{ value: "No-action probability", angle: -90, position: "insideLeft" }} />
                    <Tooltip formatter={(v: any) => `${(Number(v) * 100).toFixed(1)}%`} />
                    <Line type="monotone" dataKey="p_no_action" stroke="#8a1e1e" strokeWidth={2.5} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("no_action_funnel")}

              {renderMetricHelp("dead_cards_top")}
              <div style={{ width: "100%", height: 260 }}>
                <ResponsiveContainer>
                  <BarChart data={(graphPayloads?.dead_cards_top || []).slice(0, 10)}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="card" hide />
                    <YAxis label={{ value: "Stranded rate", angle: -90, position: "insideLeft" }} />
                    <Tooltip formatter={(v: any) => `${(Number(v) * 100).toFixed(1)}%`} />
                    <Bar dataKey="rate" fill="#444" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("dead_cards_top")}

              <h2>Operational Lens</h2>
              {renderMetricHelp("commander_cast_distribution")}
              <div style={{ width: "100%", height: 220 }}>
                <ResponsiveContainer>
                  <BarChart data={graphPayloads?.commander_cast_distribution || []}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="turn" label={{ value: "Cast turn", position: "insideBottom", offset: -2 }} />
                    <YAxis label={{ value: "Rate", angle: -90, position: "insideLeft" }} />
                    <Tooltip formatter={(v: any) => `${(Number(v) * 100).toFixed(1)}%`} />
                    <Bar dataKey="rate" fill="#111" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("commander_cast_distribution")}
              {renderMetricHelp("mulligan_funnel")}
              <div style={{ width: "100%", height: 220 }}>
                <ResponsiveContainer>
                  <BarChart data={graphPayloads?.mulligan_funnel || []}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="mulligans" label={{ value: "Mulligans taken", position: "insideBottom", offset: -2 }} />
                    <YAxis label={{ value: "Rate", angle: -90, position: "insideLeft" }} />
                    <Tooltip formatter={(v: any) => `${(Number(v) * 100).toFixed(1)}%`} />
                    <Bar dataKey="rate" fill="#666" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("mulligan_funnel")}

              <h2>Complex Systems Metrics</h2>
              <p className="muted">Adapted from systems analysis: resilience, redundancy, bottlenecks, and impact concentration for deck robustness.</p>
              <div style={{ width: "100%", height: 220 }}>
                <ResponsiveContainer>
                  <BarChart
                    data={[
                      { metric: "Resilience", value: num(analysis?.systems_metrics?.resilience_score) },
                      { metric: "Redundancy", value: num(analysis?.systems_metrics?.redundancy_score) },
                      { metric: "Bottleneck", value: num(analysis?.systems_metrics?.bottleneck_index) },
                      { metric: "Impact Inequality", value: num(analysis?.systems_metrics?.impact_inequality) * 100 },
                    ]}
                  >
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="metric" label={{ value: "Metric", position: "insideBottom", offset: -2 }} />
                    <YAxis label={{ value: "Score", angle: -90, position: "insideLeft" }} />
                    <Tooltip />
                    <Bar dataKey="value" fill="#2f2f2f" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {tab === "Diagnostic" && (
            <div className="guide-rendered">
              <h2>Diagnostic</h2>
              <p className="muted">Operational and rules-risk diagnostics for this run.</p>

              <h2>Oracle + Rulings Watchouts</h2>
              <p className="muted">
                These are cards with rule-dense wording, replacement/trigger complexity, or official rulings that frequently cause sequencing mistakes.
              </p>
              <div className="metric-help">
                <div><strong>What this shows:</strong> Cards with higher rules complexity and relevant official ruling notes.</div>
                <div><strong>Good:</strong> You understand these interactions and can sequence them without losing value.</div>
                <div><strong>Bad:</strong> Frequent mis-sequencing around replacement effects, trigger timing, or alternate casting costs.</div>
                <div><strong>What to change:</strong> Review flagged cards before matches and practice their common timing patterns.</div>
              </div>
              <h2>Interaction Notes</h2>
              <ul>
                {(analysis?.rules_interaction_notes || []).slice(0, 8).map((n: string, i: number) => <li key={i}>{n}</li>)}
              </ul>
              <table className="table">
                <thead>
                  <tr><th>Card</th><th>Why this is tricky</th><th>Ruling notes</th></tr>
                </thead>
                <tbody>
                  {(analysis?.rules_watchouts || []).map((w: any, i: number) => (
                    <tr key={`${w.card}-${i}`}>
                      <td>
                        <button className="btn" onClick={() => setSelectedCard(w.card)}>{w.card}</button>
                        {w.commander ? <div className="control-help">Commander</div> : null}
                        <div className="control-help">
                          <a href={w.scryfall_uri || "#"} target="_blank" rel="noreferrer">Oracle page</a>
                        </div>
                      </td>
                      <td>
                        {(w.complexity_flags || []).length
                          ? <ul>{(w.complexity_flags || []).map((f: string, j: number) => <li key={j}>{f}</li>)}</ul>
                          : <span>Rule text nuance detected.</span>}
                        {(w.rule_queries || []).length ? (
                          <div className="control-help">Rules search keys: {(w.rule_queries || []).join("; ")}</div>
                        ) : null}
                        <div className="control-help">{w.oracle_watchout}</div>
                      </td>
                      <td>
                        {(w.rulings || []).length
                          ? <ul>{(w.rulings || []).slice(0, 2).map((r: any, j: number) => <li key={j}>{r.published_at}: {r.comment}</li>)}</ul>
                          : <span className="muted">No extra rulings fetched.</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {(analysis?.rules_watchouts || []).length === 0 && <p>No major watchouts detected for this list.</p>}
            </div>
          )}

          {tab === "Role Breakdown" && (
            <div className="guide-rendered">
              <h2>Adaptive Role Targets</h2>
              <div className="metric-help">
                <div><strong>What this shows:</strong> Role counts compared against adaptive ranges inferred from this deck&apos;s actual plan and sim behavior.</div>
                <div><strong>Philosophy:</strong> Not all categories should be equal for all decks. A proactive combo deck can be correct with 0-2 boardwipes, while control shells often need more.</div>
                <div><strong>Good:</strong> Core roles are inside their range for your strategy.</div>
                <div><strong>Bad:</strong> Roles below minimum usually cause structural non-games (mana issues, no action, no closure).</div>
                <div><strong>What to change:</strong> Fix below-min roles first, then tune center targets.</div>
              </div>

              <h2>Detected Deckbuilding Profile</h2>
              <p>
                <strong>Primary profile:</strong> {roleTargetModel?.primary_philosophy || "n/a"}
              </p>
              <p className="control-help">
                Targets are blended from multiple philosophies rather than enforcing one rigid doctrine.
              </p>
              <ul className="list-compact">
                {Object.entries(roleTargetModel?.philosophy_weights || {})
                  .sort((a: any, b: any) => Number(b[1]) - Number(a[1]))
                  .map(([k, v]: any) => (
                    <li key={k}>{k}: {(Number(v) * 100).toFixed(1)}%</li>
                  ))}
              </ul>
              <ul className="list-compact">
                {(roleTargetModel?.notes || []).map((n: string, i: number) => <li key={i}>{n}</li>)}
              </ul>

              <table className="table">
                <thead>
                  <tr><th>Role</th><th>Have</th><th>Target Range</th><th>Status</th><th>Why</th><th></th></tr>
                </thead>
                <tbody>
                  {roleRows.map((row: any) => (
                    <Fragment key={row.role}>
                      <tr key={row.role}>
                        <td>{row.role}</td>
                        <td>{row.have}</td>
                        <td>{row.maxTarget > 0 ? `${row.minTarget}-${row.maxTarget} (center ${row.center})` : "context only"}</td>
                        <td>
                          {row.status === "below" ? "Below minimum" : row.status === "above" ? "Above range" : row.status === "on_track" ? "In range" : "Unscored"}
                        </td>
                        <td>{row.reason}</td>
                        <td><button className="btn" onClick={() => toggleRole(row.role)}>{expandedRoles[row.role] ? "Hide cards" : "Show cards"}</button></td>
                      </tr>
                      {expandedRoles[row.role] ? (
                        <tr key={`${row.role}-cards`}>
                          <td colSpan={6}>
                            {(row.cards || []).length === 0 ? (
                              <span className="muted">No cards mapped for this role in current tagged list.</span>
                            ) : (
                              <div className="row" style={{ flexWrap: "wrap" }}>
                                {(row.cards || []).map((x: any, idx: number) => (
                                  <button key={`${row.role}-${x.name}-${idx}`} className="btn" onClick={() => setSelectedCard(x.name)}>
                                    {x.qty}x {x.name}
                                  </button>
                                ))}
                              </div>
                            )}
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  ))}
                </tbody>
              </table>
              <h2>Bracket Status</h2>
              <p>
                Bracket {analysis?.bracket_report?.bracket ?? bracket}
                {analysis?.bracket_report?.bracket_name ? ` (${analysis?.bracket_report?.bracket_name})` : ""}.
              </p>
              <p className="control-help">
                Criteria below include official limits and bracket-aligned heuristics. Official failures are compliance issues; heuristic misses are guidance.
              </p>
              <table className="table">
                <thead>
                  <tr><th>Criterion</th><th>Source</th><th>Current</th><th>Target</th><th>Status</th><th>Cards matching criterion</th></tr>
                </thead>
                <tbody>
                  {(analysis?.bracket_report?.criteria || []).map((c: any, i: number) => {
                    const t = c?.target || {};
                    let targetLabel = "n/a";
                    if (typeof t?.min === "number" && typeof t?.max === "number") targetLabel = `${t.min}-${t.max}`;
                    else if (typeof t?.max === "number") targetLabel = `<= ${t.max}`;
                    else if (typeof t?.min === "number") targetLabel = `>= ${t.min}`;
                    return (
                      <tr key={`${c?.key || "criterion"}-${i}`}>
                        <td>
                          <div><strong>{c?.label || c?.key || "criterion"}</strong></div>
                          <div className="control-help">{c?.description || ""}</div>
                        </td>
                        <td>{c?.source === "official" ? "Official" : "Heuristic"}</td>
                        <td>{c?.current ?? 0}</td>
                        <td>{targetLabel}</td>
                        <td>
                          {c?.status === "pass" ? "Pass" : c?.status === "fail" ? "Fail" : "Warn"}
                          <div className="control-help">{c?.status_detail || ""}</div>
                        </td>
                        <td>
                          {(c?.cards || []).length === 0 ? (
                            <span className="muted">none</span>
                          ) : (
                            <div className="row" style={{ flexWrap: "wrap" }}>
                              {(c?.cards || []).slice(0, 12).map((x: any, j: number) => (
                                <button key={`${c?.key || "c"}-${x?.name || "n"}-${j}`} className="btn" onClick={() => setSelectedCard(x?.name)}>
                                  {cardThumb(x?.name) ? (
                                    <img
                                      src={cardThumb(x?.name)}
                                      alt={x?.name || "card"}
                                      width={20}
                                      height={28}
                                      loading="lazy"
                                      style={{ borderRadius: 3, marginRight: 6, verticalAlign: "middle", border: "1px solid #ddd" }}
                                    />
                                  ) : null}
                                  {x?.qty || 1}x {x?.name}
                                </button>
                              ))}
                            </div>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {bracketViolations.length > 0 && (
                <ul>
                  {bracketViolations.map((v: string, i: number) => <li key={i}>{v}</li>)}
                </ul>
              )}
              {(analysis?.bracket_report?.advisories || []).length > 0 && (
                <>
                  <h3>Bracket Advisories</h3>
                  <ul>
                    {(analysis?.bracket_report?.advisories || []).map((v: string, i: number) => <li key={i}>{v}</li>)}
                  </ul>
                </>
              )}
            </div>
          )}

          {tab === "Mana Base" && (
            <div className="guide-rendered">
              <h2>Mana Base Analyzer</h2>
              <div className="metric-help">
                <div><strong>What this module does:</strong> it compares <strong>color demand</strong> (mana pips your spells require) versus <strong>color supply</strong> (how many sources your mana base provides).</div>
                <div><strong>Why this matters:</strong> many Commander decks fail because colors are present in theory, but not available on the turns your spells need them.</div>
                <div><strong>Method:</strong> pip parsing from mana costs + source counting from produced mana (lands and nonlands separated).</div>
              </div>
              {(manabase?.methodology || []).length ? (
                <ul className="list-compact">
                  {(manabase.methodology || []).map((m: string, i: number) => <li key={i}>{m}</li>)}
                </ul>
              ) : null}

              <div className="kpi-grid" style={{ marginBottom: 10 }}>
                <div className="mini-card">
                  <div className="mini-label">Total Colored Pips</div>
                  <div className="mini-value">{Number(manabaseSummary?.total_colored_pips || 0).toFixed(1)}</div>
                </div>
                <div className="mini-card">
                  <div className="mini-label">Colorless/Generic Pips</div>
                  <div className="mini-value">{Number(manabaseSummary?.total_colorless_pips || 0).toFixed(1)}</div>
                </div>
                <div className="mini-card">
                  <div className="mini-label">Weighted Sources</div>
                  <div className="mini-value">{Number(manabaseSummary?.total_weighted_sources || 0).toFixed(1)}</div>
                </div>
                <div className="mini-card">
                  <div className="mini-label">Most Stressed Color</div>
                  <div className={`mini-value ${Number(manabaseSummary?.most_stressed_gap_pct || 0) < -8 ? "tone-bad" : Number(manabaseSummary?.most_stressed_gap_pct || 0) < -3 ? "tone-warn" : "tone-good"}`}>
                    {manabaseSummary?.most_stressed_color || "n/a"} {manabaseSummary?.most_stressed_color ? `(${Number(manabaseSummary?.most_stressed_gap_pct || 0).toFixed(1)} pp)` : ""}
                  </div>
                </div>
              </div>

              {(manabase?.advisories || []).length > 0 ? (
                <>
                  <h3>Actionable Advice For This Deck</h3>
                  <ul>
                    {(manabase?.advisories || []).slice(0, 6).map((a: string, i: number) => <li key={i}>{a}</li>)}
                  </ul>
                </>
              ) : (
                <p className="muted">No major color-balance stress detected in this run.</p>
              )}

              <h2>Pip Demand by Color</h2>
              {renderMetricHelp("manabase_pip_distribution")}
              <div style={{ width: "100%", height: 260 }}>
                <ResponsiveContainer>
                  <BarChart data={graphPayloads?.manabase_pip_distribution || []}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="color" label={{ value: "Color", position: "insideBottom", offset: -2 }} />
                    <YAxis label={{ value: "Pip demand", angle: -90, position: "insideLeft" }} />
                    <Tooltip formatter={(v: any) => Number(v).toFixed(2)} />
                    <Legend />
                    <Bar dataKey="early" stackId="pips" fill="#9a9a9a" name="Early (MV<=2)" />
                    <Bar dataKey="mid" stackId="pips" fill="#707070" name="Mid (MV3-4)" />
                    <Bar dataKey="late" stackId="pips" fill="#3a3a3a" name="Late (MV5+)" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("manabase_pip_distribution")}

              <h2>Source Coverage by Color</h2>
              {renderMetricHelp("manabase_source_coverage")}
              <div style={{ width: "100%", height: 260 }}>
                <ResponsiveContainer>
                  <BarChart data={graphPayloads?.manabase_source_coverage || []}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="color" label={{ value: "Color", position: "insideBottom", offset: -2 }} />
                    <YAxis label={{ value: "Source count", angle: -90, position: "insideLeft" }} />
                    <Tooltip formatter={(v: any) => Number(v).toFixed(2)} />
                    <Legend />
                    <Bar dataKey="land_sources" stackId="src" fill="#4b4b4b" name="Land sources" />
                    <Bar dataKey="nonland_sources" stackId="src" fill="#9b9b9b" name="Nonland sources" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("manabase_source_coverage")}

              <h2>Demand vs Supply Gap</h2>
              {renderMetricHelp("manabase_balance_gap")}
              <div style={{ width: "100%", height: 260 }}>
                <ResponsiveContainer>
                  <BarChart data={graphPayloads?.manabase_balance_gap || []}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="color" label={{ value: "Color", position: "insideBottom", offset: -2 }} />
                    <YAxis label={{ value: "Share", angle: -90, position: "insideLeft" }} />
                    <Tooltip formatter={(v: any) => `${(Number(v) * 100).toFixed(1)}%`} />
                    <Legend />
                    <Bar dataKey="demand_share" fill="#2d2d2d" name="Demand share" />
                    <Bar dataKey="source_share" fill="#8a8a8a" name="Source share" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("manabase_balance_gap")}

              <h2>Mana Value Curve and On-Curve Odds</h2>
              {renderMetricHelp("curve_histogram")}
              <div className="metric-help">
                <div><strong>Average MV with lands:</strong> {Number(manabaseSummary?.average_mana_value_with_lands || 0).toFixed(2)} | <strong>without lands:</strong> {Number(manabaseSummary?.average_mana_value_without_lands || 0).toFixed(2)}</div>
                <div><strong>Median MV with lands:</strong> {Number(manabaseSummary?.median_mana_value_with_lands || 0).toFixed(2)} | <strong>without lands:</strong> {Number(manabaseSummary?.median_mana_value_without_lands || 0).toFixed(2)}</div>
                <div><strong>Total mana value:</strong> {Number(manabaseSummary?.total_mana_value_with_lands || 0).toFixed(1)} with lands, {Number(manabaseSummary?.total_mana_value_without_lands || 0).toFixed(1)} without lands.</div>
                <div><strong>How to use:</strong> click a mana-value bucket to inspect cards and estimated on-curve cast chance for that bucket.</div>
              </div>
              <div style={{ width: "100%", height: 280 }}>
                <ResponsiveContainer>
                  <BarChart data={curveData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="mana_value" label={{ value: "Mana value", position: "insideBottom", offset: -2 }} />
                    <YAxis yAxisId="left" label={{ value: "Card count", angle: -90, position: "insideLeft" }} />
                    <YAxis yAxisId="right" orientation="right" domain={[0, 1]} label={{ value: "P(on curve)", angle: 90, position: "insideRight" }} />
                    <Tooltip
                      formatter={(v: any, name: any) => {
                        if (String(name).includes("p_on_curve")) return `${(Number(v) * 100).toFixed(1)}%`;
                        return Number(v).toFixed(1);
                      }}
                    />
                    <Legend />
                    <Bar
                      yAxisId="left"
                      dataKey="permanents"
                      stackId="curve"
                      fill="#7f7f7f"
                      name="Permanents"
                      onClick={(d: any) => setSelectedCurveMv(Number(d?.mana_value ?? 0))}
                    />
                    <Bar
                      yAxisId="left"
                      dataKey="spells"
                      stackId="curve"
                      fill="#b5b5b5"
                      name="Spells"
                      onClick={(d: any) => setSelectedCurveMv(Number(d?.mana_value ?? 0))}
                    />
                    <Line yAxisId="right" type="monotone" dataKey="p_on_curve_est" stroke="#111" strokeWidth={2} dot={{ r: 2 }} name="Estimated P(on curve)" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("curve_histogram")}

              {activeCurveMv != null && (
                <>
                  <h3>Cards at Mana Value {activeCurveMv}</h3>
                  <p className="control-help">
                    Estimated on-curve for this bucket: {activeCurveRow ? `${(Number(activeCurveRow?.p_on_curve_est || 0) * 100).toFixed(1)}%` : "n/a"}.
                    {" "}This estimate combines raw mana availability from simulations with current color-balance stress.
                  </p>
                  <table className="table">
                    <thead>
                      <tr><th>Card</th><th>Type</th><th>Mana Cost</th><th>Estimated P(on curve)</th></tr>
                    </thead>
                    <tbody>
                      {selectedCurveCards.length === 0 ? (
                        <tr><td colSpan={4}><span className="muted">No cards in this bucket.</span></td></tr>
                      ) : (
                        selectedCurveCards.map((x: any, i: number) => (
                          <tr key={`${x.card}-${i}`}>
                            <td>
                              <button className="btn" style={{ display: "inline-flex", alignItems: "center", gap: 8 }} onClick={() => setSelectedCard(x.card)}>
                                {cardThumb(x.card) ? <img src={cardThumb(x.card)} alt={x.card} width={24} height={34} loading="lazy" style={{ borderRadius: 4 }} /> : null}
                                <span>{x.qty}x {x.card}</span>
                              </button>
                            </td>
                            <td>{x.group === "spells" ? "Spell" : "Permanent"}</td>
                            <td>{x.mana_cost || "n/a"}</td>
                            <td>{(Number(x.p_on_curve_est || 0) * 100).toFixed(1)}%</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </>
              )}

              <h2>Color-by-Color Detail</h2>
              <table className="table">
                <thead>
                  <tr>
                    <th>Color</th>
                    <th>Pips</th>
                    <th>Demand%</th>
                    <th>Land Sources</th>
                    <th>Nonland Sources</th>
                    <th>Weighted Sources</th>
                    <th>Supply%</th>
                    <th>Gap</th>
                    <th>Status</th>
                    <th>Top Producers</th>
                  </tr>
                </thead>
                <tbody>
                  {(manabaseRows || []).map((r: any, i: number) => (
                    <tr key={`${r.color}-${i}`}>
                      <td>
                        <span className={`mana-badge mana-${String(r.color || "C").toLowerCase()}`}>{r.color}</span>
                        {" "}{r.label}
                      </td>
                      <td>{Number(r.pips || 0).toFixed(1)}</td>
                      <td>{Number(r.demand_share_pct || 0).toFixed(1)}%</td>
                      <td>{Number(r.land_sources || 0).toFixed(1)}</td>
                      <td>{Number(r.nonland_sources || 0).toFixed(1)}</td>
                      <td>{Number(r.weighted_sources || 0).toFixed(2)}</td>
                      <td>{Number(r.source_share_pct || 0).toFixed(1)}%</td>
                      <td className={Number(r.gap_pct || 0) < -8 ? "tone-bad" : Number(r.gap_pct || 0) < -3 ? "tone-warn" : "tone-good"}>
                        {Number(r.gap_pct || 0).toFixed(1)}pp
                      </td>
                      <td>{r.status === "under" ? "Under-supplied" : r.status === "warning" ? "Tight" : r.status === "over" ? "Over-supplied" : "Balanced"}</td>
                      <td>
                        {(r.top_sources || []).length === 0 ? (
                          <span className="muted">n/a</span>
                        ) : (
                          <div className="row" style={{ flexWrap: "wrap" }}>
                            {(r.top_sources || []).slice(0, 4).map((s: any, j: number) => (
                              <button key={`${r.color}-src-${j}`} className="btn" onClick={() => setSelectedCard(s.name)}>
                                {cardThumb(s.name) ? <img src={cardThumb(s.name)} alt={s.name} width={20} height={28} loading="lazy" style={{ borderRadius: 3, marginRight: 6, verticalAlign: "middle", border: "1px solid #ddd" }} /> : null}
                                {s.qty}x {s.name}
                              </button>
                            ))}
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <h2>High Pip Pressure Cards</h2>
              <p className="control-help">These cards drive color requirements the most. If a color is stressed, start by adjusting this list or its supporting sources.</p>
              <table className="table">
                <thead>
                  <tr><th>Card</th><th>Mana Cost</th><th>Pip Pressure</th><th>MV</th></tr>
                </thead>
                <tbody>
                  {(manabaseTopPipCards || []).slice(0, 12).map((x: any, i: number) => (
                    <tr key={`${x.card}-${i}`}>
                      <td>
                        <button className="btn" style={{ display: "inline-flex", alignItems: "center", gap: 8 }} onClick={() => setSelectedCard(x.card)}>
                          {cardThumb(x.card) ? <img src={cardThumb(x.card)} alt={x.card} width={24} height={34} loading="lazy" style={{ borderRadius: 4 }} /> : null}
                          <span>{x.card}</span>
                        </button>
                      </td>
                      <td>{x.mana_cost || "n/a"}</td>
                      <td>{Number(x.pressure || 0).toFixed(2)}</td>
                      <td>{Number(x.mana_value || 0).toFixed(1)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {tab === "Goldfish Report" && (
            <div className="guide-rendered">
              <div className="kpi-grid" style={{ marginBottom: 10 }}>
                <div className="mini-card"><div className="mini-label">P(4 mana by T3)</div><div className="mini-value">{pct(simRes?.summary?.milestones?.p_mana4_t3)}</div></div>
                <div className="mini-card"><div className="mini-label">P(5 mana by T4)</div><div className="mini-value">{pct(simRes?.summary?.milestones?.p_mana5_t4)}</div></div>
                <div className="mini-card"><div className="mini-label">Median Commander Turn</div><div className="mini-value">{simRes?.summary?.milestones?.median_commander_cast_turn ?? "n/a"}</div></div>
                <div className="mini-card"><div className="mini-label">Win By Turn Limit</div><div className="mini-value">{pct(winMetrics?.p_win_by_turn_limit)}</div></div>
                <div className="mini-card"><div className="mini-label">Sim Backend</div><div className="mini-value">{simRes?.summary?.backend_used || "n/a"}</div></div>
              </div>
              <div className="metric-help">
                <div><strong>Metric notes:</strong> `P(...)` means probability/percentage of games where a condition happens. Median commander turn means the middle game after sorting all runs.</div>
                <div><strong>Good baseline:</strong> P(4 mana by T3) near 55%+ and low no-action starts are usually healthy for mid-power lists.</div>
                <div><strong>Bad signal:</strong> low mana probabilities + high no-action/flood/screw means opener structure is unstable.</div>
                {simRes?.summary?.warning ? <div><strong>Backend warning:</strong> {simRes.summary.warning}</div> : null}
              </div>

              <h2>Plan Progress By Turn</h2>
              {renderMetricHelp("plan_progress")}
              <div style={{ width: "100%", height: 260 }}>
                <ResponsiveContainer>
                  <LineChart data={chartData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="turn" label={{ value: "Turn", position: "insideBottom", offset: -2 }} />
                    <YAxis label={{ value: "Plan progress score", angle: -90, position: "insideLeft" }} />
                    <Tooltip />
                    <Line type="monotone" dataKey="median" stroke="#111" strokeWidth={2.5} />
                    <Line type="monotone" dataKey="p90" stroke="#8a8a8a" strokeWidth={2} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("plan_progress")}

              <h2>Failure Mode Rates</h2>
              {renderMetricHelp("failure_rates")}
              <div style={{ width: "100%", height: 220 }}>
                <ResponsiveContainer>
                  <BarChart data={failureData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" label={{ value: "Failure type", position: "insideBottom", offset: -2 }} />
                    <YAxis label={{ value: "Percent of runs", angle: -90, position: "insideLeft" }} />
                    <Tooltip formatter={(v: any) => `${Number(v).toFixed(1)}%`} />
                    <Bar dataKey="value" fill="#444" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("failure_rates")}

              <h2>Wincon Outcomes</h2>
              {renderMetricHelp("wincon_outcomes")}
              <div style={{ width: "100%", height: 220 }}>
                <ResponsiveContainer>
                  <BarChart data={winconData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" label={{ value: "Win route", position: "insideBottom", offset: -2 }} />
                    <YAxis label={{ value: "Percent of runs", angle: -90, position: "insideLeft" }} />
                    <Tooltip formatter={(v: any) => `${Number(v).toFixed(1)}%`} />
                    <Bar dataKey="value" fill="#111" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("wincon_outcomes")}
              <h2>Uncertainty (95% CI)</h2>
              {renderMetricHelp("uncertainty")}
              <div className="metric-help">
                <div><strong>Plain language:</strong> this is the likely range for each percentage, based on your current number of simulation runs.</div>
                <div><strong>Example:</strong> if P(4 mana by T3) is 52.3%-54.3%, your deck is likely around ~53% for that milestone, not exactly one fixed number.</div>
                <div><strong>Important:</strong> this does <em>not</em> mean “95% chance in one game.” It means the estimate itself is statistically reliable.</div>
                <div><strong>Current run count:</strong> {simRes?.summary?.runs ?? "n/a"} simulations.</div>
              </div>
              <ul>
                <li>
                  <strong>P(4 mana by T3):</strong> {ciLabel(uncertainty?.p_mana4_t3_ci95)}
                  {" "}({ciQuality(uncertainty?.p_mana4_t3_ci95)} range). This means chance to have at least 4 mana sources by turn 3.
                </li>
                <li>
                  <strong>P(5 mana by T4):</strong> {ciLabel(uncertainty?.p_mana5_t4_ci95)}
                  {" "}({ciQuality(uncertainty?.p_mana5_t4_ci95)} range). This means chance to have at least 5 mana sources by turn 4.
                </li>
                <li>
                  <strong>P(win by turn limit):</strong> {ciLabel(uncertainty?.p_win_by_turn_limit_ci95)}
                  {" "}({ciQuality(uncertainty?.p_win_by_turn_limit_ci95)} range). This is chance your simulated plan can close by the selected turn limit.
                </li>
              </ul>
              <p className="deck-blurb">
                Actionable read: if a range is <strong>wide</strong>, increase simulation runs before making major deck changes. If ranges are tight but outcomes are bad, change deck structure (mana, curve, role balance) rather than chasing random variance.
              </p>
              {renderDeckBlurb("uncertainty")}
            </div>
          )}

          {tab === "Fastet Wins" && (
            <div className="guide-rendered">
              <h2>Fastet Wins</h2>
              <div className="metric-help">
                <div><strong>What this shows:</strong> the three fastest winning simulations from this run configuration.</div>
                <div><strong>How to use it:</strong> compare opening hands, mulligan decisions, and early sequencing to see what your strongest starts actually look like.</div>
                <div><strong>Caution:</strong> these are high-performing lines, not average games. Use them as reference lines, not guaranteed outcomes.</div>
              </div>
              {fastestWins.length === 0 ? (
                <p className="muted">No wins were found in the current simulation window. Increase turn limit, improve win density, or raise run count.</p>
              ) : (
                <div className="stack">
                  {fastestWins.map((fw: any, i: number) => (
                    <div key={`fw-${i}`} className="block stack">
                      <h3 style={{ margin: 0 }}>
                        #{fw?.rank || i + 1} fastest win: Turn {fw?.win_turn ?? "n/a"}{fw?.wincon ? ` (${fw.wincon})` : ""}
                      </h3>
                      <p className="control-help">
                        Run index: {fw?.run_index ?? "n/a"} | Mulligans taken: {fw?.mulligans_taken ?? 0}
                      </p>

                      <h4 style={{ margin: 0 }}>Mulligan Sequence</h4>
                      {(fw?.mulligan_steps || []).length === 0 ? (
                        <p className="muted">No mulligan data captured.</p>
                      ) : (
                        <div className="stack">
                          {(fw?.mulligan_steps || []).map((step: any, sidx: number) => (
                            <div key={`fw-${i}-m-${sidx}`} className="metric-help">
                              <div>
                                <strong>Attempt {step?.attempt ?? sidx}:</strong>{" "}
                                {step?.kept ? "Kept" : "Mulligan"}
                                {typeof step?.bottom_count === "number" ? ` | Bottomed: ${step.bottom_count}` : ""}
                              </div>
                              <div className="row" style={{ flexWrap: "wrap", marginTop: 6 }}>
                                {(step?.hand || []).map((name: string, nidx: number) => renderCardChip(name, `fw-${i}-m-${sidx}-h-${nidx}`))}
                              </div>
                              {step?.kept_hand?.length ? (
                                <>
                                  <div className="control-help" style={{ marginTop: 6 }}><strong>Kept hand after bottoming:</strong></div>
                                  <div className="row" style={{ flexWrap: "wrap" }}>
                                    {(step?.kept_hand || []).map((name: string, nidx: number) => renderCardChip(name, `fw-${i}-m-${sidx}-k-${nidx}`))}
                                  </div>
                                </>
                              ) : null}
                            </div>
                          ))}
                        </div>
                      )}

                      <h4 style={{ margin: 0 }}>Opening Hand (Kept)</h4>
                      <div className="row" style={{ flexWrap: "wrap" }}>
                        {(fw?.opening_hand || []).map((name: string, nidx: number) => renderCardChip(name, `fw-${i}-o-${nidx}`))}
                      </div>

                      <h4 style={{ margin: 0 }}>Turn-by-Turn Line</h4>
                      <table className="table">
                        <thead>
                          <tr>
                            <th>Turn</th>
                            <th>Draw</th>
                            <th>Land</th>
                            <th>Casts</th>
                            <th>Phase</th>
                            <th>Mana</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(fw?.turns || []).map((t: any, tidx: number) => (
                            <tr key={`fw-${i}-t-${tidx}`}>
                              <td>{t?.turn}</td>
                              <td>
                                {t?.draw ? (
                                  <div className="row" style={{ flexWrap: "wrap" }}>
                                    {renderCardChip(t.draw, `fw-${i}-t-${tidx}-draw`)}
                                  </div>
                                ) : (
                                  <span className="muted">n/a</span>
                                )}
                              </td>
                              <td>
                                {t?.land ? (
                                  <div className="row" style={{ flexWrap: "wrap" }}>
                                    {renderCardChip(t.land, `fw-${i}-t-${tidx}-land`)}
                                  </div>
                                ) : (
                                  <span className="muted">none</span>
                                )}
                              </td>
                              <td>
                                {(t?.casts || []).length ? (
                                  <div className="row" style={{ flexWrap: "wrap" }}>
                                    {(t?.casts || []).map((name: string, cidx: number) => renderCardChip(name, `fw-${i}-t-${tidx}-c-${cidx}`))}
                                  </div>
                                ) : (
                                  <span className="muted">No spell casts</span>
                                )}
                              </td>
                              <td>
                                {t?.phase}
                                {t?.wincon_hit ? <div className="control-help">Win line: {t.wincon_hit}</div> : null}
                              </td>
                              <td>{t?.mana_total ?? "n/a"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {tab === "Card Importance" && (
            <div className="guide-rendered">
              <h2>Most Important Cards</h2>
              <div className="metric-help">
                <div><strong>What this shows:</strong> Composite impact score per card from seen/cast impact and centrality.</div>
                <div><strong>Good:</strong> Important cards align with your stated game plan and have redundancy.</div>
                <div><strong>Bad:</strong> If top cards are off-plan or irreplaceable single points of failure, deck is fragile.</div>
                <div><strong>What to change:</strong> Add role-redundant alternatives and remove low-impact off-plan cards.</div>
              </div>
              <div style={{ width: "100%", height: 240 }}>
                <ResponsiveContainer>
                  <BarChart data={importanceChartData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="card" hide />
                    <YAxis label={{ value: "Importance score", angle: -90, position: "insideLeft" }} />
                    <Tooltip formatter={(v: any) => Number(v).toFixed(3)} />
                    <Bar dataKey="score" fill="#222" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <p className="deck-blurb">
                Importance score combines: <strong>seen impact</strong> (how often outcomes improve when a card is seen), <strong>cast impact</strong> (improvement when cast), <strong>centrality</strong> (how central a card is to successful lines), and <strong>redundancy</strong> (how replaceable it is). Higher score means this card is doing more heavy lifting in your current deck.
              </p>
              <table className="table">
                <thead>
                  <tr><th>Card</th><th>Score</th><th>Why it matters</th></tr>
                </thead>
                <tbody>
                  {(analysis?.importance || []).slice(0, 20).map((c: any, i: number) => (
                    <tr key={`${c.card}-${i}`}>
                      <td>
                        <button className="btn" style={{ display: "inline-flex", alignItems: "center", gap: 8 }} onClick={() => setSelectedCard(c.card)}>
                          {cardThumb(c.card) ? (
                            <img src={cardThumb(c.card)} alt={c.card} width={24} height={34} loading="lazy" style={{ borderRadius: 4 }} />
                          ) : (
                            <span style={{ width: 24, height: 34, display: "inline-block", borderRadius: 4, background: "#efefef" }} />
                          )}
                          <span>{c.card}</span>
                        </button>
                      </td>
                      <td>{(c.score ?? 0).toFixed(3)}</td>
                      <td>{c.explanation || "Contributes to draw/mana/plan progression."}</td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <h2>Deadweight (Lowest Impact)</h2>
              <div className="metric-help">
                <div><strong>What this shows:</strong> Cards currently underperforming in goldfish context.</div>
                <div><strong>Use with care:</strong> Some low-impact cards are still necessary interaction or meta calls.</div>
                <div><strong>What to change:</strong> Start cuts with cards labeled replaceable, then re-run analysis.</div>
              </div>
              <table className="table">
                <thead>
                  <tr><th>Card</th><th>Low-impact reason</th><th>Score</th></tr>
                </thead>
                <tbody>
                  {(analysis?.cuts || []).slice(0, 12).map((c: any, i: number) => (
                    <tr key={`${c.card}-${i}`}>
                      <td>
                        <button className="btn" onClick={() => setSelectedCard(c.card)}>{c.card}</button>
                      </td>
                      <td>{c.reason || "Low impact in current simulations."}</td>
                      <td>{typeof c.score === "number" ? c.score.toFixed(3) : "n/a"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {tab === "Optimization" && (
            <div className="guide-rendered">
              <div className="metric-help">
                <div><strong>How to read this tab:</strong> Priority actions first, then cuts/adds/swaps.</div>
                <div><strong>Good:</strong> Actions target structural deficits (mana, draw, interaction, line support).</div>
                <div><strong>Bad:</strong> If suggestions only change finishers while fundamentals remain weak, results stay inconsistent.</div>
                <div><strong>What to change:</strong> Apply top 3 structural actions before cosmetic upgrades.</div>
                <div><strong>Color identity rule:</strong> Suggestions are filtered to {colorIdentitySize === 0 ? "Colorless" : colorIdentity.join("")} only.</div>
              </div>
              <h2>Actionable Actions</h2>
              <ul>
                {(analysis?.actionable_actions || []).slice(0, 8).map((a: any, i: number) => (
                  <li key={i}>
                    <strong>{a.title}</strong> ({a.priority || "n/a"}): {a.reason}
                  </li>
                ))}
              </ul>

              <h2>Recommended Cuts</h2>
              <table className="table">
                <thead>
                  <tr><th>Card</th><th>Reason</th></tr>
                </thead>
                <tbody>
                  {(analysis?.cuts || []).slice(0, 10).map((c: any, i: number) => (
                    <tr key={i}>
                      <td>
                        <button className="btn" style={{ display: "inline-flex", alignItems: "center", gap: 8 }} onClick={() => setSelectedCard(c.card)}>
                          {cardThumb(c.card) ? <img src={cardThumb(c.card)} alt={c.card} width={24} height={34} loading="lazy" style={{ borderRadius: 4 }} /> : null}
                          <span>{c.card}</span>
                        </button>
                      </td>
                      <td>{c.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <h2>Recommended Adds</h2>
              <table className="table">
                <thead>
                  <tr><th>Card</th><th>Fit</th><th>Budget</th><th>Source</th></tr>
                </thead>
                <tbody>
                  {(analysis?.adds || []).slice(0, 10).map((a: any, i: number) => (
                    <tr key={i}>
                      <td>
                        <button className="btn" style={{ display: "inline-flex", alignItems: "center", gap: 8 }} onClick={() => setSelectedCard(a.card)}>
                          {cardThumb(a.card) ? <img src={cardThumb(a.card)} alt={a.card} width={24} height={34} loading="lazy" style={{ borderRadius: 4 }} /> : null}
                          <span>{a.card}</span>
                        </button>
                      </td>
                      <td>fills {a.fills}. {a.why}</td>
                      <td>{a.budget_note && a.budget_note !== "n/a" ? `$${a.budget_note}` : "n/a"}</td>
                      <td>
                        {a.source || "heuristic"}
                        {" "}
                        <a href={cardDisplay(a.card)?.cardmarket_url || "#"} target="_blank" rel="noreferrer">[Cardmarket]</a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <h2>Suggested Swaps</h2>
              <table className="table">
                <thead>
                  <tr><th>Cut</th><th>Add</th><th>Reason</th></tr>
                </thead>
                <tbody>
                  {(analysis?.swaps || []).slice(0, 10).map((s: any, i: number) => (
                    <tr key={i}>
                      <td>
                        <button className="btn" style={{ display: "inline-flex", alignItems: "center", gap: 8 }} onClick={() => setSelectedCard(s.cut)}>
                          {cardThumb(s.cut) ? <img src={cardThumb(s.cut)} alt={s.cut} width={24} height={34} loading="lazy" style={{ borderRadius: 4 }} /> : null}
                          <span>{s.cut}</span>
                        </button>
                      </td>
                      <td>
                        <button className="btn" style={{ display: "inline-flex", alignItems: "center", gap: 8 }} onClick={() => setSelectedCard(s.add)}>
                          {cardThumb(s.add) ? <img src={cardThumb(s.add)} alt={s.add} width={24} height={34} loading="lazy" style={{ borderRadius: 4 }} /> : null}
                          <span>{s.add}</span>
                        </button>
                      </td>
                      <td>{s.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {comboNearMiss.length > 0 && (
                <>
                  <h2>Combo-Targeted Upgrades</h2>
                  <ul>
                    {comboNearMiss.slice(0, 5).map((v: any, i: number) => (
                      <li key={i}>
                        {v.variant_id}: add {v.missing_cards?.slice(0, 2).join(", ") || "missing pieces"} to complete a near-miss line.
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          )}

          {tab === "Primer" && (
            <div className="guide-rendered">
              <ReactMarkdown>{guides?.play_guide_md || "Run analysis first."}</ReactMarkdown>
            </div>
          )}
        </div>
          </div>
          <aside className={`card-insight ${selectedCard ? "open" : ""}`}>
            {selectedCard ? (
              <div className="stack">
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <h3 style={{ margin: 0 }}>{selectedCard}</h3>
                  <button className="btn" onClick={() => setSelectedCard(null)}>x</button>
                </div>
                {cardDisplay(selectedCard)?.normal ? (
                  <img
                    src={cardDisplay(selectedCard)?.normal}
                    alt={selectedCard}
                    width={290}
                    height={405}
                    loading="lazy"
                    style={{ width: "100%", height: "auto", borderRadius: 8, border: "1px solid #ddd" }}
                  />
                ) : (
                  <div style={{ width: "100%", aspectRatio: "146 / 204", borderRadius: 8, background: "#efefef", border: "1px solid #ddd" }} />
                )}

                <div className="stack">
                  <div className="insight-metric">
                    <span>Importance score</span>
                    <span className="tip" title="Composite impact score from seen impact, cast impact, graph centrality, and redundancy.">?</span>
                    <strong>{selectedImportance ? Number(selectedImportance.score || 0).toFixed(3) : "n/a"}</strong>
                  </div>
                  <div className="insight-metric">
                    <span>Seen impact</span>
                    <span className="tip" title="How much this card correlates with better outcomes when seen by relevant turns.">?</span>
                    <strong>{selectedImpact ? Number(selectedImpact.seen_lift || 0).toFixed(3) : "n/a"}</strong>
                  </div>
                  <div className="insight-metric">
                    <span>Cast impact</span>
                    <span className="tip" title="How much this card correlates with better outcomes when actually cast.">?</span>
                    <strong>{selectedImpact ? Number(selectedImpact.cast_lift || 0).toFixed(3) : "n/a"}</strong>
                  </div>
                  <div className="insight-metric">
                    <span>Centrality</span>
                    <span className="tip" title="How central the card is within simulated successful lines and card network influence.">?</span>
                    <strong>{selectedImpact ? Number(selectedImpact.centrality || 0).toFixed(3) : "n/a"}</strong>
                  </div>
                  <div className="insight-metric">
                    <span>Redundancy</span>
                    <span className="tip" title="How replaceable this card is by similar role cards. Lower means harder to replace.">?</span>
                    <strong>{selectedImpact ? Number(selectedImpact.redundancy || 0).toFixed(3) : "n/a"}</strong>
                  </div>
                </div>

                <a className="btn" href={cardDisplay(selectedCard)?.scryfall_uri || "#"} target="_blank" rel="noreferrer">Open on Scryfall</a>
                <a className="insight-link" href={cardDisplay(selectedCard)?.cardmarket_url || "#"} target="_blank" rel="noreferrer">Open on Cardmarket</a>

                <hr className="insight-sep" />

                <h3 style={{ margin: 0 }}>Strictly Better</h3>
                <p className="control-help">Budget and role constrained replacements only. Existing deck cards are excluded.</p>
                {strictlyBetterLoading ? (
                  <p className="muted">Finding replacements...</p>
                ) : strictlyBetter.length === 0 ? (
                  <p className="muted">No strictly better replacements found under current budget/role constraints.</p>
                ) : (
                  <div className="stack">
                    {strictlyBetter.map((opt: any, idx: number) => (
                      <div key={`${opt.card}-${idx}`} className="insight-option">
                        <button className="btn" onClick={() => setSelectedCard(opt.card)}>
                          {opt.card}
                        </button>
                        <div className="control-help">Price: {opt.price_usd != null ? `$${Number(opt.price_usd).toFixed(2)}` : "n/a"}</div>
                        <ul className="list-compact">
                          {(opt.reasons || []).map((r: string, i: number) => <li key={i}>{r}</li>)}
                        </ul>
                        <div className="row">
                          <a className="insight-link" href={opt.scryfall_uri || "#"} target="_blank" rel="noreferrer">Scryfall</a>
                          <a className="insight-link" href={opt.cardmarket_url || "#"} target="_blank" rel="noreferrer">Cardmarket</a>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <div className="muted">Click any card in analysis tables to open insight.</div>
            )}
          </aside>
        </div>
      </main>

    </div>
  );
}
