export type ThemeMode = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

export const THEME_STORAGE_KEY = "deckcheck-theme";

export function isThemeMode(value: unknown): value is ThemeMode {
  return value === "light" || value === "dark" || value === "system";
}

export function resolveTheme(mode: ThemeMode, prefersDark: boolean): ResolvedTheme {
  if (mode === "system") {
    return prefersDark ? "dark" : "light";
  }
  return mode;
}

export const THEME_INIT_SCRIPT = `(() => {
  const key = ${JSON.stringify(THEME_STORAGE_KEY)};
  const isValid = (value) => value === "light" || value === "dark" || value === "system";
  try {
    const stored = window.localStorage.getItem(key);
    const mode = isValid(stored) ? stored : "system";
    const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    const resolved = mode === "system" ? (prefersDark ? "dark" : "light") : mode;
    document.documentElement.dataset.theme = resolved;
    document.documentElement.dataset.themeMode = mode;
    document.documentElement.style.colorScheme = resolved;
  } catch (error) {
    document.documentElement.dataset.theme = "dark";
    document.documentElement.dataset.themeMode = "system";
    document.documentElement.style.colorScheme = "dark";
  }
})();`;

export function chartTheme(theme: ResolvedTheme) {
  if (theme === "dark") {
    return {
      axis: "#b6bfcb",
      axisMuted: "#8f99a8",
      axisLine: "#39414d",
      grid: "#2d333c",
      legend: "#edf1f5",
      tooltipBg: "rgba(23, 26, 31, 0.96)",
      tooltipBorder: "#39414d",
      tooltipText: "#edf1f5",
      cursor: "rgba(138, 161, 207, 0.24)",
      series: {
        primary: "#8aa1cf",
        secondary: "#66779b",
        tertiary: "#94b0a6",
        quaternary: "#a39ab3",
        positive: "#7db08f",
        warning: "#c9a35f",
        danger: "#c47a82",
        muted: "#6e7786",
        muted2: "#93a0b5",
        muted3: "#47505f",
        slate: "#6e7786",
        slateSoft: "#aab6c9",
      },
    };
  }

  return {
    axis: "#5f6672",
    axisMuted: "#7b838f",
    axisLine: "#d8dbe1",
    grid: "#eceef2",
    legend: "#353a45",
    tooltipBg: "rgba(255, 255, 255, 0.97)",
    tooltipBorder: "#d8dbe1",
    tooltipText: "#151515",
    cursor: "rgba(77, 94, 133, 0.18)",
    series: {
      primary: "#4d5e85",
      secondary: "#7b879f",
      tertiary: "#8aa19b",
      quaternary: "#90879d",
      positive: "#4f8463",
      warning: "#a88445",
      danger: "#a06168",
      muted: "#89909d",
      muted2: "#96a2b8",
      muted3: "#d9dde3",
      slate: "#5f6672",
      slateSoft: "#a6b0c0",
    },
  };
}
