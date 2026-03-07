"use client";

import { Fragment, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { useSearchParams } from "next/navigation";
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
import { chartTheme, resolveTheme, type ResolvedTheme } from "./theme";
import { ManaText } from "./mana-symbols";

const RAW_API_BASE = process.env.NEXT_PUBLIC_API_BASE || "";
const DEFAULT_API_BASE = "https://deck-check.onrender.com";
const AUTH_CSRF_STORAGE_KEY = "deckcheck.csrf";
const LOCAL_DRAFT_STORAGE_KEY = "deckcheck.local-draft.v1";

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
  "Combos",
  "Lenses",
  "Role Breakdown",
  "Mana Base",
  "Goldfish Report",
  "Fastest Wins",
  "Card Importance",
  "Optimization",
  "Rule 0",
  "Primer",
  "Rules Watchouts",
] as const;
type TabName = (typeof TABS)[number];
const TAB_GROUPS = [
  { label: "Summary", tabs: ["Deck Analysis"] },
  { label: "Improve", tabs: ["Optimization", "Role Breakdown", "Mana Base", "Card Importance"] },
  { label: "Play Prep", tabs: ["Goldfish Report", "Fastest Wins", "Rule 0", "Primer"] },
  { label: "Reference", tabs: ["Combos", "Rules Watchouts", "Lenses"] },
] as const satisfies ReadonlyArray<{ label: string; tabs: readonly TabName[] }>;
type TabGroupName = (typeof TAB_GROUPS)[number]["label"];
const TAB_TO_GROUP = Object.fromEntries(
  TAB_GROUPS.flatMap((group) => group.tabs.map((tab) => [tab, group.label])),
) as Record<TabName, TabGroupName>;
const TAG_ONLY_TABS = ["Role Breakdown", "Combos", "Rules Watchouts"] as const;

const ART_PREFERENCE_OPTIONS = [
  {
    value: "original",
    label: "Original Printing",
    description: "Best for nostalgia and card-history purists. Uses the earliest non-UB paper printing when possible.",
  },
  {
    value: "classic",
    label: "Classic Frame",
    description: "Best for old-school aesthetics. Prefers old-border or older-frame printings when they exist.",
  },
  {
    value: "clean",
    label: "Clean Modern",
    description: "Best for readability. Prefers modern regular-frame non-UB printings.",
  },
  {
    value: "showcase",
    label: "Showcase Art",
    description: "Best for art-first players. Prefers borderless, full-art, and showcase treatments when available.",
  },
  {
    value: "newest",
    label: "Newest Printing",
    description: "Best if you want the current look. Prefers the most recent non-UB paper printing.",
  },
] as const;

const MINI_CARD_HELP: Record<string, string> = {
  commander: "The commander, or commander pair, the deck is built around.",
  "card count": "How many total cards were parsed from the list. A normal Commander deck should end up at 100 cards including the commander.",
  "deck legality": "Whether the current list passes the hard legality and construction checks needed to analyze it.",
  "auto win plans": "The main ways Deck.Check thinks this deck is trying to win, based on cards, tags, and combo evidence.",
  "color identity": "The colors your commander allows. Recommendations and legal cards must stay inside this identity.",
  "signed in as": "The account currently active in this browser session.",
  "inferred bracket": "Deck.Check's estimate of the deck's Commander bracket based on speed, tutors, fast mana, combo density, and other power signals.",
  "complete lines": "How many full combo lines are already fully contained in the deck.",
  "combo support score": "A rough score for how much complete combo support is already present in the list.",
  "one-card-away lines": "How many legal combo lines are missing exactly one card from the deck.",
  resilience: "How well the deck keeps functioning after disruption or a setback.",
  redundancy: "How many overlapping pieces do the same job, so the deck does not rely on only one card.",
  "bottleneck index": "How much the deck depends on a small number of chokepoints to function.",
  "role entropy": "How spread out the deck is across different roles. Higher means the deck is doing more different jobs.",
  "total colored pips": "How many colored mana symbols appear across your deck's mana costs.",
  "colorless/generic pips": "How many generic or colorless mana symbols appear across your deck's mana costs.",
  "weighted sources": "A weighted estimate of how many usable mana sources your mana base provides.",
  "most stressed color": "The color with the biggest mismatch between what your spells ask for and what your mana base can provide.",
  "p(4 mana by t3)": "Chance of reaching four mana by turn 3 in the goldfish simulation.",
  "p(5 mana by t4)": "Chance of reaching five mana by turn 4 in the goldfish simulation.",
  "median commander turn": "The middle turn on which your commander gets cast across simulated games.",
  "win by turn limit": "Chance that the simulator records a hard win before the chosen turn limit.",
  "sim backend": "Which simulation engine produced the current result.",
};
type ArtPreference = (typeof ART_PREFERENCE_OPTIONS)[number]["value"];
const DEFAULT_ART_PREFERENCE: ArtPreference = "clean";

function normalizeArtPreference(value: unknown): ArtPreference {
  const next = String(value || "").trim().toLowerCase();
  return (ART_PREFERENCE_OPTIONS.find((option) => option.value === next)?.value || DEFAULT_ART_PREFERENCE) as ArtPreference;
}

function progressTone(meta: { tone?: "error"; percent: number; show: boolean }): "default" | "accent" | "success" | "danger" {
  if (meta.tone === "error") return "danger";
  if (meta.percent >= 100 && meta.show) return "success";
  if (meta.show) return "accent";
  return "default";
}

function normalizeProjectNameKey(value: string) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "untitled-project";
}

function decklistStatusMeta(
  status: string,
  previewReady: boolean,
): { show: boolean; percent: number; label: string; detail: string; tone?: "error" } {
  const trimmed = (status || "").trim().toLowerCase();
  const mapped: Record<string, { percent: number; label: string; detail: string; show?: boolean; tone?: "error" }> = {
    idle: { percent: 0, label: "Idle", detail: "", show: false },
    generating: { percent: 34, label: "Generating deck", detail: "Picking a random commander and building a legal deck shell." },
    importing: { percent: 18, label: "Importing deck", detail: "Fetching deck text from the pasted URL." },
    parsing: { percent: 52, label: "Parsing decklist", detail: "Reading sections, quantities, commander, and legality structure." },
    tagging: { percent: 84, label: "Building preview", detail: "Applying tags and preparing the deck preview table." },
    done: { percent: 100, label: "Deck preview ready", detail: "Decklist parsing, tagging, and preview rendering are complete.", show: false },
    failed: { percent: 100, label: "Deck prep failed", detail: "The decklist could not be fully parsed and tagged.", show: false, tone: "error" },
  };
  if (trimmed === "generating") {
    const row = mapped.generating;
    return { show: true, percent: row.percent, label: row.label, detail: row.detail, tone: row.tone };
  }
  if (previewReady && trimmed !== "failed") {
    return {
      show: true,
      percent: 100,
      label: "Deck preview ready",
      detail: "Decklist parsing, tagging, and preview rendering are complete.",
    };
  }
  if (trimmed.startsWith("sim-") || trimmed === "analyzing" || trimmed === "analysis ready" || trimmed === "building primer") {
    return {
      show: true,
      percent: 100,
      label: "Deck preview ready",
      detail: "Decklist parsing, tagging, and preview rendering are complete.",
    };
  }
  if (mapped[trimmed]) {
    const row = mapped[trimmed];
    return { show: row.show ?? true, percent: row.percent, label: row.label, detail: row.detail, tone: row.tone };
  }
  return { show: false, percent: 0, label: "Idle", detail: "" };
}

function analysisStatusMeta(status: string): { show: boolean; percent: number; label: string; detail: string; tone?: "error" } {
  const trimmed = (status || "").trim().toLowerCase();
  const mapped: Record<string, { percent: number; label: string; detail: string; show?: boolean; tone?: "error" }> = {
    idle: { percent: 0, label: "Idle", detail: "", show: false },
    importing: { percent: 0, label: "Idle", detail: "", show: false },
    generating: { percent: 0, label: "Idle", detail: "", show: false },
    parsing: { percent: 0, label: "Idle", detail: "", show: false },
    tagging: { percent: 0, label: "Idle", detail: "", show: false },
    "sim-queued": { percent: 12, label: "Queueing simulation", detail: "Preparing the goldfish job and waiting for a worker." },
    "sim-started": { percent: 42, label: "Running simulation", detail: "Goldfishing the deck across many seeded runs." },
    "sim-done": { percent: 68, label: "Simulation complete", detail: "Simulation finished. Preparing the analysis layer." },
    analyzing: { percent: 84, label: "Analyzing results", detail: "Building deck diagnosis, recommendations, and graph payloads." },
    "analysis ready": { percent: 94, label: "Core analysis ready", detail: "Main results are loaded. Final guide text may still be finishing." },
    "building primer": { percent: 98, label: "Building primer", detail: "Generating the play primer and final narrative outputs." },
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
      percent: 42,
      label: "Running simulation",
      detail: `Worker status: ${status.replace(/^sim-/, "")}.`,
    };
  }
  return { show: false, percent: 0, label: "Idle", detail: "" };
}

const RULES_WATCHOUT_COPY: Record<string, { note: string; rules: string }> = {
  "Replacement effect": {
    note: "This card changes an event before it happens, so sequencing matters.",
    rules:
      "Replacement effects do not trigger and do not use the stack. They apply to the event they modify before that event happens, and if multiple replacement effects could apply, the affected player or object’s controller chooses the order.",
  },
  "Continuous condition": {
    note: "Its effect turns on and off as the board state changes.",
    rules:
      "Conditional static abilities are checked continuously. If the condition stops being true, the effect stops applying immediately without using the stack.",
  },
  "Conditional replacement": {
    note: "Its replacement text only works while a stated condition is true.",
    rules:
      "Check the condition at the exact moment the event would happen. If the condition is not true then, the replacement does nothing.",
  },
  "Triggered timing": {
    note: "Its value depends on hitting the correct trigger window.",
    rules:
      "Triggered abilities fire after their event, then wait to be put on the stack the next time a player would get priority. Attack, upkeep, dies, and enters-the-battlefield triggers each have different timing windows.",
  },
  "Mode selection": {
    note: "Choices are locked in while casting or activating, not later.",
    rules:
      "Modes are chosen as the spell or ability is put on the stack. You do not wait until resolution to decide them, and illegal modes cannot be chosen.",
  },
  "Additional casting costs": {
    note: "Extra costs must be paid during casting, not after the spell resolves.",
    rules:
      "Additional costs are part of casting the spell. They are paid up front and still matter even if the spell is later countered.",
  },
  "Stack interaction": {
    note: "This card depends on priority windows and target legality.",
    rules:
      "When using stack interaction, track when players receive priority and whether the spell or ability still has legal targets when it resolves.",
  },
  "Alternate zone casting": {
    note: "Casting from another zone changes timing and resource assumptions.",
    rules:
      "Permission to cast from graveyard, exile, or another zone does not bypass normal timing unless the card explicitly says so. Extra costs and restrictions still apply.",
  },
};

function uniqueNonEmpty(values: Array<string | null | undefined>) {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of values) {
    const text = String(raw || "").trim();
    if (!text) continue;
    if (seen.has(text)) continue;
    seen.add(text);
    out.push(text);
  }
  return out;
}

