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
      axis: "#c7bfd7",
      axisMuted: "#a99fbc",
      axisLine: "#4b425d",
      grid: "#352e45",
      legend: "#ede8f7",
      tooltipBg: "rgba(31, 26, 41, 0.96)",
      tooltipBorder: "#4b425d",
      tooltipText: "#f5f2fb",
      cursor: "rgba(177, 140, 255, 0.26)",
      series: {
        primary: "#b18cff",
        secondary: "#86aeeb",
        tertiary: "#d6af57",
        quaternary: "#8e84a7",
        positive: "#7bc196",
        warning: "#e0b04b",
        danger: "#e27d86",
        muted: "#6f6787",
        muted2: "#92a2c3",
        muted3: "#4f4761",
        slate: "#6f6787",
        slateSoft: "#a6b8da",
      },
    };
  }

  return {
    axis: "#5f5870",
    axisMuted: "#736b86",
    axisLine: "#cdbfde",
    grid: "#e6deec",
    legend: "#4d4660",
    tooltipBg: "rgba(255, 255, 255, 0.97)",
    tooltipBorder: "#ddd5e3",
    tooltipText: "#1c1a24",
    cursor: "rgba(91, 61, 138, 0.2)",
    series: {
      primary: "#5b3d8a",
      secondary: "#24314f",
      tertiary: "#b88a2c",
      quaternary: "#817497",
      positive: "#3e7a57",
      warning: "#b07b1f",
      danger: "#b34c54",
      muted: "#9185a6",
      muted2: "#647695",
      muted3: "#c4bad2",
      slate: "#5f5870",
      slateSoft: "#9babc5",
    },
  };
}
