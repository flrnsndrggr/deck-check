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
      axis: "#b3b8c2",
      axisMuted: "#8b919b",
      axisLine: "#343944",
      grid: "#2a2f38",
      legend: "#edf0f4",
      tooltipBg: "rgba(23, 26, 31, 0.96)",
      tooltipBorder: "#343944",
      tooltipText: "#edf0f4",
      cursor: "rgba(91, 140, 255, 0.24)",
      series: {
        primary: "#5b8cff",
        secondary: "#9ea4af",
        tertiary: "#7b818b",
        quaternary: "#555c67",
        positive: "#9ea4af",
        warning: "#7b818b",
        danger: "#555c67",
        muted: "#6c727d",
        muted2: "#8c929d",
        muted3: "#444a55",
        slate: "#6c727d",
        slateSoft: "#a7adb7",
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
    cursor: "rgba(21, 94, 239, 0.18)",
    series: {
      primary: "#155EEF",
      secondary: "#71717a",
      tertiary: "#a1a1aa",
      quaternary: "#d4d4d8",
      positive: "#71717a",
      warning: "#a1a1aa",
      danger: "#d4d4d8",
      muted: "#89909d",
      muted2: "#a6adb8",
      muted3: "#d9dde3",
      slate: "#5f6672",
      slateSoft: "#b5bac4",
    },
  };
}
