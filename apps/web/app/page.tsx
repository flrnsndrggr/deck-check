"use client";

import { Fragment, useEffect, useMemo, useRef, useState } from "react";
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

const RAW_API_BASE = process.env.NEXT_PUBLIC_API_BASE || "";
const DEFAULT_API_BASE = "https://deck-check.onrender.com";

function sanitizeApiBase(raw: string): string {
  const trimmed = raw.trim().replace(/^[\s'"]+|[\s'"]+$/g, "");
  const match = trimmed.match(/https?:\/\/[^\s'"]+/i);
  return (match ? match[0] : trimmed).replace(/\/+$/g, "");
}

const API_BASE = sanitizeApiBase(RAW_API_BASE);

function apiUrl(path: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  const base =
    API_BASE ||
    (typeof window !== "undefined" && window.location.hostname.endsWith("netlify.app")
      ? DEFAULT_API_BASE
      : "");
  if (!base) {
    return normalized;
  }
  if (!/^https?:\/\/[^\s]+$/i.test(base)) {
    throw new Error(`Invalid NEXT_PUBLIC_API_BASE value "${RAW_API_BASE}".`);
  }
  return `${base}${normalized}`;
}
type UrlImportNotice = { tone: "info" | "warn" | "error"; text: string } | null;

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

function pipelineStatusMeta(status: string): { show: boolean; percent: number; label: string; detail: string; tone?: "error" } {
  const trimmed = (status || "").trim().toLowerCase();
  const mapped: Record<string, { percent: number; label: string; detail: string; show?: boolean; tone?: "error" }> = {
    idle: { percent: 0, label: "Idle", detail: "", show: false },
    importing: { percent: 10, label: "Importing deck", detail: "Fetching deck text from the pasted URL." },
    parsing: { percent: 22, label: "Parsing decklist", detail: "Reading sections, quantities, commander, and legality structure." },
    tagging: { percent: 38, label: "Tagging cards", detail: "Applying role tags from card text, type lines, and commander context." },
    "sim-queued": { percent: 50, label: "Queueing simulation", detail: "Preparing the goldfish job and waiting for a worker." },
    "sim-started": { percent: 62, label: "Running simulation", detail: "Goldfishing the deck across many seeded runs." },
    "sim-done": { percent: 72, label: "Simulation complete", detail: "Simulation finished. Preparing the analysis layer." },
    analyzing: { percent: 86, label: "Analyzing results", detail: "Building deck diagnosis, recommendations, and graph payloads." },
    "analysis ready": { percent: 94, label: "Core analysis ready", detail: "Main results are loaded. Final guide text may still be finishing." },
    "building primer": { percent: 97, label: "Building primer", detail: "Generating the play primer and final narrative outputs." },
    done: { percent: 100, label: "Complete", detail: "Deck analysis is fully loaded.", show: false },
    failed: { percent: 100, label: "Run failed", detail: "The last run stopped before analysis completed.", show: false, tone: "error" },
  };
  if (mapped[trimmed]) {
    const row = mapped[trimmed];
    return { show: row.show ?? true, percent: row.percent, label: row.label, detail: row.detail, tone: row.tone };
  }
  if (trimmed.startsWith("sim-")) {
    return {
      show: true,
      percent: 60,
      label: "Running simulation",
      detail: `Worker status: ${status.replace(/^sim-/, "")}.`,
    };
  }
  return { show: false, percent: 0, label: "Idle", detail: "" };
}

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
  const [urlImportNotice, setUrlImportNotice] = useState<UrlImportNotice>(null);
  const [tab, setTab] = useState<(typeof TABS)[number]>("Deck Analysis");
  const [deckAnalysisView, setDeckAnalysisView] = useState<"Overview" | "Combos">("Overview");
  const [bracket, setBracket] = useState(3);
  const [policy, setPolicy] = useState("auto");
  const [simRuns, setSimRuns] = useState(2000);
  const [turnLimit, setTurnLimit] = useState(8);
  const [tablePressure, setTablePressure] = useState(30);
  const [mulliganAggression, setMulliganAggression] = useState(50);
  const [commanderPriority, setCommanderPriority] = useState(50);
  const [budgetMaxUsd, setBudgetMaxUsd] = useState("");
  const [showAdvancedSettings, setShowAdvancedSettings] = useState(false);
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
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(false);
  const [visibleCharts, setVisibleCharts] = useState<Record<string, boolean>>({});
  const chartObserverRef = useRef<IntersectionObserver | null>(null);
  const chartElementsRef = useRef<Record<string, HTMLDivElement | null>>({});
  const visibleChartsRef = useRef<Record<string, boolean>>({});
  const activeRunRef = useRef(0);

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
  const hasOutcomeResources = Boolean(tagRes || simRes || analysis || guides);
  const winMetrics = simRes?.summary?.win_metrics || {};
  const uncertainty = simRes?.summary?.uncertainty || {};
  const fastestWins = simRes?.summary?.fastest_wins || [];
  const comboIntel = analysis?.combo_intel || {};
  const comboComplete = comboIntel?.matched_variants || [];
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
  const progressMeta = useMemo(() => pipelineStatusMeta(status), [status]);
  const selectedImportance = (analysis?.importance || []).find((x: any) => x.card === selectedCard);
  const selectedImpact = selectedCard ? (simRes?.summary?.card_impacts || {})[selectedCard] : null;
  const selectedDisplay = selectedCard ? cardDisplay(selectedCard) : {};
  const insightMetrics = [
    {
      key: "importance",
      label: "Importance score",
      title: "Composite impact score from seen impact, cast impact, graph centrality, and redundancy.",
      value: typeof selectedImportance?.score === "number" ? Number(selectedImportance.score) : null,
    },
    {
      key: "seen",
      label: "Seen impact",
      title: "How much this card correlates with better outcomes when seen by relevant turns.",
      value: selectedImpact && typeof selectedImpact.seen_lift === "number" ? Number(selectedImpact.seen_lift) : null,
    },
    {
      key: "cast",
      label: "Cast impact",
      title: "How much this card correlates with better outcomes when actually cast.",
      value: selectedImpact && typeof selectedImpact.cast_lift === "number" ? Number(selectedImpact.cast_lift) : null,
    },
    {
      key: "centrality",
      label: "Centrality",
      title: "How central the card is within simulated successful lines and card network influence.",
      value: selectedImpact && typeof selectedImpact.centrality === "number" ? Number(selectedImpact.centrality) : null,
    },
    {
      key: "redundancy",
      label: "Redundancy",
      title: "How replaceable this card is by similar role cards. Lower means harder to replace.",
      value: selectedImpact && typeof selectedImpact.redundancy === "number" ? Number(selectedImpact.redundancy) : null,
    },
  ];
  const hasInsightMetrics = insightMetrics.some((m) => m.value !== null);
  const selectedScryfallUrl = String(selectedDisplay?.scryfall_uri || "");
  const selectedCardmarketUrl = String(selectedDisplay?.cardmarket_url || "");
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

  function extractApiErrorMessage(payload: any, fallback: string): string {
    if (!payload) return fallback;
    const detail = payload.detail;
    if (typeof detail === "string" && detail.trim()) return detail;
    if (detail && typeof detail === "object") {
      const core = typeof detail.message === "string" ? detail.message : fallback;
      const guidance = typeof detail.guidance === "string" ? ` ${detail.guidance}` : "";
      return `${core}${guidance}`.trim();
    }
    if (typeof payload.message === "string" && payload.message.trim()) return payload.message;
    return fallback;
  }

  function normalizeUiError(err: any, fallback: string): string {
    const msg = String(err?.message || "").trim();
    if (!msg) return fallback;
    if (/body is disturbed or locked/i.test(msg) || /body stream already read/i.test(msg)) {
      return "Import response could not be read in this browser session. Retry once; if it persists, paste Moxfield text export.";
    }
    return msg;
  }

  function parseBudgetCap(value: string): number | null {
    const trimmed = value.trim();
    if (!trimmed) return null;
    const parsed = Number(trimmed.replace(",", "."));
    if (!Number.isFinite(parsed) || parsed < 0) return null;
    return parsed;
  }

  async function requestJson(path: string, init: RequestInit, stage: string): Promise<any> {
    let response: Response;
    try {
      response = await fetch(apiUrl(path), init);
    } catch (err: any) {
      throw new Error(`${stage}: ${err?.message || "Network request failed."}`);
    }

    let raw = "";
    try {
      raw = await response.text();
    } catch (err: any) {
      const msg = String(err?.message || "").trim();
      if (/body is disturbed or locked/i.test(msg) || /body stream already read/i.test(msg)) {
        throw new Error(`${stage}: response body could not be read. Retry once and paste text export if this persists.`);
      }
      throw new Error(`${stage}: ${msg || "Failed to read response body."}`);
    }
    let payload: any = {};
    if (raw) {
      try {
        payload = JSON.parse(raw);
      } catch {
        if (!response.ok) {
          throw new Error(`${stage} failed (${response.status}).`);
        }
        throw new Error(`${stage} returned invalid JSON.`);
      }
    }

    if (!response.ok) {
      const fallback = `${stage} failed (${response.status}).`;
      throw new Error(extractApiErrorMessage(payload, fallback));
    }
    return payload;
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

  function chartViewportRef(chartKey: string) {
    return (el: HTMLDivElement | null) => {
      chartElementsRef.current[chartKey] = el;
      if (!el) return;
      el.dataset.chartKey = chartKey;
      if (prefersReducedMotion || visibleChartsRef.current[chartKey]) return;
      if (chartObserverRef.current) {
        chartObserverRef.current.observe(el);
      }
    };
  }

  function isChartVisible(chartKey: string) {
    return Boolean(visibleCharts.__all || visibleCharts[chartKey]);
  }

  function chartMotion(chartKey: string, seriesIndex = 0) {
    if (prefersReducedMotion) {
      return {
        isAnimationActive: false as const,
        animationDuration: 0,
        animationBegin: 0,
      };
    }
    const canAnimate = isChartVisible(chartKey);
    return {
      isAnimationActive: canAnimate,
      animationDuration: canAnimate ? 720 : 0,
      animationBegin: canAnimate ? Math.min(seriesIndex * 90, 600) : 0,
      animationEasing: "ease-out" as const,
    };
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

  function renderCardChip(
    name: string,
    key: string,
    options?: { label?: string; width?: number; height?: number; className?: string },
  ) {
    const width = options?.width ?? 24;
    const height = options?.height ?? 34;
    return (
      <button key={key} className={options?.className || "btn card-chip"} onClick={() => setSelectedCard(name)}>
        {cardThumb(name) ? (
          <img src={cardThumb(name)} alt={name} width={width} height={height} loading="lazy" style={{ borderRadius: 4, border: "1px solid #ddd" }} />
        ) : (
          <span style={{ width, height, display: "inline-block", borderRadius: 4, background: "#efefef", border: "1px solid #ddd" }} />
        )}
        <span>{options?.label || name}</span>
      </button>
    );
  }

  function renderCardRow(
    names: string[],
    keyPrefix: string,
    options?: { max?: number; emptyText?: string; labelMap?: Record<string, string> },
  ) {
    const items = (names || [])
      .filter((n) => typeof n === "string" && n.trim().length > 0)
      .slice(0, options?.max ?? (names || []).length);
    if (!items.length) {
      return <p className="muted">{options?.emptyText || "No cards available."}</p>;
    }
    return (
      <div className="card-chip-row">
        {items.map((name, i) =>
          renderCardChip(name, `${keyPrefix}-${i}`, {
            label: options?.labelMap?.[name] || name,
          }),
        )}
      </div>
    );
  }

  function updateStatus(next: string) {
    setStatus(next);
  }

  function setAdvancedMode(next: boolean) {
    setShowAdvancedSettings(next);
    if (!next) {
      setPolicy("auto");
      setTurnLimit(8);
      setTablePressure(30);
      setMulliganAggression(50);
      setCommanderPriority(50);
    }
  }

  async function hydrateDisplay(names: string[]) {
    const toFetch = names.filter((n) => n && !displayMap[n]);
    if (!toFetch.length) return;
    try {
      const q = encodeURIComponent(toFetch.join(","));
      const res = await fetch(apiUrl(`/api/cards/display?names=${q}`));
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
    let comboPieces = 0;
    let tutors = 0;
    let payoffCards = 0;
    let winconCards = 0;
    let voltronCards = 0;
    let controlPieces = 0;
    for (const c of tagPayload?.cards || []) {
      const cardTags = new Set<string>((c.tags || []).map((t: any) => String(t)));
      for (const t of cardTags) tags.add(t);
      if (cardTags.has("#Combo")) comboPieces += 1;
      if (cardTags.has("#Tutor")) tutors += 1;
      if (cardTags.has("#Payoff")) payoffCards += 1;
      if (cardTags.has("#Wincon")) winconCards += 1;
      if (cardTags.has("#Voltron")) voltronCards += 1;
      if (cardTags.has("#Control") || cardTags.has("#Counter") || cardTags.has("#Stax")) controlPieces += 1;
    }
    const arch = tagPayload?.archetype_weights || {};
    const out: string[] = [];

    if (comboPieces >= 3 || (comboPieces >= 2 && tutors >= 1) || (comboPieces >= 2 && num(arch.combo) >= 0.65)) out.push("Combo");
    if (voltronCards >= 2 || num(arch.voltron) >= 0.6) out.push("Commander Damage");
    if (controlPieces >= 4 || num(arch.control) >= 0.6) out.push("Control Lock");
    if (winconCards >= 2 && !out.includes("Combo") && !tags.has("#Voltron")) out.push("Alt Win");
    if (!out.length || tags.has("#Tokens") || payoffCards >= 3 || tags.has("#Payoff")) out.push("Combat");

    return Array.from(new Set(out));
  }

  async function importFromUrl() {
    if (!moxfieldUrl.trim()) return;
    try {
      updateStatus("importing");
      setUrlImportNotice(null);
      const payload = await requestJson(
        "/api/decks/import-url",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url: moxfieldUrl.trim() }),
        },
        "Deck URL import",
      );
      setDecklist(payload.decklist_text);
      setMoxfieldUrl("");
      if (payload.warnings?.length) {
        setUrlImportNotice({
          tone: "warn",
          text: `Imported with warnings: ${payload.warnings.join(" | ")}`,
        });
      } else {
        setUrlImportNotice({ tone: "info", text: "URL import succeeded." });
      }
    } catch (err: any) {
      setUrlImportNotice({
        tone: "error",
        text: normalizeUiError(err, "URL import failed. Paste text export instead."),
      });
    } finally {
      updateStatus("idle");
    }
  }

  async function runPipeline() {
    const runId = activeRunRef.current + 1;
    activeRunRef.current = runId;
    try {
      setSimRes(null);
      setAnalysis(null);
      setGuides(null);
      setSelectedCard(null);
      updateStatus("parsing");
      const parsed = await requestJson(
        "/api/decks/parse",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ decklist_text: decklist, bracket, multiplayer: true }),
        },
        "Deck parse",
      );
      if (activeRunRef.current !== runId) return;
      setParseRes(parsed);

      updateStatus("tagging");
      const tagged = await requestJson(
        "/api/decks/tag",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ cards: parsed.cards, commander: parsed.commander, global_tags: true }),
        },
        "Deck tagging",
      );
      if (activeRunRef.current !== runId) return;
      setTagRes(tagged);
      setDisplayMap(tagged.card_display || {});
      const inferredWincons = inferWinconsFromTagged(tagged);
      setDetectedWincons(inferredWincons);

      updateStatus("sim-queued");
      const effectivePolicy = computeEffectivePolicy();
      const simJob = await requestJson(
        "/api/sim/run",
        {
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
        },
        "Simulation enqueue",
      );
      if (activeRunRef.current !== runId) return;

      let simStatus = "queued";
      let simPayload: any = null;
      const pollStartedAt = Date.now();
      while (!["done", "failed"].includes(simStatus)) {
        if (Date.now() - pollStartedAt > 3 * 60 * 1000) {
          throw new Error("Simulation polling timed out after 3 minutes. Worker may be offline.");
        }
        await new Promise((r) => setTimeout(r, 1000));
        const polled = await requestJson(
          `/api/sim/${simJob.job_id}`,
          { method: "GET" },
          "Simulation status poll",
        );
        if (activeRunRef.current !== runId) return;
        simStatus = polled.status;
        simPayload = polled.result;
        updateStatus(`sim-${simStatus}`);
      }
      if (simStatus === "failed") {
        updateStatus("failed");
        throw new Error(simPayload?.error || "Simulation failed");
      }
      if (activeRunRef.current !== runId) return;
      setSimRes(simPayload);
      if (Array.isArray(simPayload?.summary?.selected_wincons) && simPayload.summary.selected_wincons.length) {
        setDetectedWincons(simPayload.summary.selected_wincons);
      }

      updateStatus("analyzing");
      const ana = await requestJson(
        "/api/analyze",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            cards: tagged.cards,
            commander: parsed.commander,
            bracket,
            template: "balanced",
            budget_max_usd: parseBudgetCap(budgetMaxUsd),
            sim_summary: simPayload.summary,
          }),
        },
        "Deck analysis",
      );
      if (activeRunRef.current !== runId) return;
      setAnalysis(ana);
      setTab("Deck Analysis");
      setDeckAnalysisView("Overview");
      updateStatus("analysis ready");

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
      const intentCards = [
        ...(ana?.intent_summary?.key_support_cards || []),
        ...(ana?.intent_summary?.key_engine_cards || []),
        ...(ana?.intent_summary?.main_wincon_cards || []),
        ...(ana?.intent_summary?.key_interaction_cards || []),
      ].filter((n: any) => typeof n === "string" && n.length > 0);
      const comboLineCards = (ana?.intent_summary?.combo_lines || [])
        .flatMap((line: any) => [...(line?.present_cards || []), ...(line?.missing_cards || [])])
        .filter((n: any) => typeof n === "string" && n.length > 0);
      const comboCatalogCards = [...(ana?.combo_intel?.matched_variants || [])]
        .flatMap((line: any) => [...(line?.present_cards || []), ...(line?.missing_cards || [])])
        .filter((n: any) => typeof n === "string" && n.length > 0);
      const rulesWatchoutCards = (ana?.rules_watchouts || [])
        .map((w: any) => w?.card)
        .filter((n: any) => typeof n === "string" && n.length > 0);
      void hydrateDisplay([
        ...(ana?.importance || []).slice(0, 20).map((x: any) => x.card),
        ...(ana?.adds || []).slice(0, 20).map((x: any) => x.card),
        ...(ana?.cuts || []).slice(0, 20).map((x: any) => x.card),
        ...bracketCriteriaCards,
        ...manabaseSourceCards,
        ...manabaseDemandCards,
        ...curveCards,
        ...fastestWinCards,
        ...intentCards,
        ...comboLineCards,
        ...comboCatalogCards,
        ...rulesWatchoutCards,
      ]);

      void (async () => {
        try {
          updateStatus("building primer");
          const gd = await requestJson(
            "/api/guides/generate",
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ analyze: ana, sim_summary: simPayload.summary }),
            },
            "Guide generation",
          );
          if (activeRunRef.current !== runId) return;
          setGuides(gd);
          updateStatus("done");
        } catch {
          if (activeRunRef.current !== runId) return;
          updateStatus("analysis ready");
        }
      })();
    } catch (err: any) {
      updateStatus("failed");
      alert(normalizeUiError(err, "Run failed"));
    }
  }

  useEffect(() => {
    if (!selectedCard) return;
    void hydrateDisplay([selectedCard]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCard]);

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setPrefersReducedMotion(media.matches);
    sync();
    if (typeof media.addEventListener === "function") {
      media.addEventListener("change", sync);
      return () => media.removeEventListener("change", sync);
    }
    media.addListener(sync);
    return () => media.removeListener(sync);
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (prefersReducedMotion) {
      setVisibleCharts({});
      visibleChartsRef.current = {};
      chartObserverRef.current?.disconnect();
      chartObserverRef.current = null;
      return;
    }

    if (!("IntersectionObserver" in window)) {
      setVisibleCharts({ __all: true });
      visibleChartsRef.current = { __all: true };
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting && entry.intersectionRatio <= 0) continue;
          const key = (entry.target as HTMLElement).dataset.chartKey;
          if (!key || visibleChartsRef.current[key]) continue;
          visibleChartsRef.current = { ...visibleChartsRef.current, [key]: true };
          setVisibleCharts((prev) => (prev[key] ? prev : { ...prev, [key]: true }));
          observer.unobserve(entry.target);
        }
      },
      { threshold: 0.2, rootMargin: "0px 0px -12% 0px" },
    );

    chartObserverRef.current = observer;
    Object.entries(chartElementsRef.current).forEach(([key, el]) => {
      if (el && !visibleChartsRef.current[key]) observer.observe(el);
    });

    return () => {
      observer.disconnect();
      if (chartObserverRef.current === observer) {
        chartObserverRef.current = null;
      }
    };
  }, [prefersReducedMotion, tab]);

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
        const res = await fetch(apiUrl("/api/cards/strictly-better"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            cards: tagRes.cards,
            selected_card: selectedCard,
            commander: parseRes?.commander,
            budget_max_usd: parseBudgetCap(budgetMaxUsd),
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
        const res = await fetch(apiUrl("/api/meta/updates"));
        if (!res.ok) return;
        const payload = await res.json();
        setUpdatesMeta(payload);
      } catch {
        return;
      }
    })();

    void (async () => {
      try {
        const res = await fetch(apiUrl("/api/meta/integrations"));
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
          {urlImportNotice ? <p className={`import-notice import-notice-${urlImportNotice.tone}`}>{urlImportNotice.text}</p> : null}
        </div>

        <div className="block stack">
          <label>Bracket</label>
          <select className="select" value={bracket} onChange={(e) => setBracket(Number(e.target.value))}>
            {[1, 2, 3, 4, 5].map((b) => (
              <option key={b} value={b}>{b}</option>
            ))}
          </select>
          <p className="control-help">Use the bracket that best matches your table’s speed and expectations.</p>

          <label>Simulation Runs: {simRuns}</label>
          <p className="control-help">More runs make the results steadier. 2,000 is a good default.</p>
          <input
            className="slider"
            type="range"
            min={500}
            max={10000}
            step={500}
            value={simRuns}
            onChange={(e) => setSimRuns(Number(e.target.value))}
          />

          <label>Budget Cap (USD/card)</label>
          <p className="control-help">Only affects suggested adds. Leave blank for no budget filter.</p>
          <input
            className="input"
            type="text"
            inputMode="decimal"
            value={budgetMaxUsd}
            onChange={(e) => setBudgetMaxUsd(e.target.value)}
            placeholder="e.g. 10"
          />

          <label className="setting-toggle" htmlFor="advanced-settings-toggle">
            <span>
              <strong>Advanced settings</strong>
              <span className="control-help setting-toggle-help">Show tuning controls for sim style and matchup assumptions.</span>
            </span>
            <input
              id="advanced-settings-toggle"
              type="checkbox"
              checked={showAdvancedSettings}
              onChange={(e) => setAdvancedMode(e.target.checked)}
            />
          </label>

          {showAdvancedSettings ? (
            <div className="advanced-settings stack">
              <label>Simulation Style</label>
              <select className="select" value={policy} onChange={(e) => setPolicy(e.target.value)}>
                <option value="auto">Auto</option>
                <option value="casual">Casual value</option>
                <option value="optimized">Optimized mid-power</option>
                <option value="cedh">cEDH-like speed</option>
                <option value="commander-centric">Commander-centric</option>
                <option value="hold commander">Hold commander</option>
              </select>
              <p className="control-help">
                Auto is recommended. Effective style right now: <strong>{computeEffectivePolicy()}</strong>.
              </p>

              <label>Turn Limit: {turnLimit}</label>
              <p className="control-help">Increase this for slower decks that usually win later than turn 8.</p>
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
              <p className="control-help">How often the sim assumes opponents force you to spend interaction.</p>
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
              <p className="control-help">Higher keeps faster, riskier hands. Lower keeps steadier hands.</p>
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
              <p className="control-help">Higher casts commander earlier. Lower develops the board first.</p>
              <input
                className="slider"
                type="range"
                min={0}
                max={100}
                step={10}
                value={commanderPriority}
                onChange={(e) => setCommanderPriority(Number(e.target.value))}
              />
            </div>
          ) : (
            <p className="control-help">Advanced mode is off. Deck.Check is using sensible defaults behind the scenes.</p>
          )}

          <button className="btn btn-primary" onClick={runPipeline}>Run Full Analysis</button>
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
                <div className="mini-label">Deck legality</div>
                <div className={`mini-value ${(parseRes?.errors || []).length === 0 ? "tone-good" : "tone-bad"}`}>
                  {(parseRes?.errors || []).length === 0 ? "Legal" : String((parseRes?.errors || [])[0] || "Illegal")}
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

            {progressMeta.show ? (
              <div className="deck-progress">
                <div className="deck-progress-head">
                  <strong>{progressMeta.label}</strong>
                  <span>{progressMeta.percent}%</span>
                </div>
                <div className="deck-progress-track" aria-hidden="true">
                  <div
                    className={`deck-progress-fill ${progressMeta.tone === "error" ? "is-error" : ""}`}
                    style={{ width: `${progressMeta.percent}%` }}
                  />
                </div>
                <p className="control-help">{progressMeta.detail}</p>
              </div>
            ) : null}

            {(tagRes?.cards || []).length > 0 && (
              <div>
                <strong>Card Preview</strong>
                <div className="card-preview-scroll">
                  <table className="table" style={{ marginTop: 6 }}>
                    <thead>
                      <tr><th>Card</th><th>Role hint</th></tr>
                    </thead>
                    <tbody>
                      {(tagRes?.cards || []).map((c: any, i: number) => {
                        const isCommanderCard = c?.section === "commander" || c?.name === parseRes?.commander;
                        return (
                        <tr
                          key={`${c.name}-${i}`}
                          onClick={() => setSelectedCard(c.name)}
                          className={`card-preview-row ${isCommanderCard ? "is-commander" : ""}`}
                          style={{ cursor: "pointer" }}
                        >
                          <td style={{ display: "flex", alignItems: "center", gap: 8 }}>
                            {cardThumb(c.name) ? (
                              <img src={cardThumb(c.name)} alt={c.name} width={30} height={42} loading="lazy" style={{ borderRadius: 4, border: "1px solid #ddd" }} />
                            ) : (
                              <div style={{ width: 30, height: 42, borderRadius: 4, background: "#efefef", border: "1px solid #ddd" }} />
                            )}
                            <span className="card-preview-name">
                              {c.name}
                              {isCommanderCard ? <span className="card-preview-badge">Commander</span> : null}
                            </span>
                          </td>
                          <td>{(c.tags || []).slice(0, 2).join(", ") || "n/a"}</td>
                        </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
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
          <h3>{hasOutcomeResources ? tab : "View Panel"}</h3>
          <p className="muted">
            {hasOutcomeResources
              ? `Outcomes and findings for the selected run. Status: ${status}`
              : "No view resources loaded yet. Run Full Analysis to fetch card data, simulation output, and derived reports for this panel."}
          </p>
          {hasOutcomeResources ? (
            <div className="tab-list" style={{ marginTop: 4, display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 6 }}>
              {TABS.map((t) => (
                <button key={t} className={`btn tab-btn ${tab === t ? "active" : ""}`} onClick={() => setTab(t)}>{t}</button>
              ))}
            </div>
          ) : null}
        </div>

        <div className="block">
          {!hasOutcomeResources ? (
            <div className="resource-empty-state">
              <h2>Nothing to show yet</h2>
              <p>
                This panel stays empty until the app has the resources it needs: fetched card data, goldfish simulation results,
                and derived analysis outputs.
              </p>
              <p className="muted">Run Full Analysis to populate the views.</p>
            </div>
          ) : (
            <>
          {tab === "Deck Analysis" && (
            <div className="guide-rendered">
              <div className="row" style={{ marginBottom: 8, gap: 6, flexWrap: "wrap" }}>
                <button className={`btn ${deckAnalysisView === "Overview" ? "active" : ""}`} onClick={() => setDeckAnalysisView("Overview")}>
                  Overview
                </button>
                <button className={`btn ${deckAnalysisView === "Combos" ? "active" : ""}`} onClick={() => setDeckAnalysisView("Combos")}>
                  Combos
                </button>
              </div>
              {deckAnalysisView === "Overview" ? (
                <>
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
              <p><strong>Complete combos in list:</strong> {comboComplete.length}</p>
              {comboIntel?.fetched_at ? <p className="control-help">CommanderSpellbook fetched: {new Date(comboIntel.fetched_at).toLocaleString()}</p> : null}
              <p className="control-help">
                Use the <strong>Combos</strong> view above for the full CommanderSpellbook catalog of complete combo lines already contained in this deck.
              </p>

              <h3>Key Support Cards</h3>
              {renderCardRow((intentSummary?.key_support_cards || []).slice(0, 8), "intent-support", {
                emptyText: "No support cards detected.",
              })}

              <h3>Engine Cards</h3>
              {renderCardRow((intentSummary?.key_engine_cards || []).slice(0, 8), "intent-engine", {
                emptyText: "No engine cards detected.",
              })}

              <h3>Main Wincons</h3>
              {renderCardRow((intentSummary?.main_wincon_cards || []).slice(0, 8), "intent-wincon", {
                emptyText: "No wincon cards detected.",
              })}

              <h3>Key Interaction</h3>
              {renderCardRow((intentSummary?.key_interaction_cards || []).slice(0, 8), "intent-interaction", {
                emptyText: "No key interaction cards detected.",
              })}

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
              {renderCardRow(
                topImportance.slice(0, 8).map((c: any) => c.card),
                "analysis-top-importance",
                {
                  emptyText: "No impact cards available.",
                  labelMap: Object.fromEntries(
                    topImportance.slice(0, 8).map((c: any) => [c.card, `${c.card} (${(c.score ?? 0).toFixed(3)})`]),
                  ),
                },
              )}

              <h2>Data Provenance</h2>
              <ul>
                {(integrationsMeta?.integrations || []).map((i: any, idx: number) => (
                  <li key={idx}>
                    <strong>{i.key}</strong> ({i.status}): {i.purpose} <a href={i.url} target="_blank" rel="noreferrer">[source]</a>
                  </li>
                ))}
              </ul>
                </>
              ) : (
                <div className="stack">
                  <h2>CommanderSpellbook Combo Catalog</h2>
                  <p className="muted">
                    This view only shows CommanderSpellbook combos where every named piece is already in the decklist.
                    It is deck-construction evidence, not proof that the line is assembled, protected, and resolved on curve.
                  </p>

                  <div className="kpi-grid">
                    <div className="mini-card">
                      <div className="mini-label">Complete lines</div>
                      <div className="mini-value tone-good">{comboComplete.length}</div>
                      <div className="control-help">Known combo variants already fully contained in this decklist.</div>
                    </div>
                    <div className="mini-card">
                      <div className="mini-label">Combo support score</div>
                      <div className="mini-value">{comboIntel?.combo_support_score ?? 0} / 100</div>
                      <div className="control-help">Higher means more complete CommanderSpellbook lines are already contained in the list.</div>
                    </div>
                    <div className="mini-card">
                      <div className="mini-label">Source timestamp</div>
                      <div className="mini-value">{comboIntel?.fetched_at ? "Live" : "Unknown"}</div>
                      <div className="control-help">
                        {comboIntel?.fetched_at ? new Date(comboIntel.fetched_at).toLocaleString() : "No fetch timestamp recorded."}
                      </div>
                    </div>
                  </div>

                  {comboIntel?.warnings?.length > 0 && (
                    <div className="block">
                      <strong>Source warnings</strong>
                      <ul className="list-compact">
                        {comboIntel.warnings.map((w: string, i: number) => <li key={i}>{w}</li>)}
                      </ul>
                    </div>
                  )}

                  <div className="stack">
                    <h3>Complete Combos In This Deck</h3>
                    {comboComplete.length === 0 ? (
                      <p className="muted">No complete CommanderSpellbook combo lines detected in the current list.</p>
                    ) : (
                      comboComplete.map((variant: any, i: number) => (
                        <div key={`combo-complete-${variant?.variant_id || i}`} className="block combo-variant-card">
                          <div className="combo-variant-header">
                            <div className="stack" style={{ gap: 4 }}>
                              <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
                                <span className="combo-badge combo-badge-complete">Complete</span>
                                <strong>{variant?.variant_id || `Combo ${i + 1}`}</strong>
                                {variant?.identity ? <span className="control-help">Identity: {variant.identity}</span> : null}
                              </div>
                              <div className="control-help">
                                Coverage {Math.round((Number(variant?.card_coverage || 0) || 0) * 100)}% · Missing {variant?.missing_count || 0} · Score {(Number(variant?.score || 0) || 0).toFixed(2)}
                              </div>
                            </div>
                            {variant?.source_url ? (
                              <a href={variant.source_url} target="_blank" rel="noreferrer">Open on CommanderSpellbook</a>
                            ) : null}
                          </div>
                          {variant?.recipe ? <p className="control-help">{variant.recipe}</p> : null}
                          <div className="control-help">Cards in this line</div>
                          {renderCardRow(variant?.cards || [], `combo-complete-all-${i}`, {
                            emptyText: "No cards listed for this combo.",
                          })}
                        </div>
                      ))
                    )}
                  </div>
                </div>
              )}
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
              <div ref={chartViewportRef("lenses-mana-percentiles")} style={{ width: "100%", height: 230 }}>
                <ResponsiveContainer>
                  <LineChart data={graphPayloads?.mana_percentiles || []}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="turn" label={{ value: "Turn", position: "insideBottom", offset: -2 }} />
                    <YAxis label={{ value: "Mana sources", angle: -90, position: "insideLeft" }} />
                    <Tooltip />
                    <Line {...chartMotion("lenses-mana-percentiles", 0)} type="monotone" dataKey="p50" stroke="#111" strokeWidth={2} />
                    <Line {...chartMotion("lenses-mana-percentiles", 1)} type="monotone" dataKey="p75" stroke="#555" strokeWidth={2} />
                    <Line {...chartMotion("lenses-mana-percentiles", 2)} type="monotone" dataKey="p90" stroke="#999" strokeWidth={2} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("mana_percentiles")}

              {renderMetricHelp("land_hit_cdf")}
              <div ref={chartViewportRef("lenses-land-hit-cdf")} style={{ width: "100%", height: 220 }}>
                <ResponsiveContainer>
                  <LineChart data={graphPayloads?.land_hit_cdf || []}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="turn" label={{ value: "Turn", position: "insideBottom", offset: -2 }} />
                    <YAxis domain={[0, 1]} label={{ value: "Probability", angle: -90, position: "insideLeft" }} />
                    <Tooltip formatter={(v: any) => `${(Number(v) * 100).toFixed(1)}%`} />
                    <Line {...chartMotion("lenses-land-hit-cdf", 0)} type="monotone" dataKey="p_hit_on_curve" stroke="#111" strokeWidth={2.5} />
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
                <div ref={chartViewportRef("lenses-color-access")} style={{ width: "100%", height: 240 }}>
                  <ResponsiveContainer>
                    <LineChart data={graphPayloads?.color_access || []}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="turn" label={{ value: "Turn", position: "insideBottom", offset: -2 }} />
                      <YAxis yAxisId="left" domain={[0, Math.max(2, colorIdentitySize)]} label={{ value: "Colors online", angle: -90, position: "insideLeft" }} />
                      <YAxis yAxisId="right" orientation="right" domain={[0, 1]} label={{ value: "P(full identity)", angle: 90, position: "insideRight" }} />
                      <Tooltip formatter={(v: any, k: any) => (String(k).includes("p_") ? `${(Number(v) * 100).toFixed(1)}%` : Number(v).toFixed(2))} />
                      <Legend />
                      <Line {...chartMotion("lenses-color-access", 0)} yAxisId="left" type="monotone" dataKey="avg_colors" stroke="#333" strokeWidth={2.4} name="Avg colors online" />
                      <Line {...chartMotion("lenses-color-access", 1)} yAxisId="right" type="monotone" dataKey="p_full_identity" stroke="#7a7a7a" strokeWidth={2} name="P(full identity online)" />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
              {renderDeckBlurb("color_access")}

              <h2>Plan Execution Lens</h2>
              {renderMetricHelp("phase_timeline")}
              <div ref={chartViewportRef("lenses-phase-timeline")} style={{ width: "100%", height: 260 }}>
                <ResponsiveContainer>
                  <AreaChart data={graphPayloads?.phase_timeline || []}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="turn" label={{ value: "Turn", position: "insideBottom", offset: -2 }} />
                    <YAxis domain={[0, 1]} label={{ value: "Share of games", angle: -90, position: "insideLeft" }} />
                    <Tooltip formatter={(v: any) => `${(Number(v) * 100).toFixed(1)}%`} />
                    <Legend />
                    <Area {...chartMotion("lenses-phase-timeline", 0)} type="monotone" dataKey="setup" stackId="1" stroke="#bbb" fill="#d8d8d8" />
                    <Area {...chartMotion("lenses-phase-timeline", 1)} type="monotone" dataKey="engine" stackId="1" stroke="#888" fill="#b7b7b7" />
                    <Area {...chartMotion("lenses-phase-timeline", 2)} type="monotone" dataKey="win_attempt" stackId="1" stroke="#333" fill="#6e6e6e" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("phase_timeline")}

              {renderMetricHelp("win_turn_cdf")}
              <div ref={chartViewportRef("lenses-win-turn-cdf")} style={{ width: "100%", height: 220 }}>
                <ResponsiveContainer>
                  <LineChart data={graphPayloads?.win_turn_cdf || []}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="turn" label={{ value: "Turn", position: "insideBottom", offset: -2 }} />
                    <YAxis domain={[0, 1]} label={{ value: "Cumulative probability", angle: -90, position: "insideLeft" }} />
                    <Tooltip formatter={(v: any) => `${(Number(v) * 100).toFixed(1)}%`} />
                    <Line {...chartMotion("lenses-win-turn-cdf", 0)} type="monotone" dataKey="cdf" stroke="#111" strokeWidth={2.5} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("win_turn_cdf")}

              <h2>Risk Lens</h2>
              {renderMetricHelp("no_action_funnel")}
              <div ref={chartViewportRef("lenses-no-action-funnel")} style={{ width: "100%", height: 220 }}>
                <ResponsiveContainer>
                  <LineChart data={graphPayloads?.no_action_funnel || []}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="turn" label={{ value: "Turn", position: "insideBottom", offset: -2 }} />
                    <YAxis domain={[0, 1]} label={{ value: "No-action probability", angle: -90, position: "insideLeft" }} />
                    <Tooltip formatter={(v: any) => `${(Number(v) * 100).toFixed(1)}%`} />
                    <Line {...chartMotion("lenses-no-action-funnel", 0)} type="monotone" dataKey="p_no_action" stroke="#8a1e1e" strokeWidth={2.5} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("no_action_funnel")}

              {renderMetricHelp("dead_cards_top")}
              <div ref={chartViewportRef("lenses-dead-cards-top")} style={{ width: "100%", height: 260 }}>
                <ResponsiveContainer>
                  <BarChart data={(graphPayloads?.dead_cards_top || []).slice(0, 10)}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="card" hide />
                    <YAxis label={{ value: "Stranded rate", angle: -90, position: "insideLeft" }} />
                    <Tooltip formatter={(v: any) => `${(Number(v) * 100).toFixed(1)}%`} />
                    <Bar {...chartMotion("lenses-dead-cards-top", 0)} dataKey="rate" fill="#444" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("dead_cards_top")}

              <h2>Operational Lens</h2>
              {renderMetricHelp("commander_cast_distribution")}
              <div ref={chartViewportRef("lenses-commander-cast")} style={{ width: "100%", height: 220 }}>
                <ResponsiveContainer>
                  <BarChart data={graphPayloads?.commander_cast_distribution || []}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="turn" label={{ value: "Cast turn", position: "insideBottom", offset: -2 }} />
                    <YAxis label={{ value: "Rate", angle: -90, position: "insideLeft" }} />
                    <Tooltip formatter={(v: any) => `${(Number(v) * 100).toFixed(1)}%`} />
                    <Bar {...chartMotion("lenses-commander-cast", 0)} dataKey="rate" fill="#111" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("commander_cast_distribution")}
              {renderMetricHelp("mulligan_funnel")}
              <div ref={chartViewportRef("lenses-mulligan-funnel")} style={{ width: "100%", height: 220 }}>
                <ResponsiveContainer>
                  <BarChart data={graphPayloads?.mulligan_funnel || []}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="mulligans" label={{ value: "Mulligans taken", position: "insideBottom", offset: -2 }} />
                    <YAxis label={{ value: "Rate", angle: -90, position: "insideLeft" }} />
                    <Tooltip formatter={(v: any) => `${(Number(v) * 100).toFixed(1)}%`} />
                    <Bar {...chartMotion("lenses-mulligan-funnel", 0)} dataKey="rate" fill="#666" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("mulligan_funnel")}

              <h2>Complex Systems Metrics</h2>
              <p className="muted">Adapted from systems analysis: resilience, redundancy, bottlenecks, and impact concentration for deck robustness.</p>
              <div ref={chartViewportRef("lenses-systems-metrics")} style={{ width: "100%", height: 220 }}>
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
                    <Bar {...chartMotion("lenses-systems-metrics", 0)} dataKey="value" fill="#2f2f2f" />
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
                        {renderCardChip(w.card, `watchout-${i}`, { width: 20, height: 28 })}
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
                              <div className="card-chip-row">
                                {(row.cards || []).map((x: any, idx: number) =>
                                  renderCardChip(x.name, `${row.role}-${x.name}-${idx}`, {
                                    label: `${x.qty}x ${x.name}`,
                                  }),
                                )}
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
              <div ref={chartViewportRef("manabase-pip-distribution")} style={{ width: "100%", height: 260 }}>
                <ResponsiveContainer>
                  <BarChart data={graphPayloads?.manabase_pip_distribution || []}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="color" label={{ value: "Color", position: "insideBottom", offset: -2 }} />
                    <YAxis label={{ value: "Pip demand", angle: -90, position: "insideLeft" }} />
                    <Tooltip formatter={(v: any) => Number(v).toFixed(2)} />
                    <Legend />
                    <Bar {...chartMotion("manabase-pip-distribution", 0)} dataKey="early" stackId="pips" fill="#9a9a9a" name="Early (MV<=2)" />
                    <Bar {...chartMotion("manabase-pip-distribution", 1)} dataKey="mid" stackId="pips" fill="#707070" name="Mid (MV3-4)" />
                    <Bar {...chartMotion("manabase-pip-distribution", 2)} dataKey="late" stackId="pips" fill="#3a3a3a" name="Late (MV5+)" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("manabase_pip_distribution")}

              <h2>Source Coverage by Color</h2>
              {renderMetricHelp("manabase_source_coverage")}
              <div ref={chartViewportRef("manabase-source-coverage")} style={{ width: "100%", height: 260 }}>
                <ResponsiveContainer>
                  <BarChart data={graphPayloads?.manabase_source_coverage || []}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="color" label={{ value: "Color", position: "insideBottom", offset: -2 }} />
                    <YAxis label={{ value: "Source count", angle: -90, position: "insideLeft" }} />
                    <Tooltip formatter={(v: any) => Number(v).toFixed(2)} />
                    <Legend />
                    <Bar {...chartMotion("manabase-source-coverage", 0)} dataKey="land_sources" stackId="src" fill="#4b4b4b" name="Land sources" />
                    <Bar {...chartMotion("manabase-source-coverage", 1)} dataKey="nonland_sources" stackId="src" fill="#9b9b9b" name="Nonland sources" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("manabase_source_coverage")}

              <h2>Demand vs Supply Gap</h2>
              {renderMetricHelp("manabase_balance_gap")}
              <div ref={chartViewportRef("manabase-balance-gap")} style={{ width: "100%", height: 260 }}>
                <ResponsiveContainer>
                  <BarChart data={graphPayloads?.manabase_balance_gap || []}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="color" label={{ value: "Color", position: "insideBottom", offset: -2 }} />
                    <YAxis label={{ value: "Share", angle: -90, position: "insideLeft" }} />
                    <Tooltip formatter={(v: any) => `${(Number(v) * 100).toFixed(1)}%`} />
                    <Legend />
                    <Bar {...chartMotion("manabase-balance-gap", 0)} dataKey="demand_share" fill="#2d2d2d" name="Demand share" />
                    <Bar {...chartMotion("manabase-balance-gap", 1)} dataKey="source_share" fill="#8a8a8a" name="Source share" />
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
              <div ref={chartViewportRef("manabase-curve-histogram")} style={{ width: "100%", height: 280 }}>
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
                      {...chartMotion("manabase-curve-histogram", 0)}
                      yAxisId="left"
                      dataKey="permanents"
                      stackId="curve"
                      fill="#7f7f7f"
                      name="Permanents"
                      onClick={(d: any) => setSelectedCurveMv(Number(d?.mana_value ?? 0))}
                    />
                    <Bar
                      {...chartMotion("manabase-curve-histogram", 1)}
                      yAxisId="left"
                      dataKey="spells"
                      stackId="curve"
                      fill="#b5b5b5"
                      name="Spells"
                      onClick={(d: any) => setSelectedCurveMv(Number(d?.mana_value ?? 0))}
                    />
                    <Line {...chartMotion("manabase-curve-histogram", 2)} yAxisId="right" type="monotone" dataKey="p_on_curve_est" stroke="#111" strokeWidth={2} dot={{ r: 2 }} name="Estimated P(on curve)" />
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
              <div ref={chartViewportRef("goldfish-plan-progress")} style={{ width: "100%", height: 260 }}>
                <ResponsiveContainer>
                  <LineChart data={chartData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="turn" label={{ value: "Turn", position: "insideBottom", offset: -2 }} />
                    <YAxis label={{ value: "Plan progress score", angle: -90, position: "insideLeft" }} />
                    <Tooltip />
                    <Line {...chartMotion("goldfish-plan-progress", 0)} type="monotone" dataKey="median" stroke="#111" strokeWidth={2.5} />
                    <Line {...chartMotion("goldfish-plan-progress", 1)} type="monotone" dataKey="p90" stroke="#8a8a8a" strokeWidth={2} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("plan_progress")}

              <h2>Failure Mode Rates</h2>
              {renderMetricHelp("failure_rates")}
              <div ref={chartViewportRef("goldfish-failure-rates")} style={{ width: "100%", height: 220 }}>
                <ResponsiveContainer>
                  <BarChart data={failureData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" label={{ value: "Failure type", position: "insideBottom", offset: -2 }} />
                    <YAxis label={{ value: "Percent of runs", angle: -90, position: "insideLeft" }} />
                    <Tooltip formatter={(v: any) => `${Number(v).toFixed(1)}%`} />
                    <Bar {...chartMotion("goldfish-failure-rates", 0)} dataKey="value" fill="#444" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("failure_rates")}

              <h2>Wincon Outcomes</h2>
              {renderMetricHelp("wincon_outcomes")}
              <div ref={chartViewportRef("goldfish-wincon-outcomes")} style={{ width: "100%", height: 220 }}>
                <ResponsiveContainer>
                  <BarChart data={winconData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" label={{ value: "Win route", position: "insideBottom", offset: -2 }} />
                    <YAxis label={{ value: "Percent of runs", angle: -90, position: "insideLeft" }} />
                    <Tooltip formatter={(v: any) => `${Number(v).toFixed(1)}%`} />
                    <Bar {...chartMotion("goldfish-wincon-outcomes", 0)} dataKey="value" fill="#111" />
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
                      {fw?.win_reason ? <p className="deck-blurb" style={{ marginTop: -4 }}>Why this counted as a win: {fw.win_reason}</p> : null}

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
                                {t?.win_reason ? <div className="control-help">{t.win_reason}</div> : null}
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
              <div ref={chartViewportRef("importance-top-chart")} style={{ width: "100%", height: 240 }}>
                <ResponsiveContainer>
                  <BarChart data={importanceChartData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="card" hide />
                    <YAxis label={{ value: "Importance score", angle: -90, position: "insideLeft" }} />
                    <Tooltip formatter={(v: any) => Number(v).toFixed(3)} />
                    <Bar {...chartMotion("importance-top-chart", 0)} dataKey="score" fill="#222" />
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
                        {renderCardChip(c.card, `deadweight-${i}`)}
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
                  <div className="stack">
                    {comboNearMiss.slice(0, 5).map((v: any, i: number) => (
                      <div key={i} className="block">
                        <div><strong>{v.variant_id}</strong></div>
                        <div className="control-help">
                          Add the missing pieces below to complete this near-miss line.
                        </div>
                        {renderCardRow((v?.missing_cards || []).slice(0, 4), `opt-nearmiss-${i}`, {
                          emptyText: "No missing cards listed.",
                        })}
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}

          {tab === "Primer" && (
            <div className="guide-rendered">
              <ReactMarkdown>{guides?.play_guide_md || "Run analysis first."}</ReactMarkdown>
            </div>
          )}
            </>
          )}
        </div>
          </div>
          <aside className={`card-insight ${selectedCard ? "open" : ""}`}>
            {selectedCard ? (
              <div className="stack">
                <div className="insight-header">
                  <h3 className="insight-title">{selectedCard}</h3>
                  <button className="insight-close" aria-label="Close card insight" onClick={() => setSelectedCard(null)}>
                    x
                  </button>
                </div>
                {selectedDisplay?.normal ? (
                  <img
                    src={selectedDisplay?.normal}
                    alt={selectedCard}
                    width={290}
                    height={405}
                    loading="lazy"
                    style={{ width: "100%", height: "auto", borderRadius: 8, border: "1px solid #ddd" }}
                  />
                ) : (
                  <div style={{ width: "100%", aspectRatio: "146 / 204", borderRadius: 8, background: "#efefef", border: "1px solid #ddd" }} />
                )}

                {hasInsightMetrics ? (
                  <div className="stack">
                    {insightMetrics.map((metric) => (
                      <div key={metric.key} className="insight-metric">
                        <span>{metric.label}</span>
                        <span className="tip" title={metric.title}>?</span>
                        <strong>{metric.value == null ? "n/a" : metric.value.toFixed(3)}</strong>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="insight-no-metrics">
                    Card-level simulation metrics are not available for this card in the current run. This usually means it was not part of the sampled impact set.
                  </div>
                )}

                <div className="insight-actions">
                  {selectedScryfallUrl ? (
                    <a className="btn insight-btn" href={selectedScryfallUrl} target="_blank" rel="noreferrer">Open on Scryfall</a>
                  ) : (
                    <span className="btn insight-btn disabled">Scryfall unavailable</span>
                  )}
                  {selectedCardmarketUrl ? (
                    <a className="btn insight-btn" href={selectedCardmarketUrl} target="_blank" rel="noreferrer">Open on Cardmarket</a>
                  ) : (
                    <span className="btn insight-btn disabled">Cardmarket unavailable</span>
                  )}
                </div>

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
                        {renderCardChip(opt.card, `strictly-better-${idx}`)}
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