function InlinePanelProgress({
  label,
  percent,
  detail,
  tone,
  ariaLabel,
}: {
  label: string;
  percent: number;
  detail: string;
  tone?: "error";
  ariaLabel: string;
}) {
  return (
    <div className="panel-progress-inline" title={detail} aria-label={ariaLabel}>
      <span className="panel-progress-label">{label}</span>
      <div className="panel-progress-track" aria-hidden="true">
        <div
          className={`panel-progress-fill ${tone === "error" ? "is-error" : ""}`}
          style={{ width: `${percent}%` }}
        />
      </div>
      <span className="panel-progress-percent">{percent}%</span>
    </div>
  );
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


export default function HomePage() {
  const searchParams = useSearchParams();
  const entryMode = String(searchParams?.get("entry") || "url").toLowerCase();
  const [decklist, setDecklist] = useState("");
  const [moxfieldUrl, setMoxfieldUrl] = useState("");
  const [urlImportNotice, setUrlImportNotice] = useState<UrlImportNotice>(null);
  const [tab, setTab] = useState<TabName>("Deck Analysis");
  const [bracket, setBracket] = useState(3);
  const [policy, setPolicy] = useState("auto");
  const [simRuns, setSimRuns] = useState(2000);
  const [turnLimit, setTurnLimit] = useState(8);
  const [tablePressure, setTablePressure] = useState(30);
  const [mulliganAggression, setMulliganAggression] = useState(50);
  const [commanderPriority, setCommanderPriority] = useState(50);
  const [budgetMaxUsd, setBudgetMaxUsd] = useState("");
  const [artPreference, setArtPreference] = useState<ArtPreference>(DEFAULT_ART_PREFERENCE);
  const [showAdvancedSettings, setShowAdvancedSettings] = useState(false);
  const [detectedWincons, setDetectedWincons] = useState<string[]>([]);
  const [status, setStatus] = useState("idle");
  const [activeAction, setActiveAction] = useState<"none" | "random" | "tag" | "analysis">("none");

  const [parseRes, setParseRes] = useState<any>(null);
  const [tagRes, setTagRes] = useState<any>(null);
  const [simRes, setSimRes] = useState<any>(null);
  const [analysis, setAnalysis] = useState<any>(null);
  const [guides, setGuides] = useState<any>(null);
  const [comboRes, setComboRes] = useState<any>(null);
  const [rulesWatchoutsRes, setRulesWatchoutsRes] = useState<any[]>([]);
  const [displayMap, setDisplayMap] = useState<Record<string, any>>({});
  const [selectedCard, setSelectedCard] = useState<string | null>(null);
  const [selectedCurveMv, setSelectedCurveMv] = useState<number | null>(null);
  const [decklistPanelView, setDecklistPanelView] = useState<"Decklist" | "Tagged Decklist">("Decklist");
  const [mobilePane, setMobilePane] = useState<"controls" | "deck" | "views">("controls");
  const urlInputRef = useRef<HTMLInputElement | null>(null);
  const decklistInputRef = useRef<HTMLTextAreaElement | null>(null);
  const [authUser, setAuthUser] = useState<{ id: number; email: string; is_admin?: boolean; role?: string; status?: string; plan?: string } | null>(null);
  const [authEmail, setAuthEmail] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState("");
  const [authNotice, setAuthNotice] = useState("");
  const [csrfToken, setCsrfToken] = useState("");
  const [projects, setProjects] = useState<any[]>([]);
  const [projectVersions, setProjectVersions] = useState<Record<number, any[]>>({});
  const [expandedProjectId, setExpandedProjectId] = useState<number | null>(null);
  const [projectBusy, setProjectBusy] = useState(false);
  const [currentProjectId, setCurrentProjectId] = useState<number | null>(null);
  const [projectName, setProjectName] = useState("");
  const [savedSignature, setSavedSignature] = useState("");
  const [lastSavedAt, setLastSavedAt] = useState("");
  const [localDraftSavedAt, setLocalDraftSavedAt] = useState("");
  const [resetToken, setResetToken] = useState("");
  const [resetPassword, setResetPassword] = useState("");
  const [authChecked, setAuthChecked] = useState(false);
  const [integrationsMeta, setIntegrationsMeta] = useState<any>(null);
  const [accountOpen, setAccountOpen] = useState(false);
  const [accountTab, setAccountTab] = useState<"login" | "register" | "recover" | "library" | "security">("login");
  const [strictlyBetter, setStrictlyBetter] = useState<any[]>([]);
  const [strictlyBetterLoading, setStrictlyBetterLoading] = useState(false);
  const [expandedRoles, setExpandedRoles] = useState<Record<string, boolean>>({});
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(false);
  const [visibleCharts, setVisibleCharts] = useState<Record<string, boolean>>({});
  const [resolvedTheme, setResolvedTheme] = useState<ResolvedTheme>("dark");
  const chartObserverRef = useRef<IntersectionObserver | null>(null);
  const chartElementsRef = useRef<Record<string, HTMLDivElement | null>>({});
  const visibleChartsRef = useRef<Record<string, boolean>>({});
  const activeRunRef = useRef(0);
  const draftRestoredRef = useRef(false);

  const detailOpen = true;

  function applySystemTheme(mediaOverride?: MediaQueryList | null) {
    const media =
      mediaOverride ??
      (typeof window !== "undefined" && typeof window.matchMedia === "function"
        ? window.matchMedia("(prefers-color-scheme: dark)")
        : null);
    const nextResolved = resolveTheme("system", Boolean(media?.matches));
    if (typeof document !== "undefined") {
      document.documentElement.dataset.theme = nextResolved;
      document.documentElement.dataset.themeMode = "system";
      document.documentElement.style.colorScheme = nextResolved;
    }
    setResolvedTheme(nextResolved);
  }

  const currentChartTheme = useMemo(() => chartTheme(resolvedTheme), [resolvedTheme]);
  const chartAxisProps = useMemo(
    () => ({
      stroke: currentChartTheme.axisLine,
      axisLine: { stroke: currentChartTheme.axisLine },
      tickLine: { stroke: currentChartTheme.axisLine },
      tick: { fill: currentChartTheme.axis, fontSize: 12 },
    }),
    [currentChartTheme],
  );
  const chartGridProps = useMemo(
    () => ({
      stroke: currentChartTheme.grid,
      strokeDasharray: "3 3",
      vertical: false,
    }),
    [currentChartTheme],
  );
  const chartTooltipProps = useMemo(
    () => ({
      contentStyle: {
        backgroundColor: currentChartTheme.tooltipBg,
        borderColor: currentChartTheme.tooltipBorder,
        borderRadius: 12,
        boxShadow: "0 18px 44px rgba(8, 6, 14, 0.24)",
        color: currentChartTheme.tooltipText,
      },
      labelStyle: {
        color: currentChartTheme.tooltipText,
        fontWeight: 600,
      },
      itemStyle: {
        color: currentChartTheme.tooltipText,
      },
      cursor: {
        stroke: currentChartTheme.cursor,
        strokeDasharray: "4 4",
      },
    }),
    [currentChartTheme],
  );
  const chartLegendProps = useMemo(
    () => ({
      wrapperStyle: {
        color: currentChartTheme.legend,
        fontSize: 12,
        paddingTop: 8,
      },
    }),
    [currentChartTheme],
  );

  function chartLabel(value: string, position: "insideBottom" | "insideLeft" | "insideRight", extra?: Record<string, unknown>) {
    return {
      value,
      position,
      fill: currentChartTheme.axisMuted,
      fontSize: 12,
      ...(position === "insideBottom" ? { offset: -2 } : {}),
      ...extra,
    };
  }

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
  const commanderNames = useMemo(
    () => (parseRes?.commanders?.length ? parseRes.commanders : parseRes?.commander ? [parseRes.commander] : []),
    [parseRes],
  );
  const commanderLabel = useMemo(
    () => (commanderNames.length ? commanderNames.join(" + ") : "n/a"),
    [commanderNames],
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
  const hasAnalysisResources = Boolean(simRes || analysis || guides);
  const availableTabs = useMemo(
    () => (hasAnalysisResources ? [...TABS] : tagRes ? [...TAG_ONLY_TABS] : []),
    [hasAnalysisResources, tagRes],
  );
  const availableTabGroups = useMemo(
    () =>
      TAB_GROUPS.filter((group) =>
        group.tabs.some((groupTab) => availableTabs.includes(groupTab as any)),
      ),
    [availableTabs],
  );
  const activeTabGroup = useMemo<TabGroupName | null>(() => {
    if (!availableTabs.length) return null;
    const activeTab = (availableTabs.includes(tab as any) ? tab : availableTabs[0]) as TabName;
    return TAB_TO_GROUP[activeTab];
  }, [availableTabs, tab]);
  const visibleGroupTabs = useMemo(
    () =>
      activeTabGroup
        ? availableTabs.filter((availableTab) => TAB_TO_GROUP[availableTab as TabName] === activeTabGroup)
        : [],
    [activeTabGroup, availableTabs],
  );
  const hasOutcomeResources = availableTabs.length > 0;
  const winMetrics = simRes?.summary?.win_metrics || {};
  const uncertainty = simRes?.summary?.uncertainty || {};
  const fastestWins = simRes?.summary?.fastest_wins || [];
  const comboIntel = analysis?.combo_intel || comboRes || {};
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
  const typeThemeProfile = analysis?.type_theme_profile || tagRes?.type_theme_profile || {};
  const colorIdentity = colorProfile?.color_identity || parseRes?.color_identity || tagRes?.color_identity || [];
  const colorIdentitySize = Number(colorProfile?.color_identity_size ?? parseRes?.color_identity_size ?? tagRes?.color_identity_size ?? 0);
  const currentBracketReport = analysis?.bracket_report || tagRes?.bracket_report || parseRes?.bracket_report || null;
  const currentBracketValue = Number(currentBracketReport?.bracket ?? bracket ?? 3);
  const currentBracketName = String(currentBracketReport?.bracket_name || "");
  const decklistProgressMeta = useMemo(
    () => decklistStatusMeta(status, Boolean(tagRes?.cards?.length)),
    [status, tagRes],
  );
  const analysisProgressMeta = useMemo(() => analysisStatusMeta(status), [status]);
  const normalizedStatus = String(status || "").trim().toLowerCase();
  const randomDeckButtonProgress = activeAction === "random" && normalizedStatus === "generating" ? decklistProgressMeta.percent : 0;
  const tagDeckButtonProgress = activeAction === "tag" && ["parsing", "tagging"].includes(normalizedStatus) ? decklistProgressMeta.percent : 0;
  const fullAnalysisButtonProgress = activeAction === "analysis"
    ? (
        analysisProgressMeta.show
          ? analysisProgressMeta.percent
          : (["parsing", "tagging"].includes(normalizedStatus) ? Math.max(8, Math.round(decklistProgressMeta.percent * 0.18)) : 0)
      )
    : 0;
  const rulesWatchoutRows = useMemo(() => {
    return ((analysis?.rules_watchouts || rulesWatchoutsRes || []) as any[])
      .map((w: any) => {
        const flags = Array.isArray(w?.complexity_flags) ? w.complexity_flags : [];
        const fallbackErrata = uniqueNonEmpty(
          (w?.rulings || []).map((r: any) => {
            const comment = String(r?.comment || "").trim();
            if (!comment) return null;
            const published = String(r?.published_at || "").trim();
            return published ? `${published}: ${comment}` : comment;
          }),
        );
        const errata = uniqueNonEmpty(Array.isArray(w?.errata) ? w.errata : fallbackErrata);
        const notes = uniqueNonEmpty(Array.isArray(w?.notes) ? w.notes : flags.map((flag: string) => RULES_WATCHOUT_COPY[flag]?.note || null));
        const rulesInfo = uniqueNonEmpty(
          Array.isArray(w?.rules_information)
            ? w.rules_information
            : Array.isArray(w?.rulesInfo)
              ? w.rulesInfo
              : flags.map((flag: string) => RULES_WATCHOUT_COPY[flag]?.rules || null),
        );
        if (!errata.length && !notes.length && !rulesInfo.length) {
          return null;
        }
        return {
          ...w,
          errata,
          notes,
          rulesInfo,
        };
      })
      .filter(Boolean);
  }, [analysis, rulesWatchoutsRes]);
  const currentSettingsBundle = useMemo(
    () => ({
      bracket: currentBracketValue,
      policy,
      simRuns,
      turnLimit,
      tablePressure,
      mulliganAggression,
      commanderPriority,
      budgetMaxUsd,
      artPreference,
      showAdvancedSettings,
    }),
    [currentBracketValue, policy, simRuns, turnLimit, tablePressure, mulliganAggression, commanderPriority, budgetMaxUsd, artPreference, showAdvancedSettings],
  );
  const currentProjectSummary = useMemo(() => {
    const legalityLabel =
      parseRes?.errors?.length
        ? String(parseRes.errors[0] || "Needs fixes")
        : parseRes
          ? "Legal"
          : "Unvalidated";
    const comboCatalog = analysis?.combo_intel || comboRes || {};
    const medianWinTurn = simRes?.summary?.win_metrics?.median_win_turn;
    return {
      deck_name: analysis?.deck_name || projectName || commanderLabel || "Untitled Project",
      commander_label: commanderLabel,
      card_count: parsedCount,
      auto_win_plans: detectedWincons,
      color_identity: colorIdentity,
      bracket: currentBracketValue,
      has_analysis: Boolean(analysis || simRes || guides),
      legality: legalityLabel,
      latest_status: status,
      median_win_turn: typeof medianWinTurn === "number" ? medianWinTurn : null,
      complete_combo_count: Number(comboCatalog?.matched_variants?.length || 0),
      one_card_combo_count: Number(comboCatalog?.near_miss_variants?.length || 0),
      rules_watchout_count: Number((analysis?.rules_watchouts || rulesWatchoutsRes || []).length || 0),
    };
  }, [
    analysis,
    comboRes,
    commanderLabel,
    currentBracketValue,
    detectedWincons,
    colorIdentity,
    guides,
    parsedCount,
    parseRes,
    projectName,
    rulesWatchoutsRes,
    simRes,
    status,
  ]);
  const currentSavedBundle = useMemo(
    () => ({
      settings: currentSettingsBundle,
      parseRes,
      tagRes,
      simRes,
      analysis,
      guides,
      comboRes,
      rulesWatchoutsRes,
      detectedWincons,
      status,
    }),
    [analysis, comboRes, currentSettingsBundle, detectedWincons, guides, parseRes, rulesWatchoutsRes, simRes, status, tagRes],
  );
  const currentProjectSnapshot = useMemo(() => {
    const derivedName = (projectName || analysis?.deck_name || commanderLabel || "Untitled Project").trim() || "Untitled Project";
    return {
      name: derivedName,
      name_key: normalizeProjectNameKey(derivedName),
      deck_name: analysis?.deck_name || derivedName,
      commander_label: commanderLabel,
      decklist_text: decklist,
      bracket: currentBracketValue,
      summary: currentProjectSummary,
      saved_bundle: currentSavedBundle,
    };
  }, [analysis?.deck_name, commanderLabel, currentBracketValue, currentProjectSummary, currentSavedBundle, decklist, projectName]);
  const currentProjectSignature = useMemo(() => JSON.stringify(currentProjectSnapshot), [currentProjectSnapshot]);
  const hasMeaningfulDeckState = useMemo(
    () =>
      Boolean(
        currentProjectId ||
          projectName.trim() ||
          parseRes ||
          tagRes ||
          simRes ||
          analysis ||
          guides ||
          comboRes ||
          rulesWatchoutsRes.length ||
          decklist.trim(),
      ),
    [analysis, comboRes, currentProjectId, decklist, guides, parseRes, projectName, rulesWatchoutsRes.length, simRes, tagRes],
  );
  const hasUnsavedChanges = useMemo(
    () => Boolean(hasMeaningfulDeckState && (!savedSignature || savedSignature !== currentProjectSignature)),
    [currentProjectSignature, hasMeaningfulDeckState, savedSignature],
  );
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
    if (!out.length) out.push("Core goldfish metrics look stable for the current policy and inferred bracket.");
    return out;
  }, [simRes, analysis]);

  const roleRows = useMemo(() => {
    if (!analysis) {
      const taggedCards = tagRes?.cards || [];
      const roleCounts: Record<string, number> = {};
      const cardsByRole: Record<string, { name: string; qty: number }[]> = {};
      for (const card of taggedCards) {
        if (!["deck", "commander"].includes(card?.section)) continue;
        for (const role of card?.tags || []) {
          roleCounts[role] = Number(roleCounts[role] || 0) + Number(card?.qty || 1);
          cardsByRole[role] = cardsByRole[role] || [];
          cardsByRole[role].push({ name: card.name, qty: Number(card.qty || 1) });
        }
      }
      return Object.entries(roleCounts)
        .map(([role, count]) => ({
          role,
          have: Number(count || 0),
          minTarget: 0,
          center: 0,
          maxTarget: 0,
          status: "tagged",
          reason: "Tagged count from the current decklist. Run full analysis for adaptive targets and bracket-aware role guidance.",
          cards: (cardsByRole[role] || []).sort((a, b) => Number(b.qty || 0) - Number(a.qty || 0) || String(a.name || "").localeCompare(String(b.name || ""))),
        }))
        .sort((a, b) => Number(b.have || 0) - Number(a.have || 0) || a.role.localeCompare(b.role));
    }
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

  useEffect(() => {
    if (!hasOutcomeResources) return;
    if (!availableTabs.includes(tab as any)) {
      setTab(availableTabs[0] as TabName);
    }
  }, [availableTabs, hasOutcomeResources, tab]);

  useEffect(() => {
    const focusTarget = () => {
      if (entryMode === "paste") {
        setMobilePane("deck");
        decklistInputRef.current?.focus();
      } else {
        setMobilePane("controls");
        urlInputRef.current?.focus();
      }
    };
    const raf = window.requestAnimationFrame(focusTarget);
    return () => window.cancelAnimationFrame(raf);
  }, [entryMode]);

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
      return "Import response could not be read in this browser session. Retry once; if it persists, paste the deck text directly.";
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

  function persistCsrfToken(next: string) {
    setCsrfToken(next);
    if (typeof window === "undefined") return;
    if (next) window.localStorage.setItem(AUTH_CSRF_STORAGE_KEY, next);
    else window.localStorage.removeItem(AUTH_CSRF_STORAGE_KEY);
  }

  function clearResetTokenFromUrl() {
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    url.searchParams.delete("reset_token");
    window.history.replaceState({}, "", url.toString());
  }

  function clearLocalDraft() {
    if (typeof window === "undefined") return;
    window.localStorage.removeItem(LOCAL_DRAFT_STORAGE_KEY);
    setLocalDraftSavedAt("");
    setAuthNotice("Local draft cleared.");
  }

  function projectSummaryPills(summary: any) {
    const pills: string[] = [];
    if (summary?.deck_name) pills.push(String(summary.deck_name));
    if (summary?.legality) pills.push(String(summary.legality));
    if (typeof summary?.median_win_turn === "number") pills.push(`Median win T${summary.median_win_turn}`);
    if (Array.isArray(summary?.auto_win_plans) && summary.auto_win_plans.length) pills.push(summary.auto_win_plans.join(", "));
    if (Number(summary?.complete_combo_count || 0) > 0) pills.push(`${summary.complete_combo_count} combo${Number(summary.complete_combo_count) === 1 ? "" : "s"}`);
    if (Number(summary?.one_card_combo_count || 0) > 0) pills.push(`${summary.one_card_combo_count} one-away`);
    if (summary?.latest_status === "done") pills.push("Analysis ready");
    return pills.slice(0, 4);
  }

  async function requestJson(path: string, init: RequestInit, stage: string): Promise<any> {
    let response: Response;
    try {
      response = await fetch(apiUrl(path), { credentials: "include", ...init });
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

  function authHeaders() {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    const token = csrfToken || (typeof window !== "undefined" ? window.localStorage.getItem(AUTH_CSRF_STORAGE_KEY) || "" : "");
    if (token) headers["X-CSRF-Token"] = token;
    return headers;
  }

  function collectBundleCardNames(bundle: any): string[] {
    const names = new Set<string>();
    const add = (value: any) => {
      if (typeof value === "string" && value.trim()) names.add(value);
    };
    (bundle?.parseRes?.cards || []).forEach((card: any) => add(card?.name));
    (bundle?.tagRes?.cards || []).forEach((card: any) => add(card?.name));
    (bundle?.analysis?.importance || []).forEach((row: any) => add(row?.card));
    (bundle?.analysis?.adds || []).forEach((row: any) => add(row?.card));
    (bundle?.analysis?.cuts || []).forEach((row: any) => add(row?.card));
    (bundle?.analysis?.rules_watchouts || bundle?.rulesWatchoutsRes || []).forEach((row: any) => add(row?.card));
    [...(bundle?.comboRes?.matched_variants || []), ...(bundle?.comboRes?.near_miss_variants || [])].forEach((row: any) => {
      (row?.present_cards || []).forEach(add);
      (row?.missing_cards || []).forEach(add);
    });
    return [...names];
  }

  function applySavedBundle(project: any, options?: { isLocalDraft?: boolean }) {
    const bundle = project?.saved_bundle || {};
    const nextArtPreference = normalizeArtPreference(bundle?.settings?.artPreference);
    setCurrentProjectId(options?.isLocalDraft ? null : (project?.project_id ?? project?.id ?? null));
    setProjectName(project?.name || project?.deck_name || "");
    setDecklist(project?.decklist_text || "");
    setBracket(Number(project?.bracket ?? bundle?.settings?.bracket ?? 3));
    setPolicy(bundle?.settings?.policy ?? "auto");
    setSimRuns(Number(bundle?.settings?.simRuns ?? 2000));
    setTurnLimit(Number(bundle?.settings?.turnLimit ?? 8));
    setTablePressure(Number(bundle?.settings?.tablePressure ?? 30));
    setMulliganAggression(Number(bundle?.settings?.mulliganAggression ?? 50));
    setCommanderPriority(Number(bundle?.settings?.commanderPriority ?? 50));
    setBudgetMaxUsd(String(bundle?.settings?.budgetMaxUsd ?? ""));
    setArtPreference(nextArtPreference);
    setShowAdvancedSettings(Boolean(bundle?.settings?.showAdvancedSettings ?? false));
    setParseRes(bundle?.parseRes || null);
    setTagRes(bundle?.tagRes || null);
    setSimRes(bundle?.simRes || null);
    setAnalysis(bundle?.analysis || null);
    setGuides(bundle?.guides || null);
    setComboRes(bundle?.comboRes || null);
    setRulesWatchoutsRes(bundle?.rulesWatchoutsRes || []);
    setDetectedWincons(bundle?.detectedWincons || []);
    setDisplayMap({});
    setDecklistPanelView("Decklist");
    setSelectedCard(null);
    setStatus(bundle?.status || (bundle?.analysis || bundle?.simRes || bundle?.guides ? "done" : bundle?.tagRes ? "done" : "idle"));
    const persistedSnapshot = JSON.stringify({
      name: project?.name || project?.deck_name || "",
      name_key: project?.name_key || normalizeProjectNameKey(project?.name || project?.deck_name || ""),
      deck_name: project?.deck_name || project?.name || "",
      commander_label: project?.commander_label || "",
      decklist_text: project?.decklist_text || "",
      bracket: Number(project?.bracket ?? bundle?.settings?.bracket ?? 3),
      summary: project?.summary || {},
      saved_bundle: bundle,
    });
    setSavedSignature(persistedSnapshot);
    setLastSavedAt(String(project?.updated_at || project?.created_at || project?.local_saved_at || ""));
    if (options?.isLocalDraft) {
      setLocalDraftSavedAt(String(project?.local_saved_at || ""));
    }
    const hasAnalysis = Boolean(bundle?.analysis || bundle?.simRes || bundle?.guides);
    const hasTag = Boolean(bundle?.tagRes);
    setTab(hasAnalysis ? "Deck Analysis" : hasTag ? "Role Breakdown" : "Deck Analysis");
    setMobilePane(hasAnalysis || hasTag ? "views" : "deck");
    const hydrateNames = collectBundleCardNames(bundle);
    if (hydrateNames.length) void hydrateDisplay(hydrateNames, nextArtPreference, true);
  }

  async function refreshProjects(nextUser = authUser) {
    if (!nextUser) {
      setProjects([]);
      return;
    }
    try {
      const payload = await requestJson("/api/projects", { method: "GET" }, "Project list");
      setProjects(payload.projects || []);
    } catch {
      setProjects([]);
    }
  }

  async function handleAuth(action: "login" | "register") {
    setAuthBusy(true);
    setAuthError("");
    setAuthNotice("");
    try {
      const payload = await requestJson(
        `/api/auth/${action}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: authEmail, password: authPassword }),
        },
        action === "login" ? "Login" : "Account creation",
      );
      setAuthUser(payload.user || null);
      persistCsrfToken(payload.csrf_token || "");
      setAuthPassword("");
      setResetPassword("");
      setResetToken("");
      setAuthChecked(true);
      await refreshProjects(payload.user || null);
      setAuthNotice(action === "login" ? "Logged in." : "Account created.");
    } catch (err: any) {
      setAuthError(normalizeUiError(err, action === "login" ? "Login failed." : "Account creation failed."));
    } finally {
      setAuthBusy(false);
    }
  }

  async function handleLogout() {
    setAuthBusy(true);
    setAuthError("");
    setAuthNotice("");
    try {
      await requestJson("/api/auth/logout", { method: "POST", headers: authHeaders() }, "Logout");
      setAuthUser(null);
      setProjects([]);
      setCurrentProjectId(null);
      setProjectName("");
      setProjectVersions({});
      setExpandedProjectId(null);
      persistCsrfToken("");
      setAuthChecked(true);
      setSavedSignature("");
      setLastSavedAt("");
    } catch (err: any) {
      setAuthError(normalizeUiError(err, "Logout failed."));
    } finally {
      setAuthBusy(false);
    }
  }

  async function requestPasswordReset() {
    if (!authEmail.trim()) {
      setAuthError("Enter your email first.");
      return;
    }
    setAuthBusy(true);
    setAuthError("");
    setAuthNotice("");
    try {
      const payload = await requestJson(
        "/api/auth/password-reset/request",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: authEmail }),
        },
        "Password reset request",
      );
      setAuthNotice(payload?.debug_magic_link ? `${payload.message} Local link: ${payload.debug_magic_link}` : payload.message || "If that email exists, a one-time reset link has been sent.");
    } catch (err: any) {
      setAuthError(normalizeUiError(err, "Password reset request failed."));
    } finally {
      setAuthBusy(false);
    }
  }

  async function confirmPasswordReset() {
    if (!resetToken) {
      setAuthError("Reset link is missing or expired.");
      return;
    }
    setAuthBusy(true);
    setAuthError("");
    setAuthNotice("");
    try {
      const payload = await requestJson(
        "/api/auth/password-reset/confirm",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token: resetToken, password: resetPassword }),
        },
        "Password reset",
      );
      setAuthUser(payload.user || null);
      persistCsrfToken(payload.csrf_token || "");
      setResetPassword("");
      setResetToken("");
      clearResetTokenFromUrl();
      setAuthNotice("Password updated. You are now signed in.");
      await refreshProjects(payload.user || null);
    } catch (err: any) {
      setAuthError(normalizeUiError(err, "Password reset failed."));
    } finally {
      setAuthBusy(false);
    }
  }

  async function saveCurrentProject(options?: { silent?: boolean }) {
    if (!authUser) {
      if (!options?.silent) setAuthError("Log in to save decks.");
      return;
    }
    setProjectBusy(true);
    if (!options?.silent) {
      setAuthError("");
      setAuthNotice("");
    }
    try {
      const snapshot = currentProjectSnapshot;
      const derivedName = snapshot.name;
      const matchingProject = projects.find((project: any) => project?.name_key === snapshot.name_key);
      const targetProjectId = currentProjectId || matchingProject?.id || null;
      const payload = await requestJson(
        targetProjectId ? `/api/projects/${targetProjectId}` : "/api/projects",
        {
          method: targetProjectId ? "PUT" : "POST",
          headers: authHeaders(),
          body: JSON.stringify(snapshot),
        },
        targetProjectId ? "Project update" : "Project save",
      );
      setCurrentProjectId(payload.id);
      setProjectName(payload.name || derivedName);
      setSavedSignature(JSON.stringify(snapshot));
      setLastSavedAt(String(payload.updated_at || payload.created_at || new Date().toISOString()));
      setExpandedProjectId(payload.id);
      await refreshProjects();
      const versionsPayload = await requestJson(`/api/projects/${payload.id}/versions`, { method: "GET" }, "Project version history");
      setProjectVersions((prev) => ({ ...prev, [payload.id]: versionsPayload.versions || [] }));
      if (!options?.silent) setAuthNotice(targetProjectId ? "Saved as a new version." : "Saved.");
    } catch (err: any) {
      if (!options?.silent) setAuthError(normalizeUiError(err, "Saving the deck failed."));
    } finally {
      setProjectBusy(false);
    }
  }

  async function toggleProjectVersions(projectId: number) {
    if (expandedProjectId === projectId) {
      setExpandedProjectId(null);
      return;
    }
    setExpandedProjectId(projectId);
    if (projectVersions[projectId]) return;
    setProjectBusy(true);
    try {
      const payload = await requestJson(`/api/projects/${projectId}/versions`, { method: "GET" }, "Project version history");
      setProjectVersions((prev) => ({ ...prev, [projectId]: payload.versions || [] }));
    } catch (err: any) {
      setAuthError(normalizeUiError(err, "Loading project history failed."));
    } finally {
      setProjectBusy(false);
    }
  }

  async function loadLatestProject(projectId: number) {
    setProjectBusy(true);
    setAuthError("");
    try {
      const payload = await requestJson(`/api/projects/${projectId}`, { method: "GET" }, "Project load");
      applySavedBundle(payload);
      setAuthNotice(`Loaded ${payload.name || payload.deck_name}.`);
    } catch (err: any) {
      setAuthError(normalizeUiError(err, "Loading the saved deck failed."));
    } finally {
      setProjectBusy(false);
    }
  }

  async function loadProjectVersion(projectId: number, versionId: number) {
    setProjectBusy(true);
    setAuthError("");
    try {
      const payload = await requestJson(`/api/projects/${projectId}/versions/${versionId}`, { method: "GET" }, "Project version load");
      applySavedBundle(payload);
      setAuthNotice(`Loaded version ${payload.version_number}.`);
    } catch (err: any) {
      setAuthError(normalizeUiError(err, "Loading the saved deck version failed."));
    } finally {
      setProjectBusy(false);
    }
  }

  async function deleteProject(projectId: number) {
    setProjectBusy(true);
    setAuthError("");
    try {
      await requestJson(`/api/projects/${projectId}`, { method: "DELETE", headers: authHeaders() }, "Project delete");
      if (currentProjectId === projectId) {
        setCurrentProjectId(null);
      }
      await refreshProjects();
    } catch (err: any) {
      setAuthError(normalizeUiError(err, "Deleting the saved deck failed."));
    } finally {
      setProjectBusy(false);
    }
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

  function resolveMiniCardHelp(label: string, fallback?: string) {
    const key = label.trim().toLowerCase();
    return fallback || MINI_CARD_HELP[key] || `${label} for this deck or account.`;
  }

  function renderMiniCard({
    label,
    value,
    tone,
    surface = "3",
    help,
    valueClassName,
    children,
  }: {
    label: string;
    value: ReactNode;
    tone?: string;
    surface?: string;
    help?: string;
    valueClassName?: string;
    children?: ReactNode;
  }) {
    const tooltip = resolveMiniCardHelp(label, help);
    return (
      <div className="mini-card" data-surface={surface} data-tone={tone} title={tooltip} aria-label={`${label}. ${tooltip}`}>
        <div className="mini-label-row">
          <div className="mini-label">{label}</div>
          <span className="mini-tooltip-trigger" aria-hidden="true" title={tooltip}>?</span>
        </div>
        <div className={valueClassName ? `mini-value ${valueClassName}` : "mini-value"}>{value}</div>
        {children}
      </div>
    );
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
          <img src={cardThumb(name)} alt={name} width={width} height={height} loading="lazy" className="card-chip-thumb" />
        ) : (
          <span className="card-chip-thumb card-chip-thumb-placeholder" style={{ width, height }} />
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

  function renderComboGrid(
    entries: Array<string | { name: string; label?: string }>,
    keyPrefix: string,
    options?: { dimmedNames?: string[]; emptyText?: string },
  ) {
    const items = (entries || [])
      .map((entry) => {
        if (typeof entry === "string") {
          const name = entry.trim();
          return name ? { name, label: name } : null;
        }
        const name = String(entry?.name || "").trim();
        if (!name) return null;
        const label = String(entry?.label || name).trim() || name;
        return { name, label };
      })
      .filter((entry): entry is { name: string; label: string } => Boolean(entry));
    if (!items.length) {
      return <p className="muted">{options?.emptyText || "No cards available."}</p>;
    }
    const dimmed = new Set((options?.dimmedNames || []).map((name) => name.trim().toLowerCase()));
    return (
      <div className="combo-card-grid">
        {items.map((item, index) => {
          const poster = cardPoster(item.name);
          const isDimmed = dimmed.has(item.name.trim().toLowerCase());
          return (
            <button
              key={`${keyPrefix}-${index}`}
              type="button"
              className={`combo-card-tile ${isDimmed ? "is-dimmed" : ""}`}
              onClick={() => setSelectedCard(item.name)}
            >
              {poster ? (
                <img src={poster} alt={item.name} loading="lazy" className="combo-card-tile-image" />
              ) : (
                <div className="combo-card-tile-image combo-card-tile-placeholder" />
              )}
              <span className="combo-card-tile-name">{item.label}</span>
            </button>
          );
        })}
      </div>
    );
  }

  function cardPoster(name: string) {
    return cardDisplay(name)?.normal || cardDisplay(name)?.small || "";
  }

  function renderCardDetailMedia(
    name: string,
    key: string,
    options?: { compact?: boolean; static?: boolean },
  ) {
    const src = cardPoster(name);
    const className = `card-detail-media${options?.compact ? " is-compact" : ""}${options?.static ? " is-static" : ""}`;
    const content = src ? (
      <img src={src} alt={name} loading="lazy" />
    ) : (
      <div className="card-detail-placeholder" />
    );
    if (options?.static) {
      return (
        <div key={key} className={className}>
          {content}
        </div>
      );
    }
    return (
      <button key={key} type="button" className={className} onClick={() => setSelectedCard(name)}>
        {content}
      </button>
    );
  }

  function renderCardDetailRow({
    rowKey,
    title,
    imageCard,
    mediaCards,
    badge,
    meta,
    stats,
    sections,
    links,
    compact,
  }: {
    rowKey: string;
    title: string;
    imageCard?: string;
    mediaCards?: string[];
    badge?: string;
    meta?: any;
    stats?: Array<{ label: string; value: any }>;
    sections?: Array<{ label: string; content: any } | null | false | undefined>;
    links?: Array<{ label: string; href?: string | null }>;
    compact?: boolean;
  }) {
    const activeSections = (sections || []).reduce<Array<{ label: string; content: any }>>((acc, section) => {
      if (section && typeof section === "object" && "content" in section && section.content) {
        acc.push(section as { label: string; content: any });
      }
      return acc;
    }, []);
    const activeLinks = (links || []).filter((link) => link?.href);
    const mediaNames = (mediaCards || []).filter((name) => typeof name === "string" && name.trim().length > 0);
    const media = mediaNames.length > 1 ? (
      <div className="card-detail-media-stack">
        {mediaNames.slice(0, 2).map((name, idx) =>
          renderCardDetailMedia(name, `${rowKey}-media-${idx}`, { compact: true }),
        )}
      </div>
    ) : imageCard ? (
      renderCardDetailMedia(imageCard, `${rowKey}-media`, { compact })
    ) : null;

    return (
      <article key={rowKey} className={`card-detail-row ${compact ? "is-compact" : ""}`.trim()} data-surface={compact ? "3" : "2"}>
        {media}
        <div className="card-detail-body">
          <div className="card-detail-title-row">
            <h3 className="card-detail-title">{title}</h3>
            {badge ? <span className="card-preview-badge">{badge}</span> : null}
          </div>
          {meta ? <div className="card-detail-meta">{meta}</div> : null}
          {stats?.length ? (
            <div className="card-detail-stats">
              {stats.map((stat, idx) => (
                <span key={`${rowKey}-stat-${idx}`} className="card-detail-stat">
                  <strong>{stat.label}:</strong> {stat.value}
                </span>
              ))}
            </div>
          ) : null}
          {activeSections.map((section, idx) => (
            <div key={`${rowKey}-section-${idx}`} className="card-detail-section">
              <div className="card-detail-section-label">{section.label}</div>
              {section.content}
            </div>
          ))}
          {activeLinks.length ? (
            <div className="card-detail-links">
              {activeLinks.map((link, idx) => (
                <a key={`${rowKey}-link-${idx}`} className="insight-link" href={link.href || "#"} target="_blank" rel="noreferrer">
                  {link.label}
                </a>
              ))}
            </div>
          ) : null}
        </div>
      </article>
    );
  }

  function updateStatus(next: string) {
    setStatus(next);
  }

  function clearRunResources() {
    setParseRes(null);
    setTagRes(null);
    setSimRes(null);
    setAnalysis(null);
    setGuides(null);
    setComboRes(null);
    setRulesWatchoutsRes([]);
    setDisplayMap({});
    setDetectedWincons([]);
    setSelectedCard(null);
    setStrictlyBetter([]);
    setDecklistPanelView("Decklist");
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

  async function hydrateDisplay(names: string[], preferenceOverride?: ArtPreference, force = false) {
    const nextPreference = normalizeArtPreference(preferenceOverride || artPreference);
    const uniqueNames = Array.from(new Set((names || []).filter((n) => typeof n === "string" && n.trim().length > 0)));
    const toFetch = force ? uniqueNames : uniqueNames.filter((n) => n && !displayMap[n]);
    if (!toFetch.length) return;
    try {
      const params = new URLSearchParams({
        names: toFetch.join(","),
        art_preference: nextPreference,
      });
      const res = await fetch(apiUrl(`/api/cards/display?${params.toString()}`));
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
      clearRunResources();
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

  async function generateRandomDeck() {
    try {
      setActiveAction("random");
      updateStatus("generating");
      setUrlImportNotice(null);
      const payload = await requestJson(
        "/api/decks/random",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        },
        "Random deck generation",
      );
      clearRunResources();
      setProjectName("");
      setDecklist(String(payload.decklist_text || ""));
      setMobilePane("deck");
      setUrlImportNotice({
        tone: "info",
        text: `Generated a legal ${payload.color_identity?.join("") || "colorless"} deck for ${payload.commander}. ${payload.interaction_count || 0} cheap interaction slots included.`,
      });
    } catch (err: any) {
      setUrlImportNotice({
        tone: "error",
        text: normalizeUiError(err, "Random deck generation failed."),
      });
    } finally {
      updateStatus("idle");
    }
  }

  async function parseAndTagDeck(runId: number) {
    updateStatus("parsing");
    const parsed = await requestJson(
      "/api/decks/parse",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decklist_text: decklist, multiplayer: true }),
      },
      "Deck parse",
    );
    if (activeRunRef.current !== runId) return null;
    setParseRes(parsed);
    const parsedBracket = Number(parsed?.bracket_report?.bracket || 3);
    setBracket(parsedBracket);

    updateStatus("tagging");
    const tagged = await requestJson(
      "/api/decks/tag",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            cards: parsed.cards,
            commander: parsed.commander,
            commanders: parsed.commanders || [],
            global_tags: true,
            art_preference: artPreference,
          }),
        },
        "Deck tagging",
      );
    if (activeRunRef.current !== runId) return null;
    setTagRes(tagged);
    const taggedBracket = Number(tagged?.bracket_report?.bracket || parsedBracket || 3);
    setBracket(taggedBracket);
    setDisplayMap(tagged.card_display || {});
    const inferredWincons = inferWinconsFromTagged(tagged);
    setDetectedWincons(inferredWincons);
    return { parsed, tagged, inferredWincons, effectiveBracket: taggedBracket };
  }

  async function runTagOnly() {
    const runId = activeRunRef.current + 1;
    activeRunRef.current = runId;
    try {
      setActiveAction("tag");
      setSimRes(null);
      setAnalysis(null);
      setGuides(null);
      setComboRes(null);
      setRulesWatchoutsRes([]);
      setSelectedCard(null);
      const prep = await parseAndTagDeck(runId);
      if (!prep || activeRunRef.current !== runId) return;
      const { parsed, tagged } = prep;

      const commanderCards = (parsed.commanders || parsed.commander ? [parsed.commander].filter(Boolean).concat(parsed.commanders || []) : [])
        .filter((name: string, index: number, arr: string[]) => arr.indexOf(name) === index);
      const deckCardNames = (tagged.cards || [])
        .filter((card: any) => ["deck", "commander"].includes(card?.section))
        .map((card: any) => card?.name)
        .filter((name: any) => typeof name === "string" && name.length > 0);

      const [comboPayload, watchoutsPayload] = await Promise.all([
        requestJson(
          "/api/combos/intel",
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              cards: deckCardNames,
              commander: parsed.commander,
              commanders: commanderCards,
            }),
          },
          "Combo catalog",
        ).catch(() => ({ matched_variants: [], near_miss_variants: [], combo_support_score: 0, warnings: [] })),
        requestJson(
          "/api/rules/watchouts",
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              cards: parsed.cards,
              commander: parsed.commander,
              commanders: commanderCards,
            }),
          },
          "Rules watchouts",
        ).catch(() => []),
      ]);
      if (activeRunRef.current !== runId) return;
      setComboRes(comboPayload);
      setRulesWatchoutsRes(Array.isArray(watchoutsPayload) ? watchoutsPayload : []);

      const comboCards = [
        ...((comboPayload?.matched_variants || []).flatMap((line: any) => [...(line?.present_cards || []), ...(line?.missing_cards || [])])),
        ...((comboPayload?.near_miss_variants || []).flatMap((line: any) => [...(line?.present_cards || []), ...(line?.missing_cards || [])])),
      ].filter((name: any) => typeof name === "string" && name.length > 0);
      const watchoutCards = (Array.isArray(watchoutsPayload) ? watchoutsPayload : [])
        .map((row: any) => row?.card)
        .filter((name: any) => typeof name === "string" && name.length > 0);
      void hydrateDisplay([...comboCards, ...watchoutCards]);

      setTab("Role Breakdown");
      setMobilePane("views");
      updateStatus("done");
    } catch (err: any) {
      updateStatus("failed");
      alert(normalizeUiError(err, "Deck tagging failed"));
    }
  }

  async function runPipeline() {
    const runId = activeRunRef.current + 1;
    activeRunRef.current = runId;
    try {
      setActiveAction("analysis");
      setSimRes(null);
      setAnalysis(null);
      setGuides(null);
      setComboRes(null);
      setRulesWatchoutsRes([]);
      setSelectedCard(null);
      const prep = await parseAndTagDeck(runId);
      if (!prep || activeRunRef.current !== runId) return;
      const { parsed, tagged, inferredWincons, effectiveBracket } = prep;

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
            commanders: parsed.commanders || [],
            runs: simRuns,
            turn_limit: turnLimit,
            policy: effectivePolicy,
            bracket: effectiveBracket,
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
            commanders: parsed.commanders || [],
            bracket: effectiveBracket,
            template: "balanced",
            budget_max_usd: parseBudgetCap(budgetMaxUsd),
            sim_summary: simPayload.summary,
          }),
        },
        "Deck analysis",
      );
      if (activeRunRef.current !== runId) return;
      setAnalysis(ana);
      if (typeof ana?.bracket_report?.bracket === "number") {
        setBracket(Number(ana.bracket_report.bracket));
      }
      setTab("Deck Analysis");
      setMobilePane("views");
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
          if (authUser) {
            await saveCurrentProject({ silent: true });
          }
          updateStatus("done");
        } catch {
          if (activeRunRef.current !== runId) return;
          if (authUser) {
            await saveCurrentProject({ silent: true });
          }
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
    if (["idle", "done", "failed"].includes(normalizedStatus)) {
      setActiveAction("none");
    }
  }, [normalizedStatus]);

  useEffect(() => {
    const names = uniqueNonEmpty([
      ...collectBundleCardNames(currentSavedBundle),
      ...(analysis?.missing_roles || []).flatMap((row: any) => row?.cards || []),
      ...strictlyBetter.map((row: any) => row?.card),
      selectedCard,
    ]);
    if (!names.length) return;
    setDisplayMap({});
    void hydrateDisplay(names, artPreference, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [artPreference]);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    applySystemTheme(media);

    const syncTheme = () => {
      applySystemTheme(media);
    };

    if (typeof media.addEventListener === "function") {
      media.addEventListener("change", syncTheme);
      return () => media.removeEventListener("change", syncTheme);
    }
    media.addListener(syncTheme);
    return () => media.removeListener(syncTheme);
  }, []);

  useEffect(() => {
    if (!authChecked || draftRestoredRef.current || typeof window === "undefined") return;
    draftRestoredRef.current = true;
    try {
      const raw = window.localStorage.getItem(LOCAL_DRAFT_STORAGE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (!parsed?.saved_bundle || !parsed?.decklist_text) return;
      if (currentProjectId || hasMeaningfulDeckState) return;
      applySavedBundle(parsed, { isLocalDraft: true });
      setAuthNotice(`Recovered local draft from ${new Date(parsed.local_saved_at || Date.now()).toLocaleString()}.`);
    } catch {
      return;
    }
  }, [authChecked, currentProjectId, hasMeaningfulDeckState]);

  useEffect(() => {
    if (!authChecked || typeof window === "undefined") return;
    if (!hasMeaningfulDeckState) {
      window.localStorage.removeItem(LOCAL_DRAFT_STORAGE_KEY);
      setLocalDraftSavedAt("");
      return;
    }
    const timeout = window.setTimeout(() => {
      try {
        const nextSavedAt = new Date().toISOString();
        window.localStorage.setItem(
          LOCAL_DRAFT_STORAGE_KEY,
          JSON.stringify({
            ...currentProjectSnapshot,
            id: currentProjectId,
            local_saved_at: nextSavedAt,
          }),
        );
        setLocalDraftSavedAt(nextSavedAt);
      } catch {
        return;
      }
    }, 450);
    return () => window.clearTimeout(timeout);
  }, [authChecked, currentProjectId, currentProjectSnapshot, hasMeaningfulDeckState]);

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
    if (decklistPanelView === "Tagged Decklist" && !(tagRes?.tagged_lines || []).length) {
      setDecklistPanelView("Decklist");
    }
  }, [decklistPanelView, tagRes]);

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
            commanders: parseRes?.commanders || [],
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
  }, [selectedCard, tagRes, parseRes?.commander, parseRes?.commanders, budgetMaxUsd]);

  useEffect(() => {
    void (async () => {
      try {
        if (typeof window !== "undefined") {
          const stored = window.localStorage.getItem(AUTH_CSRF_STORAGE_KEY) || "";
          if (stored) setCsrfToken(stored);
          const params = new URLSearchParams(window.location.search);
          const linkedResetToken = params.get("reset_token") || "";
          if (linkedResetToken) {
            setResetToken(linkedResetToken);
            setAuthNotice("Magic link received. Choose a new password to finish recovery.");
          }
        }
        const payload = await requestJson("/api/auth/session", { method: "GET" }, "Session restore");
        setAuthUser(payload.user || null);
        persistCsrfToken(payload.csrf_token || "");
        if (payload.user) {
          const projectsPayload = await requestJson("/api/projects", { method: "GET" }, "Project list");
          setProjects(projectsPayload.projects || []);
        }
      } catch {
        setAuthUser(null);
        setProjects([]);
      } finally {
        setAuthChecked(true);
      }
    })();
  }, []);

  useEffect(() => {
    if (selectedCard) {
      setMobilePane("views");
    }
  }, [selectedCard]);

  useEffect(() => {
    if (resetToken) {
      setAccountOpen(true);
      setAccountTab("recover");
    }
  }, [resetToken]);

  useEffect(() => {
    if (authUser?.email && !authEmail) {
      setAuthEmail(authUser.email);
    }
    if (authUser) {
      if (accountTab === "login" || accountTab === "register" || accountTab === "recover") {
        setAccountTab("library");
      }
    } else if (accountTab === "library" || accountTab === "security") {
      setAccountTab("login");
    }
  }, [authUser, authEmail, accountTab]);

  useEffect(() => {
    if (!accountOpen || typeof window === "undefined") return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setAccountOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [accountOpen]);

  useEffect(() => {
    if (currentProjectId || projectName.trim()) return;
    const nextName = String(analysis?.deck_name || commanderLabel || "").trim();
    if (nextName) {
      setProjectName(nextName);
    }
  }, [analysis?.deck_name, commanderLabel, currentProjectId, projectName]);

  useEffect(() => {
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

  const sidebarProgressMeta = analysisProgressMeta.show ? analysisProgressMeta : decklistProgressMeta;
  const accountInitials = (authUser?.email || "dc")
    .split("@")[0]
    .split(/[\s._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part: string) => part[0]?.toUpperCase() || "")
    .join("") || "DC";
  const accountTriggerLabel = "Account";
  const accountTriggerMeta = authUser
    ? (hasUnsavedChanges ? "Unsaved changes" : `${projects.length} saved deck${projects.length === 1 ? "" : "s"}`)
    : "Sign in to save decks";
  const selectedArtPreference = ART_PREFERENCE_OPTIONS.find((option) => option.value === artPreference) || ART_PREFERENCE_OPTIONS[2];
  const activeAccountTab = resetToken
    ? "recover"
    : authUser
      ? (accountTab === "security" ? accountTab : "library")
      : (accountTab === "register" || accountTab === "recover" ? accountTab : "login");

  function renderAccountLibrary() {
    return (
      <div className="stack">
        <div className="sidebar-status-row">
          {currentProjectId ? (
            <span className="status-chip" data-tone={hasUnsavedChanges ? "warning" : "success"}>
              {hasUnsavedChanges ? "Unsaved changes" : "Saved"}
            </span>
          ) : null}
          {lastSavedAt ? (
            <span className="status-chip" data-tone="accent">
              Last saved {new Date(lastSavedAt).toLocaleDateString()}
            </span>
          ) : null}
          {localDraftSavedAt ? <span className="status-chip" data-tone="accent">Local backup</span> : null}
        </div>
        <div className="account-section-intro">
          <strong>Your deck library</strong>
          <span>Save the current deck, keep versions under one deck name, and reopen older snapshots when needed.</span>
        </div>
        <label>Saved deck name</label>
        <input
          className="input"
          value={projectName}
          onChange={(e) => setProjectName(e.target.value)}
          placeholder={analysis?.deck_name || commanderLabel || "Untitled Project"}
        />
        <div className="account-primary-actions">
          <button className="btn btn-primary" onClick={() => { void saveCurrentProject(); }} disabled={projectBusy || !hasMeaningfulDeckState || Boolean(currentProjectId && !hasUnsavedChanges)}>
            {projectBusy ? "Saving..." : currentProjectId ? (hasUnsavedChanges ? "Save new version" : "Already saved") : "Save current deck"}
          </button>
          <button className="btn" onClick={clearLocalDraft} disabled={!localDraftSavedAt}>
            Clear local draft
          </button>
        </div>
        {localDraftSavedAt ? <p className="control-help">Local draft backup from {new Date(localDraftSavedAt).toLocaleString()}.</p> : null}
        <div className="saved-projects-list">
          {(projects || []).map((project: any) => (
            <div key={project.id} className="saved-project-row">
              <div className="saved-project-row-header">
                <button className="saved-project-main" onClick={() => loadLatestProject(project.id)} disabled={projectBusy}>
                  <strong>{project.name || project.deck_name}</strong>
                  <span>{project.commander_label || project.deck_name}</span>
                  <span>{new Date(project.updated_at).toLocaleString()} · {project.version_count || 1} version{Number(project.version_count || 1) === 1 ? "" : "s"}</span>
                </button>
                <div className="saved-project-actions">
                  <button className="btn saved-project-history" onClick={() => toggleProjectVersions(project.id)} disabled={projectBusy}>
                    {expandedProjectId === project.id ? "Hide history" : "History"}
                  </button>
                  <button
                    className="btn saved-project-delete"
                    onClick={() => deleteProject(project.id)}
                    disabled={projectBusy}
                    aria-label={`Delete ${project.name || project.deck_name}`}
                  >
                    Delete
                  </button>
                </div>
              </div>
              <div className="saved-project-pills">
                {projectSummaryPills(project.summary).map((pill) => (
                  <span key={`${project.id}-${pill}`} className="saved-project-pill">
                    {pill}
                  </span>
                ))}
                {currentProjectId === project.id ? <span className="saved-project-pill is-current">Current</span> : null}
              </div>
              {expandedProjectId === project.id ? (
                <div className="saved-project-versions">
                  {(projectVersions[project.id] || []).map((version: any) => (
                    <button
                      key={version.id}
                      className="saved-project-version"
                      onClick={() => loadProjectVersion(project.id, version.id)}
                      disabled={projectBusy}
                    >
                      <strong>Version {version.version_number}</strong>
                      <span>{new Date(version.created_at).toLocaleString()}</span>
                      <span>{projectSummaryPills(version.summary).join(" · ")}</span>
                    </button>
                  ))}
                  {!(projectVersions[project.id] || []).length ? <p className="control-help">No version snapshots yet.</p> : null}
                </div>
              ) : null}
            </div>
          ))}
          {!projects.length ? <p className="control-help">No saved decks yet.</p> : null}
        </div>
      </div>
    );
  }

  function renderAccountSecurity() {
    return (
      <div className="stack">
        <div className="account-section-intro">
          <strong>Security</strong>
          <span>Manage recovery and the current session.</span>
        </div>
        {renderMiniCard({
          label: "Signed in as",
          value: authUser?.email || "Unknown user",
          surface: "2",
        })}
        <div className="account-primary-actions">
          <button className="btn" onClick={() => { setAuthEmail(authUser?.email || authEmail); void requestPasswordReset(); }} disabled={authBusy}>
            Email reset link
          </button>
          {authUser?.is_admin ? (
            <a className="btn" href="/admin">
              Open admin
            </a>
          ) : null}
          <button className="btn" onClick={handleLogout} disabled={authBusy}>
            Sign out
          </button>
        </div>
        <p className="control-help">Password recovery uses a one-time email magic link. Signing out keeps local draft backups on this device unless you clear them.</p>
      </div>
    );
  }

  function renderSignedOutAccount() {
    if (resetToken) {
      return (
        <div className="stack">
          <div className="account-section-intro">
            <strong>Finish recovery</strong>
            <span>This one-time link resets the password and signs you back in.</span>
          </div>
          <label>New password</label>
          <input className="input" type="password" value={resetPassword} onChange={(e) => setResetPassword(e.target.value)} placeholder="At least 10 characters" />
          <div className="account-primary-actions">
            <button className="btn btn-primary" onClick={confirmPasswordReset} disabled={authBusy}>Set new password</button>
            <button className="btn" onClick={() => { setResetToken(""); setResetPassword(""); clearResetTokenFromUrl(); setAuthNotice(""); setAccountTab("login"); }}>Back to sign in</button>
          </div>
        </div>
      );
    }

    return (
      <div className="stack">
        <div className="account-section-intro">
          <strong>{activeAccountTab === "register" ? "Create your account" : activeAccountTab === "recover" ? "Recover access" : "Sign in"}</strong>
          <span>{activeAccountTab === "recover" ? "Request a one-time reset link by email." : "Accounts save decklists, tagged outputs, analysis snapshots, and version history."}</span>
        </div>
        <label>Email</label>
        <input className="input" value={authEmail} onChange={(e) => setAuthEmail(e.target.value)} placeholder="you@example.com" />
        {activeAccountTab !== "recover" ? (
          <>
            <label>Password</label>
            <input className="input" type="password" value={authPassword} onChange={(e) => setAuthPassword(e.target.value)} placeholder="At least 10 characters" />
            <div className="account-primary-actions">
              <button className="btn btn-primary" onClick={() => handleAuth(activeAccountTab === "register" ? "register" : "login")} disabled={authBusy}>
                {activeAccountTab === "register" ? "Create account" : "Log in"}
              </button>
            </div>
          </>
        ) : (
          <div className="account-primary-actions">
            <button className="btn btn-primary" onClick={requestPasswordReset} disabled={authBusy}>Email reset link</button>
          </div>
        )}
        {localDraftSavedAt ? <p className="control-help">Local draft backup from {new Date(localDraftSavedAt).toLocaleString()}.</p> : null}
        <div className="account-primary-actions">
          <button className="btn" onClick={clearLocalDraft} disabled={!localDraftSavedAt}>Clear local draft</button>
        </div>
      </div>
    );
  }

  return (
    <div className={`ui-shell ${detailOpen ? "detail-open" : ""} mobile-pane-${mobilePane}`}>
      <div className="mobile-workspace-bar" role="tablist" aria-label="Workspace panels">
        <button
          type="button"
          className={`btn mobile-workspace-btn ${mobilePane === "controls" ? "active" : ""}`}
          aria-pressed={mobilePane === "controls"}
          onClick={() => setMobilePane("controls")}
        >
          Controls
        </button>
        <button
          type="button"
          className={`btn mobile-workspace-btn ${mobilePane === "deck" ? "active" : ""}`}
          aria-pressed={mobilePane === "deck"}
          onClick={() => setMobilePane("deck")}
        >
          Deck
        </button>
        <button
          type="button"
          className={`btn mobile-workspace-btn ${mobilePane === "views" ? "active" : ""}`}
          aria-pressed={mobilePane === "views"}
          onClick={() => setMobilePane("views")}
        >
          Views
        </button>
      </div>
      <button
        type="button"
        className="account-launcher"
        aria-haspopup="dialog"
        aria-expanded={accountOpen}
        aria-controls="account-drawer"
        onClick={() => setAccountOpen(true)}
      >
        <span className="account-launcher-avatar">{accountInitials}</span>
        <span className="account-launcher-copy">
          <strong>{accountTriggerLabel}</strong>
          <span>{accountTriggerMeta}</span>
        </span>
      </button>
      <aside className="ui-sidebar">
        <div className="sidebar-scroll stack">
          <div className="block stack sidebar-brand" data-surface="1">
            <h2 className="wordmark" aria-label="Deck.Check">
              <span className="wordmark-glyph">D</span>
              <span className="wordmark-text">
                Deck<span className="wordmark-dot">.</span>Check
              </span>
            </h2>
            {sidebarProgressMeta.show ? (
              <div className="sidebar-status-row">
                <span className="status-chip" data-tone={progressTone(sidebarProgressMeta)}>
                  {sidebarProgressMeta.label}
                </span>
              </div>
            ) : null}
          </div>

          <div className="sidebar-group sidebar-pane">
            <div className="sidebar-section-label">Import</div>
            <div className="stack">
              <label>Deck URL</label>
              <input
                ref={urlInputRef}
                className="input"
                value={moxfieldUrl}
                onChange={(e) => setMoxfieldUrl(e.target.value)}
                placeholder="Paste a deck URL"
              />
              <button className="btn" onClick={importFromUrl}>Analyze URL</button>
              <p className="control-help">Supported sources include Moxfield and Archidekt. If a source blocks access, paste the decklist instead.</p>
              <label>Card art style</label>
              <select className="select" value={artPreference} onChange={(e) => setArtPreference(normalizeArtPreference(e.target.value))}>
                {ART_PREFERENCE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <p className="control-help">{selectedArtPreference.description}</p>
              {urlImportNotice ? (
                <p className={`import-notice import-notice-${urlImportNotice.tone}`} data-tone={urlImportNotice.tone === "error" ? "danger" : urlImportNotice.tone === "warn" ? "warning" : "accent"}>
                  {urlImportNotice.text}
                </p>
              ) : null}
            </div>
          </div>

          <div className="sidebar-group sidebar-pane">
            <div className="sidebar-section-label">Table Assumptions</div>
            <div className="stack">
              <label>Inferred bracket</label>
              {renderMiniCard({
                label: "Inferred bracket",
                value: currentBracketReport ? `Bracket ${currentBracketValue}` : "Pending",
                surface: "2",
                help: currentBracketName || "Deck.Check will infer bracket from the deck once tagging starts.",
                children: <div className="control-help">{currentBracketName || "Deck.Check will infer bracket from the deck once tagging starts."}</div>,
              })}
              <p className="control-help">Deck.Check infers bracket from fast mana, tutors, combo density, Game Changers, and simulated speed when available.</p>

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
            </div>
          </div>
        </div>
        <div className="sidebar-footer">
          <button
            type="button"
            className={`btn sidebar-run-btn sidebar-run-btn-secondary ${randomDeckButtonProgress > 0 ? "is-progress-active" : ""}`}
            onClick={generateRandomDeck}
            title="Pick a random legal legendary-creature commander, build 38 lands, add 10-15 cheap instant-speed interaction, and fill the rest with commander-synergy cards."
            style={{ "--button-progress": `${randomDeckButtonProgress}%` } as CSSProperties}
          >
            <span className="sidebar-run-btn-label">Generate Random Deck</span>
          </button>
          <button
            type="button"
            className={`btn sidebar-run-btn sidebar-run-btn-secondary ${tagDeckButtonProgress > 0 ? "is-progress-active" : ""}`}
            onClick={runTagOnly}
            title="Parse, validate, tag, and open only the views that do not require simulation."
            style={{ "--button-progress": `${tagDeckButtonProgress}%` } as CSSProperties}
          >
            <span className="sidebar-run-btn-label">Tag Deck Only</span>
          </button>
          <button
            type="button"
            className={`btn btn-primary sidebar-run-btn ${fullAnalysisButtonProgress > 0 ? "is-progress-active" : ""}`}
            onClick={runPipeline}
            title="Fetch card data, goldfish results, and the full analysis stack."
            style={{ "--button-progress": `${fullAnalysisButtonProgress}%` } as CSSProperties}
          >
            <span className="sidebar-run-btn-label">Run Full Analysis</span>
          </button>
        </div>

      </aside>

      <section className="ui-detail">
        <div className="stack decklist-shell">
          <div className="panel-title-row">
            <div className="panel-heading-group">
              <div className="panel-kicker">Deck Intake</div>
              <h3>{analysis?.deck_name ? `Decklist: ${analysis.deck_name}` : "Decklist"}</h3>
              <div className="decklist-status-row">
                <span className="status-chip" data-tone={progressTone(decklistProgressMeta)}>
                  {decklistProgressMeta.show ? decklistProgressMeta.label : "Editing"}
                </span>
                <span className="status-chip" data-tone={parsedCount === 100 ? "success" : "warning"}>
                  {parsedCount ? `${parsedCount} cards` : "Unparsed"}
                </span>
                <span className="status-chip" data-tone={(parseRes?.errors || []).length === 0 ? "success" : "danger"}>
                  {(parseRes?.errors || []).length === 0 ? "Legal check clear" : "Needs fixes"}
                </span>
              </div>
            </div>
            {decklistProgressMeta.show ? (
              <InlinePanelProgress
                label={decklistProgressMeta.label}
                percent={decklistProgressMeta.percent}
                detail={decklistProgressMeta.detail}
                tone={decklistProgressMeta.tone}
                ariaLabel={`Decklist processing progress: ${decklistProgressMeta.label}, ${decklistProgressMeta.percent}%`}
              />
            ) : null}
          </div>
          <div className="block stack decklist-panel" data-surface="1">
            <div className="kpi-grid">
              {renderMiniCard({
                label: "Commander",
                value: commanderLabel,
                tone: "accent",
              })}
              {renderMiniCard({
                label: "Card Count",
                value: parsedCount || "n/a",
                tone: parsedCount === 100 ? "success" : "warning",
                valueClassName: parsedCount === 100 ? "tone-good" : "tone-warn",
              })}
              {renderMiniCard({
                label: "Deck legality",
                value: (parseRes?.errors || []).length === 0 ? "Legal" : String((parseRes?.errors || [])[0] || "Illegal"),
                tone: (parseRes?.errors || []).length === 0 ? "success" : "danger",
                valueClassName: (parseRes?.errors || []).length === 0 ? "tone-good" : "tone-bad",
              })}
              {renderMiniCard({
                label: "Auto Win Plans",
                value: detectedWincons.length ? detectedWincons.join(", ") : "n/a",
                tone: "accent",
              })}
              {renderMiniCard({
                label: "Color Identity",
                value: colorIdentitySize === 0 ? "Colorless" : (colorIdentity.join("") || "n/a"),
                tone: "accent",
              })}
            </div>
            <div className="decklist-mode-bar">
              <button
                type="button"
                className={`btn ${decklistPanelView === "Decklist" ? "active" : ""}`}
                onClick={() => setDecklistPanelView("Decklist")}
              >
                Decklist
              </button>
              <button
                type="button"
                className={`btn ${decklistPanelView === "Tagged Decklist" ? "active" : ""}`}
                onClick={() => setDecklistPanelView("Tagged Decklist")}
                disabled={!(tagRes?.tagged_lines || []).length}
              >
                Tagged Decklist
              </button>
              {decklistPanelView === "Tagged Decklist" ? (
                <>
                  <button
                    className="btn"
                    onClick={async () => {
                      const text = tagRes?.tagged_lines?.join("\n") || "";
                      await navigator.clipboard.writeText(text);
                    }}
                  >
                    Copy tagged decklist
                  </button>
                  <span className="muted decklist-mode-note">Copy-ready export with Moxfield-compatible tags.</span>
                </>
              ) : null}
            </div>

            {decklistPanelView === "Decklist" ? (
              <textarea ref={decklistInputRef} className="textarea decklist-textarea" value={decklist} onChange={(e) => setDecklist(e.target.value)} />
            ) : (
              <div className="mono decklist-tagged-export">
                {tagRes?.tagged_lines?.join("\n") || "Run analysis to populate tagged lines."}
              </div>
            )}

            {(parseRes?.errors || []).length > 0 && (
              <div className="tone-card" data-surface="3" data-tone="danger">
                <strong>Blocking Errors</strong>
                <ul className="list-compact">
                  {(parseRes?.errors || []).map((e: string, i: number) => <li key={i}>{e}</li>)}
                </ul>
              </div>
            )}

            {bracketViolations.length > 0 && (
              <div className="tone-card" data-surface="3" data-tone="warning">
                <strong>Bracket Issues</strong>
                <ul className="list-compact">
                  {bracketViolations.map((e: string, i: number) => <li key={i}>{e}</li>)}
                </ul>
              </div>
            )}

            {(tagRes?.cards || []).length > 0 && (
              <div className="decklist-preview">
                <strong>Card Preview</strong>
                <div className="card-preview-scroll">
                  <table className="table card-preview-table" style={{ marginTop: 6 }}>
                    <thead>
                      <tr><th>Card</th><th>Role hint</th></tr>
                    </thead>
                    <tbody>
                      {(tagRes?.cards || []).map((c: any, i: number) => {
                        const isCommanderCard = c?.section === "commander";
                        return (
                        <tr
                          key={`${c.name}-${i}`}
                          onClick={() => setSelectedCard(c.name)}
                          className={`card-preview-row ${isCommanderCard ? "is-commander" : ""}`}
                        >
                          <td className="card-preview-cell">
                            {cardThumb(c.name) ? (
                              <img src={cardThumb(c.name)} alt={c.name} width={34} height={48} loading="lazy" className="card-preview-thumb" />
                            ) : (
                              <div className="card-preview-thumb card-preview-thumb-placeholder" />
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
          </div>
        </div>
      </section>

      <main className={`ui-main ${selectedCard ? "insight-open" : ""}`}>
        <div className="outcome-shell">
        <div className="outcome-content">
        <div className="stack outcome-header">
          <div className="panel-title-row">
            <div className="panel-heading-group">
              <div className="panel-kicker">Analysis Stage</div>
              <h3>{hasOutcomeResources ? tab : "View Panel"}</h3>
              {analysisProgressMeta.show || hasOutcomeResources ? (
                <div className="decklist-status-row">
                  <span className="status-chip" data-tone={progressTone(analysisProgressMeta)}>
                    {analysisProgressMeta.show ? analysisProgressMeta.label : "Ready"}
                  </span>
                  <span className="status-chip" data-tone={hasOutcomeResources ? "success" : "default"}>
                    {hasOutcomeResources ? "Resources loaded" : "Waiting on analysis"}
                  </span>
                </div>
              ) : null}
            </div>
            {analysisProgressMeta.show ? (
              <InlinePanelProgress
                label={analysisProgressMeta.label}
                percent={analysisProgressMeta.percent}
                detail={analysisProgressMeta.detail}
                tone={analysisProgressMeta.tone}
                ariaLabel={`Analysis progress: ${analysisProgressMeta.label}, ${analysisProgressMeta.percent}%`}
              />
            ) : null}
          </div>
          {hasOutcomeResources ? (
            <>
              <div className="tab-bucket-list" role="tablist" aria-label="Workspace sections">
                {availableTabGroups.map((group) => {
                  const isActive = group.label === activeTabGroup;
                  return (
                    <button
                      key={group.label}
                      type="button"
                      className={`btn tab-btn ${isActive ? "active" : ""}`}
                      onClick={() => {
                        const nextTab = group.tabs.find((groupTab) => availableTabs.includes(groupTab as any));
                        if (nextTab) setTab(nextTab);
                      }}
                    >
                      {group.label}
                    </button>
                  );
                })}
              </div>
              {visibleGroupTabs.length > 1 ? (
                <div className="tab-list tab-subnav" role="tablist" aria-label={`${activeTabGroup} views`}>
                  {visibleGroupTabs.map((t) => (
                    <button key={t} className={`btn tab-btn ${tab === t ? "active" : ""}`} onClick={() => setTab(t as TabName)}>{t}</button>
                  ))}
                </div>
              ) : null}
            </>
          ) : null}
        </div>

        <div className="block outcome-body" data-surface="1">
          {!hasOutcomeResources ? (
            <div className="resource-empty-state">
              <div className="resource-empty-brand" aria-hidden="true">
                <span className="wordmark-glyph">D</span>
                <span className="wordmark-text">
                  Deck<span className="wordmark-dot">.</span>Check
                </span>
              </div>
              <p className="resource-empty-caption">Nothing to show yet</p>
            </div>
          ) : (
            <>
          {tab === "Deck Analysis" && (
            <div className="guide-rendered">
              <h2>Key Findings</h2>
              <ul>
                {findings.map((f, i) => <li key={i}>{f}</li>)}
              </ul>

              <h2>Deck Health Summary</h2>
              <div className="kpi-grid">
                {Object.entries(analysis?.health_summary || {}).map(([k, v]: any) =>
                  renderMiniCard({
                    label: k.replaceAll("_", " "),
                    value: `${v?.score ?? "n/a"} (${v?.status || "n/a"})`,
                    tone: v?.status === "healthy" ? "success" : v?.status === "warning" ? "warning" : "danger",
                    valueClassName: v?.status === "healthy" ? "tone-good" : v?.status === "warning" ? "tone-warn" : "tone-bad",
                    help: v?.explanation || undefined,
                    children: (
                      <>
                        <div className="control-help">{v?.explanation || ""}</div>
                        <div className="control-help"><strong>Good:</strong> {HEALTH_HELP[k]?.good || "Higher is better."}</div>
                        <div className="control-help"><strong>Bad:</strong> {HEALTH_HELP[k]?.bad || "Lower scores indicate structural weakness."}</div>
                        <div className="control-help"><strong>Fix:</strong> {HEALTH_HELP[k]?.action || "Tune cards supporting early consistency."}</div>
                      </>
                    ),
                  })
                )}
              </div>
              <ul className="list-compact">
                <li><strong>Resilience:</strong> good around 70+, warning below 55.</li>
                <li><strong>Redundancy:</strong> good around 60+, low means too much dependence on a few cards.</li>
                <li><strong>Bottleneck index:</strong> lower is better; very high means fragile core dependency.</li>
                <li><strong>Role entropy:</strong> very low can mean one-dimensional plan; very high can mean lack of focus.</li>
              </ul>
              <p><strong>Consistency Score:</strong> {analysis?.consistency_score ?? "n/a"} / 100</p>

              <h2>Deck Identity</h2>
              <p>
                <strong>Commander:</strong> {commanderLabel}
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
              {(typeThemeProfile?.card_types?.length || typeThemeProfile?.creature_subtypes?.length || typeThemeProfile?.package_signals?.length) ? (
                <>
                  {(typeThemeProfile?.deck_theme_tags || []).length ? (
                    <p>
                      <strong>Deck theme tags:</strong>{" "}
                      {(typeThemeProfile?.deck_theme_tags || []).join(", ")}
                    </p>
                  ) : null}
                  <p>
                    <strong>Type signals:</strong>{" "}
                    {(typeThemeProfile?.card_types || [])
                      .slice(0, 4)
                      .map((row: any) => `${row.name} (${row.count})`)
                      .join(", ") || "n/a"}
                  </p>
                  <p>
                    <strong>Subtype signals:</strong>{" "}
                    {(typeThemeProfile?.creature_subtypes || typeThemeProfile?.subtypes || [])
                      .slice(0, 4)
                      .map((row: any) => `${row.name} (${row.count})`)
                      .join(", ") || "n/a"}
                  </p>
                  {typeThemeProfile?.dominant_creature_subtype ? (
                    <p>
                      <strong>Typal anchor:</strong> {typeThemeProfile.dominant_creature_subtype.name} ({typeThemeProfile.dominant_creature_subtype.count} cards)
                    </p>
                  ) : null}
                  {(typeThemeProfile?.package_signals || []).length ? (
                    <ul className="list-compact">
                      {(typeThemeProfile.package_signals || []).slice(0, 3).map((line: string, i: number) => (
                        <li key={i}>{line}</li>
                      ))}
                    </ul>
                  ) : null}
                </>
              ) : null}

              <h2>Deck Intent</h2>
              <p><strong>Primary plan:</strong> {intentSummary?.primary_plan || "n/a"}</p>
              <p><strong>Secondary plan:</strong> {intentSummary?.secondary_plan || "n/a"}</p>
              <p><strong>Main kill vectors:</strong> {(intentSummary?.kill_vectors || []).join(", ") || "n/a"}</p>
              <p><strong>Confidence:</strong> {typeof intentSummary?.confidence === "number" ? `${(intentSummary.confidence * 100).toFixed(1)}%` : "n/a"}</p>
              <p><strong>Combo support score:</strong> {comboIntel?.combo_support_score ?? 0} / 100</p>
              <p><strong>Complete combos in list:</strong> {comboComplete.length}</p>
              <p className="control-help">
                Use the <strong>Combos</strong> tab for the full combo catalog already contained in this deck and the closest one-card-away lines.
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

              <details className="block">
                <summary><strong>Advanced analysis</strong></summary>
                <div className="stack" style={{ marginTop: 16 }}>
                  <h2>Complex Systems Lens</h2>
                  <div className="kpi-grid">
                    {renderMiniCard({
                      label: "Resilience",
                      value: analysis?.systems_metrics?.resilience_score ?? "n/a",
                      help: analysis?.systems_metrics?.interpretation?.resilience_score,
                      children: analysis?.systems_metrics?.interpretation?.resilience_score ? <div className="control-help">{analysis.systems_metrics.interpretation.resilience_score}</div> : null,
                    })}
                    {renderMiniCard({
                      label: "Redundancy",
                      value: analysis?.systems_metrics?.redundancy_score ?? "n/a",
                      help: analysis?.systems_metrics?.interpretation?.redundancy_score,
                      children: analysis?.systems_metrics?.interpretation?.redundancy_score ? <div className="control-help">{analysis.systems_metrics.interpretation.redundancy_score}</div> : null,
                    })}
                    {renderMiniCard({
                      label: "Bottleneck Index",
                      value: analysis?.systems_metrics?.bottleneck_index ?? "n/a",
                      help: analysis?.systems_metrics?.interpretation?.bottleneck_index,
                      children: analysis?.systems_metrics?.interpretation?.bottleneck_index ? <div className="control-help">{analysis.systems_metrics.interpretation.bottleneck_index}</div> : null,
                    })}
                    {renderMiniCard({
                      label: "Role Entropy",
                      value: `${analysis?.systems_metrics?.role_entropy_bits ?? "n/a"} bits`,
                      help: analysis?.systems_metrics?.interpretation?.role_entropy_bits,
                      children: analysis?.systems_metrics?.interpretation?.role_entropy_bits ? <div className="control-help">{analysis.systems_metrics.interpretation.role_entropy_bits}</div> : null,
                    })}
                  </div>

                  <h2>Tagging Diagnostics</h2>
                  <ul>
                    <li>Untagged cards: {analysis?.tag_diagnostics?.untagged_count ?? 0}</li>
                    <li>Potentially over-tagged cards: {analysis?.tag_diagnostics?.overloaded_count ?? 0}</li>
                    <li>Multi-role cards: {analysis?.tag_diagnostics?.multi_role_count ?? 0}</li>
                  </ul>
                  <p className="muted">This helps challenge the tagging system and identify where manual overrides or tighter regex rules are needed.</p>

                  <h2>Data Provenance</h2>
                  <ul>
                    {(integrationsMeta?.integrations || []).map((i: any, idx: number) => (
                      <li key={idx}>
                        <strong>{i.key}</strong> ({i.status}): {i.purpose} <a href={i.url} target="_blank" rel="noreferrer">[source]</a>
                      </li>
                    ))}
                  </ul>
                </div>
              </details>
            </div>
          )}

          {tab === "Combos" && (
            <div className="guide-rendered">
              <div className="kpi-grid">
                {renderMiniCard({
                  label: "Complete lines",
                  value: comboComplete.length,
                  valueClassName: "tone-good",
                  help: "How many full combo lines are already completely present in the deck.",
                  children: <div className="control-help">Known combo lines already fully contained in this decklist.</div>,
                })}
                {renderMiniCard({
                  label: "Combo support score",
                  value: `${comboIntel?.combo_support_score ?? 0} / 100`,
                  help: "A rough score for how much complete combo support is already present in the list.",
                  children: <div className="control-help">Higher means more complete combo lines are already contained in the list.</div>,
                })}
                {renderMiniCard({
                  label: "One-card-away lines",
                  value: comboNearMiss.length,
                  help: "How many legal combo lines are missing exactly one card from the deck.",
                  children: <div className="control-help">Lines where this deck is missing exactly one legal card.</div>,
                })}
              </div>

              <section className="combo-section">
                <h2 className="combo-section-title">Complete Combos In This Deck</h2>
                {comboComplete.length === 0 ? (
                  <p className="muted">No complete combo lines detected in the current list.</p>
                ) : (
                  comboComplete.map((variant: any, i: number) => (
                    <article key={`combo-complete-${variant?.variant_id || i}`} className="combo-line">
                      {renderComboGrid(variant?.cards || [], `combo-complete-all-${i}`, {
                        emptyText: "No cards listed for this combo.",
                      })}
                      {variant?.recipe ? (
                        <p className="combo-line-recipe"><ManaText text={variant.recipe} /></p>
                      ) : null}
                      {variant?.source_url ? (
                        <a className="combo-line-link" href={variant.source_url} target="_blank" rel="noreferrer">
                          Open on CommanderSpellbook
                        </a>
                      ) : null}
                    </article>
                  ))
                )}
              </section>

              <section className="combo-section">
                <h2 className="combo-section-title">One Card Away</h2>
                {comboNearMiss.length === 0 ? (
                  <p className="muted">No one-card-away combo lines detected in the current list.</p>
                ) : (
                  comboNearMiss.map((variant: any, i: number) => (
                    <article key={`combo-nearmiss-${variant?.variant_id || i}`} className="combo-line">
                      {renderComboGrid([...(variant?.present_cards || []), ...(variant?.missing_cards || [])], `combo-nearmiss-all-${i}`, {
                        dimmedNames: variant?.missing_cards || [],
                        emptyText: "No cards listed for this combo.",
                      })}
                      {variant?.recipe ? (
                        <p className="combo-line-recipe"><ManaText text={variant.recipe} /></p>
                      ) : null}
                      {variant?.source_url ? (
                        <a className="combo-line-link" href={variant.source_url} target="_blank" rel="noreferrer">
                          Open on CommanderSpellbook
                        </a>
                      ) : null}
                    </article>
                  ))
                )}
              </section>
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
                    <CartesianGrid {...chartGridProps} />
                    <XAxis {...chartAxisProps} dataKey="turn" label={chartLabel("Turn", "insideBottom")} />
                    <YAxis {...chartAxisProps} label={chartLabel("Mana sources", "insideLeft", { angle: -90 })} />
                    <Tooltip {...chartTooltipProps} />
                    <Line {...chartMotion("lenses-mana-percentiles", 0)} type="monotone" dataKey="p50" stroke={currentChartTheme.series.primary} strokeWidth={2.4} dot={false} />
                    <Line {...chartMotion("lenses-mana-percentiles", 1)} type="monotone" dataKey="p75" stroke={currentChartTheme.series.secondary} strokeWidth={2.2} dot={false} />
                    <Line {...chartMotion("lenses-mana-percentiles", 2)} type="monotone" dataKey="p90" stroke={currentChartTheme.series.quaternary} strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("mana_percentiles")}

              {renderMetricHelp("land_hit_cdf")}
              <div ref={chartViewportRef("lenses-land-hit-cdf")} style={{ width: "100%", height: 220 }}>
                <ResponsiveContainer>
                  <LineChart data={graphPayloads?.land_hit_cdf || []}>
                    <CartesianGrid {...chartGridProps} />
                    <XAxis {...chartAxisProps} dataKey="turn" label={chartLabel("Turn", "insideBottom")} />
                    <YAxis {...chartAxisProps} domain={[0, 1]} label={chartLabel("Probability", "insideLeft", { angle: -90 })} />
                    <Tooltip {...chartTooltipProps} formatter={(v: any) => `${(Number(v) * 100).toFixed(1)}%`} />
                    <Line {...chartMotion("lenses-land-hit-cdf", 0)} type="monotone" dataKey="p_hit_on_curve" stroke={currentChartTheme.series.primary} strokeWidth={2.5} dot={false} />
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
                      <CartesianGrid {...chartGridProps} />
                      <XAxis {...chartAxisProps} dataKey="turn" label={chartLabel("Turn", "insideBottom")} />
                      <YAxis {...chartAxisProps} yAxisId="left" domain={[0, Math.max(2, colorIdentitySize)]} label={chartLabel("Colors online", "insideLeft", { angle: -90 })} />
                      <YAxis {...chartAxisProps} yAxisId="right" orientation="right" domain={[0, 1]} label={chartLabel("P(full identity)", "insideRight", { angle: 90 })} />
                      <Tooltip {...chartTooltipProps} formatter={(v: any, k: any) => (String(k).includes("p_") ? `${(Number(v) * 100).toFixed(1)}%` : Number(v).toFixed(2))} />
                      <Legend {...chartLegendProps} />
                      <Line {...chartMotion("lenses-color-access", 0)} yAxisId="left" type="monotone" dataKey="avg_colors" stroke={currentChartTheme.series.secondary} strokeWidth={2.4} name="Avg colors online" dot={false} />
                      <Line {...chartMotion("lenses-color-access", 1)} yAxisId="right" type="monotone" dataKey="p_full_identity" stroke={currentChartTheme.series.primary} strokeWidth={2.1} name="P(full identity online)" dot={false} />
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
                    <CartesianGrid {...chartGridProps} />
                    <XAxis {...chartAxisProps} dataKey="turn" label={chartLabel("Turn", "insideBottom")} />
                    <YAxis {...chartAxisProps} domain={[0, 1]} label={chartLabel("Share of games", "insideLeft", { angle: -90 })} />
                    <Tooltip {...chartTooltipProps} formatter={(v: any) => `${(Number(v) * 100).toFixed(1)}%`} />
                    <Legend {...chartLegendProps} />
                    <Area {...chartMotion("lenses-phase-timeline", 0)} type="monotone" dataKey="setup" stackId="1" stroke={currentChartTheme.series.quaternary} fill={currentChartTheme.series.muted3} />
                    <Area {...chartMotion("lenses-phase-timeline", 1)} type="monotone" dataKey="engine" stackId="1" stroke={currentChartTheme.series.secondary} fill={currentChartTheme.series.muted2} />
                    <Area {...chartMotion("lenses-phase-timeline", 2)} type="monotone" dataKey="win_attempt" stackId="1" stroke={currentChartTheme.series.primary} fill={currentChartTheme.series.primary} fillOpacity={0.7} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("phase_timeline")}

              {renderMetricHelp("win_turn_cdf")}
              <div ref={chartViewportRef("lenses-win-turn-cdf")} style={{ width: "100%", height: 220 }}>
                <ResponsiveContainer>
                  <LineChart data={graphPayloads?.win_turn_cdf || []}>
                    <CartesianGrid {...chartGridProps} />
                    <XAxis {...chartAxisProps} dataKey="turn" label={chartLabel("Turn", "insideBottom")} />
                    <YAxis {...chartAxisProps} domain={[0, 1]} label={chartLabel("Cumulative probability", "insideLeft", { angle: -90 })} />
                    <Tooltip {...chartTooltipProps} formatter={(v: any) => `${(Number(v) * 100).toFixed(1)}%`} />
                    <Line {...chartMotion("lenses-win-turn-cdf", 0)} type="monotone" dataKey="cdf" stroke={currentChartTheme.series.positive} strokeWidth={2.5} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("win_turn_cdf")}

              <h2>Risk Lens</h2>
              {renderMetricHelp("no_action_funnel")}
              <div ref={chartViewportRef("lenses-no-action-funnel")} style={{ width: "100%", height: 220 }}>
                <ResponsiveContainer>
                  <LineChart data={graphPayloads?.no_action_funnel || []}>
                    <CartesianGrid {...chartGridProps} />
                    <XAxis {...chartAxisProps} dataKey="turn" label={chartLabel("Turn", "insideBottom")} />
                    <YAxis {...chartAxisProps} domain={[0, 1]} label={chartLabel("No-action probability", "insideLeft", { angle: -90 })} />
                    <Tooltip {...chartTooltipProps} formatter={(v: any) => `${(Number(v) * 100).toFixed(1)}%`} />
                    <Line {...chartMotion("lenses-no-action-funnel", 0)} type="monotone" dataKey="p_no_action" stroke={currentChartTheme.series.danger} strokeWidth={2.5} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("no_action_funnel")}

              {renderMetricHelp("dead_cards_top")}
              <div ref={chartViewportRef("lenses-dead-cards-top")} style={{ width: "100%", height: 260 }}>
                <ResponsiveContainer>
                  <BarChart data={(graphPayloads?.dead_cards_top || []).slice(0, 10)}>
                    <CartesianGrid {...chartGridProps} />
                    <XAxis {...chartAxisProps} dataKey="card" hide />
                    <YAxis {...chartAxisProps} label={chartLabel("Stranded rate", "insideLeft", { angle: -90 })} />
                    <Tooltip {...chartTooltipProps} formatter={(v: any) => `${(Number(v) * 100).toFixed(1)}%`} />
                    <Bar {...chartMotion("lenses-dead-cards-top", 0)} dataKey="rate" fill={currentChartTheme.series.quaternary} radius={[8, 8, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("dead_cards_top")}

              <h2>Operational Lens</h2>
              {renderMetricHelp("commander_cast_distribution")}
              <div ref={chartViewportRef("lenses-commander-cast")} style={{ width: "100%", height: 220 }}>
                <ResponsiveContainer>
                  <BarChart data={graphPayloads?.commander_cast_distribution || []}>
                    <CartesianGrid {...chartGridProps} />
                    <XAxis {...chartAxisProps} dataKey="turn" label={chartLabel("Cast turn", "insideBottom")} />
                    <YAxis {...chartAxisProps} label={chartLabel("Rate", "insideLeft", { angle: -90 })} />
                    <Tooltip {...chartTooltipProps} formatter={(v: any) => `${(Number(v) * 100).toFixed(1)}%`} />
                    <Bar {...chartMotion("lenses-commander-cast", 0)} dataKey="rate" fill={currentChartTheme.series.primary} radius={[8, 8, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("commander_cast_distribution")}
              {renderMetricHelp("mulligan_funnel")}
              <div ref={chartViewportRef("lenses-mulligan-funnel")} style={{ width: "100%", height: 220 }}>
                <ResponsiveContainer>
                  <BarChart data={graphPayloads?.mulligan_funnel || []}>
                    <CartesianGrid {...chartGridProps} />
                    <XAxis {...chartAxisProps} dataKey="mulligans" label={chartLabel("Mulligans taken", "insideBottom")} />
                    <YAxis {...chartAxisProps} label={chartLabel("Rate", "insideLeft", { angle: -90 })} />
                    <Tooltip {...chartTooltipProps} formatter={(v: any) => `${(Number(v) * 100).toFixed(1)}%`} />
                    <Bar {...chartMotion("lenses-mulligan-funnel", 0)} dataKey="rate" fill={currentChartTheme.series.secondary} radius={[8, 8, 0, 0]} />
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
                    <CartesianGrid {...chartGridProps} />
                    <XAxis {...chartAxisProps} dataKey="metric" label={chartLabel("Metric", "insideBottom")} />
                    <YAxis {...chartAxisProps} label={chartLabel("Score", "insideLeft", { angle: -90 })} />
                    <Tooltip {...chartTooltipProps} />
                    <Bar {...chartMotion("lenses-systems-metrics", 0)} dataKey="value" fill={currentChartTheme.series.primary} radius={[8, 8, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {tab === "Rules Watchouts" && (
            <div className="guide-rendered">
              <div className="rules-watchout-list">
                {rulesWatchoutRows.map((w: any, i: number) =>
                  renderCardDetailRow({
                    rowKey: `watchout-${w.card}-${i}`,
                    title: w.card,
                    imageCard: w.card,
                    badge: w.commander ? "Commander" : undefined,
                    sections: [
                      w.errata?.length
                        ? {
                            label: "Errata",
                            content: (
                              <ul className="list-compact">
                                {w.errata.map((item: string, j: number) => <li key={`errata-${j}`}>{item}</li>)}
                              </ul>
                            ),
                          }
                        : null,
                      w.notes?.length
                        ? {
                            label: "Notes",
                            content: (
                              <ul className="list-compact">
                                {w.notes.map((item: string, j: number) => <li key={`notes-${j}`}>{item}</li>)}
                              </ul>
                            ),
                          }
                        : null,
                      w.rulesInfo?.length
                        ? {
                            label: "Rules information",
                            content: (
                              <ul className="list-compact">
                                {w.rulesInfo.map((item: string, j: number) => <li key={`rules-${j}`}>{item}</li>)}
                              </ul>
                            ),
                          }
                        : null,
                    ],
                  }),
                )}
              </div>
              {rulesWatchoutRows.length === 0 && <p>No major watchouts detected for this list.</p>}
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
                              renderComboGrid(
                                (row.cards || []).map((x: any) => ({
                                  name: x.name,
                                  label: `${x.qty}x ${x.name}`,
                                })),
                                `role-${row.role}`,
                                { emptyText: "No cards mapped for this role in current tagged list." },
                              )
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
                {analysis?.bracket_report?.source === "inferred" ? "Inferred bracket" : "Bracket"} {analysis?.bracket_report?.bracket ?? currentBracketValue}
                {analysis?.bracket_report?.bracket_name ? ` (${analysis?.bracket_report?.bracket_name})` : currentBracketName ? ` (${currentBracketName})` : ""}.
              </p>
              <p className="control-help">
                Criteria below include official limits and bracket-aligned heuristics. Official failures are compliance issues; heuristic misses are guidance.
              </p>
              {(analysis?.bracket_report?.inference?.reasoning || []).length > 0 && (
                <ul className="control-help">
                  {(analysis?.bracket_report?.inference?.reasoning || []).map((reason: string, i: number) => <li key={i}>{reason}</li>)}
                </ul>
              )}
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
                                      className="table-card-thumb"
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
                {renderMiniCard({
                  label: "Total Colored Pips",
                  value: Number(manabaseSummary?.total_colored_pips || 0).toFixed(1),
                })}
                {renderMiniCard({
                  label: "Colorless/Generic Pips",
                  value: Number(manabaseSummary?.total_colorless_pips || 0).toFixed(1),
                })}
                {renderMiniCard({
                  label: "Weighted Sources",
                  value: Number(manabaseSummary?.total_weighted_sources || 0).toFixed(1),
                })}
                {renderMiniCard({
                  label: "Most Stressed Color",
                  value: (
                    <>
                      {manabaseSummary?.most_stressed_color || "n/a"}{" "}
                      {manabaseSummary?.most_stressed_color ? `(${Number(manabaseSummary?.most_stressed_gap_pct || 0).toFixed(1)} pp)` : ""}
                    </>
                  ),
                  tone: Number(manabaseSummary?.most_stressed_gap_pct || 0) < -8 ? "danger" : Number(manabaseSummary?.most_stressed_gap_pct || 0) < -3 ? "warning" : "success",
                  valueClassName: Number(manabaseSummary?.most_stressed_gap_pct || 0) < -8 ? "tone-bad" : Number(manabaseSummary?.most_stressed_gap_pct || 0) < -3 ? "tone-warn" : "tone-good",
                })}
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
                    <CartesianGrid {...chartGridProps} />
                    <XAxis {...chartAxisProps} dataKey="color" label={chartLabel("Color", "insideBottom")} />
                    <YAxis {...chartAxisProps} label={chartLabel("Pip demand", "insideLeft", { angle: -90 })} />
                    <Tooltip {...chartTooltipProps} formatter={(v: any) => Number(v).toFixed(2)} />
                    <Legend {...chartLegendProps} />
                    <Bar {...chartMotion("manabase-pip-distribution", 0)} dataKey="early" stackId="pips" fill={currentChartTheme.series.secondary} name="Early (MV<=2)" radius={[8, 8, 0, 0]} />
                    <Bar {...chartMotion("manabase-pip-distribution", 1)} dataKey="mid" stackId="pips" fill={currentChartTheme.series.primary} name="Mid (MV3-4)" radius={[8, 8, 0, 0]} />
                    <Bar {...chartMotion("manabase-pip-distribution", 2)} dataKey="late" stackId="pips" fill={currentChartTheme.series.tertiary} name="Late (MV5+)" radius={[8, 8, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("manabase_pip_distribution")}

              <h2>Source Coverage by Color</h2>
              {renderMetricHelp("manabase_source_coverage")}
              <div ref={chartViewportRef("manabase-source-coverage")} style={{ width: "100%", height: 260 }}>
                <ResponsiveContainer>
                  <BarChart data={graphPayloads?.manabase_source_coverage || []}>
                    <CartesianGrid {...chartGridProps} />
                    <XAxis {...chartAxisProps} dataKey="color" label={chartLabel("Color", "insideBottom")} />
                    <YAxis {...chartAxisProps} label={chartLabel("Source count", "insideLeft", { angle: -90 })} />
                    <Tooltip {...chartTooltipProps} formatter={(v: any) => Number(v).toFixed(2)} />
                    <Legend {...chartLegendProps} />
                    <Bar {...chartMotion("manabase-source-coverage", 0)} dataKey="land_sources" stackId="src" fill={currentChartTheme.series.primary} name="Land sources" radius={[8, 8, 0, 0]} />
                    <Bar {...chartMotion("manabase-source-coverage", 1)} dataKey="nonland_sources" stackId="src" fill={currentChartTheme.series.slateSoft} name="Nonland sources" radius={[8, 8, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("manabase_source_coverage")}

              <h2>Demand vs Supply Gap</h2>
              {renderMetricHelp("manabase_balance_gap")}
              <div ref={chartViewportRef("manabase-balance-gap")} style={{ width: "100%", height: 260 }}>
                <ResponsiveContainer>
                  <BarChart data={graphPayloads?.manabase_balance_gap || []}>
                    <CartesianGrid {...chartGridProps} />
                    <XAxis {...chartAxisProps} dataKey="color" label={chartLabel("Color", "insideBottom")} />
                    <YAxis {...chartAxisProps} label={chartLabel("Share", "insideLeft", { angle: -90 })} />
                    <Tooltip {...chartTooltipProps} formatter={(v: any) => `${(Number(v) * 100).toFixed(1)}%`} />
                    <Legend {...chartLegendProps} />
                    <Bar {...chartMotion("manabase-balance-gap", 0)} dataKey="demand_share" fill={currentChartTheme.series.warning} name="Demand share" radius={[8, 8, 0, 0]} />
                    <Bar {...chartMotion("manabase-balance-gap", 1)} dataKey="source_share" fill={currentChartTheme.series.positive} name="Source share" radius={[8, 8, 0, 0]} />
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
                    <CartesianGrid {...chartGridProps} />
                    <XAxis {...chartAxisProps} dataKey="mana_value" label={chartLabel("Mana value", "insideBottom")} />
                    <YAxis {...chartAxisProps} yAxisId="left" label={chartLabel("Card count", "insideLeft", { angle: -90 })} />
                    <YAxis {...chartAxisProps} yAxisId="right" orientation="right" domain={[0, 1]} label={chartLabel("P(on curve)", "insideRight", { angle: 90 })} />
                    <Tooltip
                      {...chartTooltipProps}
                      formatter={(v: any, name: any) => {
                        if (String(name).includes("p_on_curve")) return `${(Number(v) * 100).toFixed(1)}%`;
                        return Number(v).toFixed(1);
                      }}
                    />
                    <Legend {...chartLegendProps} />
                    <Bar
                      {...chartMotion("manabase-curve-histogram", 0)}
                      yAxisId="left"
                      dataKey="permanents"
                      stackId="curve"
                      fill={currentChartTheme.series.secondary}
                      name="Permanents"
                      radius={[8, 8, 0, 0]}
                      onClick={(d: any) => setSelectedCurveMv(Number(d?.mana_value ?? 0))}
                    />
                    <Bar
                      {...chartMotion("manabase-curve-histogram", 1)}
                      yAxisId="left"
                      dataKey="spells"
                      stackId="curve"
                      fill={currentChartTheme.series.slateSoft}
                      name="Spells"
                      radius={[8, 8, 0, 0]}
                      onClick={(d: any) => setSelectedCurveMv(Number(d?.mana_value ?? 0))}
                    />
                    <Line
                      {...chartMotion("manabase-curve-histogram", 2)}
                      yAxisId="right"
                      type="monotone"
                      dataKey="p_on_curve_est"
                      stroke={currentChartTheme.series.primary}
                      strokeWidth={2.2}
                      dot={{ r: 2, fill: currentChartTheme.series.primary, strokeWidth: 0 }}
                      name="Estimated P(on curve)"
                    />
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
                              <button className="btn inline-card-button" onClick={() => setSelectedCard(x.card)}>
                                {cardThumb(x.card) ? <img src={cardThumb(x.card)} alt={x.card} width={24} height={34} loading="lazy" className="inline-card-thumb" /> : null}
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
                                {cardThumb(s.name) ? <img src={cardThumb(s.name)} alt={s.name} width={20} height={28} loading="lazy" className="table-card-thumb" /> : null}
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
                        <button className="btn inline-card-button" onClick={() => setSelectedCard(x.card)}>
                          {cardThumb(x.card) ? <img src={cardThumb(x.card)} alt={x.card} width={24} height={34} loading="lazy" className="inline-card-thumb" /> : null}
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
                {renderMiniCard({
                  label: "P(4 mana by T3)",
                  value: pct(simRes?.summary?.milestones?.p_mana4_t3),
                })}
                {renderMiniCard({
                  label: "P(5 mana by T4)",
                  value: pct(simRes?.summary?.milestones?.p_mana5_t4),
                })}
                {renderMiniCard({
                  label: "Median Commander Turn",
                  value: simRes?.summary?.milestones?.median_commander_cast_turn ?? "n/a",
                })}
                {renderMiniCard({
                  label: "Win By Turn Limit",
                  value: pct(winMetrics?.p_win_by_turn_limit),
                  tone: "accent",
                })}
                {renderMiniCard({
                  label: "Sim Backend",
                  value: simRes?.summary?.backend_used || "n/a",
                })}
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
                    <CartesianGrid {...chartGridProps} />
                    <XAxis {...chartAxisProps} dataKey="turn" label={chartLabel("Turn", "insideBottom")} />
                    <YAxis {...chartAxisProps} label={chartLabel("Plan progress score", "insideLeft", { angle: -90 })} />
                    <Tooltip {...chartTooltipProps} />
                    <Line {...chartMotion("goldfish-plan-progress", 0)} type="monotone" dataKey="median" stroke={currentChartTheme.series.primary} strokeWidth={2.5} dot={false} />
                    <Line {...chartMotion("goldfish-plan-progress", 1)} type="monotone" dataKey="p90" stroke={currentChartTheme.series.secondary} strokeWidth={2.1} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("plan_progress")}

              <h2>Failure Mode Rates</h2>
              {renderMetricHelp("failure_rates")}
              <div ref={chartViewportRef("goldfish-failure-rates")} style={{ width: "100%", height: 220 }}>
                <ResponsiveContainer>
                  <BarChart data={failureData}>
                    <CartesianGrid {...chartGridProps} />
                    <XAxis {...chartAxisProps} dataKey="name" label={chartLabel("Failure type", "insideBottom")} />
                    <YAxis {...chartAxisProps} label={chartLabel("Percent of runs", "insideLeft", { angle: -90 })} />
                    <Tooltip {...chartTooltipProps} formatter={(v: any) => `${Number(v).toFixed(1)}%`} />
                    <Bar {...chartMotion("goldfish-failure-rates", 0)} dataKey="value" fill={currentChartTheme.series.danger} radius={[8, 8, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              {renderDeckBlurb("failure_rates")}

              <h2>Wincon Outcomes</h2>
              {renderMetricHelp("wincon_outcomes")}
              <div ref={chartViewportRef("goldfish-wincon-outcomes")} style={{ width: "100%", height: 220 }}>
                <ResponsiveContainer>
                  <BarChart data={winconData}>
                    <CartesianGrid {...chartGridProps} />
                    <XAxis {...chartAxisProps} dataKey="name" label={chartLabel("Win route", "insideBottom")} />
                    <YAxis {...chartAxisProps} label={chartLabel("Percent of runs", "insideLeft", { angle: -90 })} />
                    <Tooltip {...chartTooltipProps} formatter={(v: any) => `${Number(v).toFixed(1)}%`} />
                    <Bar {...chartMotion("goldfish-wincon-outcomes", 0)} dataKey="value" fill={currentChartTheme.series.positive} radius={[8, 8, 0, 0]} />
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

          {tab === "Fastest Wins" && (
            <div className="guide-rendered">
              <h2>Fastest Wins</h2>
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
                    <CartesianGrid {...chartGridProps} />
                    <XAxis {...chartAxisProps} dataKey="card" hide />
                    <YAxis {...chartAxisProps} label={chartLabel("Importance score", "insideLeft", { angle: -90 })} />
                    <Tooltip {...chartTooltipProps} formatter={(v: any) => Number(v).toFixed(3)} />
                    <Bar {...chartMotion("importance-top-chart", 0)} dataKey="score" fill={currentChartTheme.series.primary} radius={[8, 8, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <p className="deck-blurb">
                Importance score combines: <strong>seen impact</strong> (how often outcomes improve when a card is seen), <strong>cast impact</strong> (improvement when cast), <strong>centrality</strong> (how central a card is to successful lines), and <strong>redundancy</strong> (how replaceable it is). Higher score means this card is doing more heavy lifting in your current deck.
              </p>
              <div className="card-detail-list">
                {(analysis?.importance || []).slice(0, 20).map((c: any, i: number) =>
                  renderCardDetailRow({
                    rowKey: `importance-${c.card}-${i}`,
                    title: c.card,
                    imageCard: c.card,
                    stats: [
                      { label: "Importance score", value: (c.score ?? 0).toFixed(3) },
                    ],
                    sections: [
                      {
                        label: "Why it matters",
                        content: <p>{c.explanation || "Contributes to draw, mana, and overall plan progression."}</p>,
                      },
                    ],
                  }),
                )}
              </div>

              <h2>Deadweight (Lowest Impact)</h2>
              <div className="metric-help">
                <div><strong>What this shows:</strong> Cards currently underperforming in goldfish context.</div>
                <div><strong>Use with care:</strong> Some low-impact cards are still necessary interaction or meta calls.</div>
                <div><strong>What to change:</strong> Start cuts with cards labeled replaceable, then re-run analysis.</div>
              </div>
              <div className="card-detail-list">
                {(analysis?.cuts || []).slice(0, 12).map((c: any, i: number) =>
                  renderCardDetailRow({
                    rowKey: `deadweight-${c.card}-${i}`,
                    title: c.card,
                    imageCard: c.card,
                    stats: [
                      { label: "Impact score", value: typeof c.score === "number" ? c.score.toFixed(3) : "n/a" },
                    ],
                    sections: [
                      {
                        label: "Why this underperformed",
                        content: <p>{c.reason || "Low impact in current simulations."}</p>,
                      },
                    ],
                  }),
                )}
              </div>
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
              <div className="card-detail-list">
                {(analysis?.cuts || []).slice(0, 10).map((c: any, i: number) =>
                  renderCardDetailRow({
                    rowKey: `cut-${c.card}-${i}`,
                    title: c.card,
                    imageCard: c.card,
                    sections: [
                      {
                        label: "Why cut this",
                        content: <p>{c.reason}</p>,
                      },
                    ],
                  }),
                )}
              </div>
              <h2>Recommended Adds</h2>
              <div className="card-detail-list">
                {(analysis?.adds || []).slice(0, 10).map((a: any, i: number) =>
                  renderCardDetailRow({
                    rowKey: `add-${a.card}-${i}`,
                    title: a.card,
                    imageCard: a.card,
                    stats: [
                      { label: "Role fit", value: a.fills || "n/a" },
                      { label: "Budget", value: a.budget_note && a.budget_note !== "n/a" ? `$${a.budget_note}` : "n/a" },
                      { label: "Source", value: a.source || "heuristic" },
                    ],
                    sections: [
                      {
                        label: "Why it fits",
                        content: <p>{a.why}</p>,
                      },
                    ],
                    links: [
                      { label: "Scryfall", href: cardDisplay(a.card)?.scryfall_uri },
                      { label: "Cardmarket", href: cardDisplay(a.card)?.cardmarket_url },
                    ],
                  }),
                )}
              </div>
              <h2>Suggested Swaps</h2>
              <div className="card-detail-list">
                {(analysis?.swaps || []).slice(0, 10).map((s: any, i: number) =>
                  renderCardDetailRow({
                    rowKey: `swap-${s.cut}-${s.add}-${i}`,
                    title: `Swap ${s.cut} for ${s.add}`,
                    mediaCards: [s.cut, s.add],
                    sections: [
                      {
                        label: "Why this swap helps",
                        content: <p>{s.reason}</p>,
                      },
                    ],
                    links: [
                      { label: `${s.cut} on Scryfall`, href: cardDisplay(s.cut)?.scryfall_uri },
                      { label: `${s.add} on Scryfall`, href: cardDisplay(s.add)?.scryfall_uri },
                      { label: `${s.add} on Cardmarket`, href: cardDisplay(s.add)?.cardmarket_url },
                    ],
                  }),
                )}
              </div>

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

          {tab === "Rule 0" && (
            <div className="guide-rendered">
              <div className="row" style={{ justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                <p className="control-help" style={{ margin: 0 }}>
                  Copy this into a Rule 0 conversation for a compact but honest summary of speed, combo pressure, interaction, and table expectations.
                </p>
                <button
                  className="btn"
                  onClick={async () => {
                    const text = guides?.rule0_brief_md || "";
                    if (!text) return;
                    await navigator.clipboard.writeText(text);
                  }}
                  disabled={!guides?.rule0_brief_md}
                >
                  Copy Rule 0 Brief
                </button>
              </div>
              <ReactMarkdown>{guides?.rule0_brief_md || "Run full analysis first."}</ReactMarkdown>
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
                    className="insight-poster"
                  />
                ) : (
                  <div className="insight-poster insight-poster-placeholder" />
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
                  <div className="card-detail-list">
                    {strictlyBetter.map((opt: any, idx: number) =>
                      renderCardDetailRow({
                        rowKey: `strictly-better-${opt.card}-${idx}`,
                        title: opt.card,
                        imageCard: opt.card,
                        compact: true,
                        stats: [
                          { label: "Price", value: opt.price_usd != null ? `$${Number(opt.price_usd).toFixed(2)}` : "n/a" },
                        ],
                        sections: [
                          {
                            label: "Why it is closer or better here",
                            content: (
                              <ul className="list-compact">
                                {(opt.reasons || []).map((r: string, i: number) => <li key={i}>{r}</li>)}
                              </ul>
                            ),
                          },
                        ],
                        links: [
                          { label: "Scryfall", href: opt.scryfall_uri },
                          { label: "Cardmarket", href: opt.cardmarket_url },
                        ],
                      }),
                    )}
                  </div>
                )}
              </div>
            ) : (
              <div className="muted">Click any card in analysis tables to open insight.</div>
            )}
          </aside>
        </div>
      </main>

      {accountOpen ? <button type="button" className="account-overlay" aria-label="Close account drawer" onClick={() => setAccountOpen(false)} /> : null}
      <aside id="account-drawer" className={`account-drawer ${accountOpen ? "open" : ""}`} aria-hidden={!accountOpen} role="dialog" aria-modal="true" aria-labelledby="account-drawer-title">
        <div className="account-drawer-header">
          <div className="account-drawer-heading">
            <div className="panel-kicker">Account</div>
            <h3 id="account-drawer-title">{authUser ? "Deck Library" : resetToken ? "Recover Account" : "Sign In"}</h3>
            {authUser ? (
              <p className="account-drawer-subtitle">
                {authUser.email}
              </p>
            ) : (
              <p className="account-drawer-subtitle">
                Save decks, reopen versions, and keep analysis attached to your list.
              </p>
            )}
          </div>
          <button type="button" className="account-drawer-close" aria-label="Close account drawer" onClick={() => setAccountOpen(false)}>×</button>
        </div>
        {!resetToken ? (
          <div className="account-drawer-tabs" role="tablist" aria-label="Account sections">
            {(authUser
              ? [
                  { key: "library", label: "Library" },
                  { key: "security", label: "Security" },
                ]
              : [
                  { key: "login", label: "Log in" },
                  { key: "register", label: "Create account" },
                  { key: "recover", label: "Recover" },
                ]).map((tabOption) => (
              <button
                key={tabOption.key}
                type="button"
                className={`btn tab-btn ${activeAccountTab === tabOption.key ? "active" : ""}`}
                aria-pressed={activeAccountTab === tabOption.key}
                onClick={() => setAccountTab(tabOption.key as "login" | "register" | "recover" | "library" | "security")}
              >
                {tabOption.label}
              </button>
            ))}
          </div>
        ) : null}
        <div className="account-drawer-body">
          {!authChecked ? (
            <p className="control-help">Checking session…</p>
          ) : authUser ? (
            activeAccountTab === "security" ? renderAccountSecurity() : renderAccountLibrary()
          ) : (
            renderSignedOutAccount()
          )}
          {authNotice ? <p className="import-notice" data-tone="accent">{authNotice}</p> : null}
          {authError ? <p className="import-notice" data-tone="danger">{authError}</p> : null}
        </div>
      </aside>

    </div>
  );
}
