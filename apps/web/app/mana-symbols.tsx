"use client";

import React, {
  Children,
  cloneElement,
  createContext,
  isValidElement,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import ReactMarkdown from "react-markdown";

type SymbologyEntry = {
  symbol: string;
  english?: string;
  svg_uri: string;
};

type SymbologyMap = Record<string, SymbologyEntry>;

const SYMBOLOGY_URL = "https://api.scryfall.com/symbology";
const SYMBOLOGY_CACHE_KEY = "deckcheck.scryfall.symbology.v1";
const SYMBOLOGY_CACHE_TTL_MS = 1000 * 60 * 60 * 24 * 7;
const MANA_TOKEN_RE = /(\{[^}]+\})/g;

const ManaSymbolsContext = createContext<SymbologyMap>({});

function normalizeToken(token: string): string {
  return String(token || "").trim().toUpperCase();
}

function buildSymbologyMap(data: any): SymbologyMap {
  const map: SymbologyMap = {};
  for (const row of Array.isArray(data) ? data : []) {
    const symbol = normalizeToken(row?.symbol || "");
    const svg = String(row?.svg_uri || "").trim();
    if (!symbol || !svg) continue;
    map[symbol] = {
      symbol,
      english: String(row?.english || "").trim(),
      svg_uri: svg,
    };
  }
  return map;
}

function loadCachedSymbology(): SymbologyMap {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(SYMBOLOGY_CACHE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!parsed?.fetched_at || !parsed?.map) return {};
    if (Date.now() - Number(parsed.fetched_at) > SYMBOLOGY_CACHE_TTL_MS) return {};
    return parsed.map || {};
  } catch {
    return {};
  }
}

function saveCachedSymbology(map: SymbologyMap) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      SYMBOLOGY_CACHE_KEY,
      JSON.stringify({
        fetched_at: Date.now(),
        map,
      }),
    );
  } catch {
    return;
  }
}

function renderManaParts(text: string, map: SymbologyMap, keyPrefix: string): ReactNode[] {
  return String(text || "")
    .split(MANA_TOKEN_RE)
    .filter((part) => part.length > 0)
    .map((part, index) => {
      const normalized = normalizeToken(part);
      const symbol = map[normalized];
      if (symbol) {
        return (
          <img
            key={`${keyPrefix}-${index}`}
            src={symbol.svg_uri}
            alt={symbol.symbol}
            title={symbol.english || symbol.symbol}
            className="mana-symbol"
            loading="lazy"
          />
        );
      }
      return <React.Fragment key={`${keyPrefix}-${index}`}>{part}</React.Fragment>;
    });
}

function manaifyNode(node: ReactNode, map: SymbologyMap, keyPrefix: string): ReactNode {
  if (node == null || typeof node === "boolean") return node;
  if (typeof node === "string") {
    return renderManaParts(node, map, keyPrefix);
  }
  if (typeof node === "number") return String(node);
  if (Array.isArray(node)) {
    return node.map((child, index) => (
      <React.Fragment key={`${keyPrefix}-${index}`}>{manaifyNode(child, map, `${keyPrefix}-${index}`)}</React.Fragment>
    ));
  }
  if (isValidElement(node)) {
    const props = node.props as { children?: ReactNode };
    if (props.children === undefined) return node;
    const nextChildren = Children.map(props.children, (child, index) =>
      manaifyNode(child, map, `${keyPrefix}-${index}`),
    );
    return cloneElement(node, undefined, nextChildren);
  }
  return node;
}

function manaifyMarkdown(markdown: string, map: SymbologyMap): string {
  const source = String(markdown || "");
  const guarded = source.split(/(```[\s\S]*?```|`[^`]*`)/g);
  return guarded
    .map((segment) => {
      if (segment.startsWith("```") || segment.startsWith("`")) {
        return segment;
      }
      return segment.replace(MANA_TOKEN_RE, (token) => {
        const symbol = map[normalizeToken(token)];
        return symbol ? `![${token}](${symbol.svg_uri})` : token;
      });
    })
    .join("");
}

export function ManaSymbolsProvider({ children }: { children: ReactNode }) {
  const [symbolMap, setSymbolMap] = useState<SymbologyMap>({});

  useEffect(() => {
    const cached = loadCachedSymbology();
    if (Object.keys(cached).length) {
      setSymbolMap(cached);
    }

    let cancelled = false;
    void fetch(SYMBOLOGY_URL)
      .then((res) => (res.ok ? res.json() : null))
      .then((payload) => {
        if (cancelled || !payload?.data) return;
        const next = buildSymbologyMap(payload.data);
        if (!Object.keys(next).length) return;
        setSymbolMap(next);
        saveCachedSymbology(next);
      })
      .catch(() => null);

    return () => {
      cancelled = true;
    };
  }, []);

  const value = useMemo(() => symbolMap, [symbolMap]);
  return <ManaSymbolsContext.Provider value={value}>{children}</ManaSymbolsContext.Provider>;
}

export function useManaSymbols() {
  return useContext(ManaSymbolsContext);
}

export function ManaText({ text, className }: { text: string; className?: string }) {
  const map = useManaSymbols();
  return <span className={className}>{manaifyNode(text, map, "mana-text")}</span>;
}

export function ManaNode({ node }: { node: ReactNode }) {
  const map = useManaSymbols();
  return <>{manaifyNode(node, map, "mana-node")}</>;
}

export function ManaMarkdown({ markdown }: { markdown: string }) {
  const map = useManaSymbols();
  const rendered = useMemo(() => manaifyMarkdown(markdown, map), [markdown, map]);
  return (
    <ReactMarkdown
      components={{
        img: ({ src = "", alt = "" }) => (
          // ReactMarkdown image rendering for mana symbol markdown replacements
          <img src={src} alt={alt} title={alt} className="mana-symbol" loading="lazy" />
        ),
      }}
    >
      {rendered}
    </ReactMarkdown>
  );
}
