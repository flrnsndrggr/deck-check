export const CONSENT_STORAGE_KEY = "deckcheck.consent.v1";
export const CONSENT_COOKIE_NAME = "dc_consent";
export const CONSENT_VERSION = 1;
export const CONSENT_MAX_AGE_DAYS = 180;

export type ConsentState = {
  version: number;
  decidedAt: string;
  necessary: true;
  functional: boolean;
  analytics: boolean;
  marketing: boolean;
};

export type ConsentDraft = Pick<ConsentState, "functional" | "analytics" | "marketing">;

export function defaultConsentDraft(): ConsentDraft {
  return {
    functional: false,
    analytics: false,
    marketing: false,
  };
}

export function acceptAllConsent(): ConsentState {
  return {
    version: CONSENT_VERSION,
    decidedAt: new Date().toISOString(),
    necessary: true,
    functional: true,
    analytics: true,
    marketing: true,
  };
}

export function rejectOptionalConsent(): ConsentState {
  return {
    version: CONSENT_VERSION,
    decidedAt: new Date().toISOString(),
    necessary: true,
    ...defaultConsentDraft(),
  };
}

export function buildConsentFromDraft(draft: ConsentDraft): ConsentState {
  return {
    version: CONSENT_VERSION,
    decidedAt: new Date().toISOString(),
    necessary: true,
    functional: !!draft.functional,
    analytics: !!draft.analytics,
    marketing: !!draft.marketing,
  };
}

export function isConsentExpired(value: ConsentState | null): boolean {
  if (!value?.decidedAt) return true;
  const at = new Date(value.decidedAt);
  if (Number.isNaN(at.getTime())) return true;
  const ageMs = Date.now() - at.getTime();
  return ageMs > CONSENT_MAX_AGE_DAYS * 24 * 60 * 60 * 1000;
}

export function isValidConsent(value: unknown): value is ConsentState {
  if (!value || typeof value !== "object") return false;
  const next = value as Record<string, unknown>;
  return (
    Number(next.version) === CONSENT_VERSION &&
    typeof next.decidedAt === "string" &&
    next.necessary === true &&
    typeof next.functional === "boolean" &&
    typeof next.analytics === "boolean" &&
    typeof next.marketing === "boolean" &&
    !isConsentExpired(next as ConsentState)
  );
}

export function readStoredConsent(): ConsentState | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(CONSENT_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return isValidConsent(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function encodeConsentCookie(value: ConsentState): string {
  return encodeURIComponent(
    JSON.stringify({
      v: value.version,
      t: value.decidedAt,
      f: value.functional ? 1 : 0,
      a: value.analytics ? 1 : 0,
      m: value.marketing ? 1 : 0,
    }),
  );
}

export function applyConsentToDocument(value: ConsentState | null) {
  if (typeof window === "undefined" || typeof document === "undefined") return;
  const root = document.documentElement;
  const effective = value && isValidConsent(value) ? value : null;

  root.dataset.consentReady = effective ? "true" : "false";
  root.dataset.consentFunctional = effective?.functional ? "granted" : "denied";
  root.dataset.consentAnalytics = effective?.analytics ? "granted" : "denied";
  root.dataset.consentMarketing = effective?.marketing ? "granted" : "denied";

  (window as any).__deckCheckConsent = effective;
  window.dispatchEvent(new CustomEvent("deckcheck:consent-changed", { detail: effective }));

  if (effective) {
    try {
      window.localStorage.setItem(CONSENT_STORAGE_KEY, JSON.stringify(effective));
    } catch {}
    document.cookie = `${CONSENT_COOKIE_NAME}=${encodeConsentCookie(effective)}; Path=/; Max-Age=${CONSENT_MAX_AGE_DAYS * 24 * 60 * 60}; SameSite=Lax`;
  } else {
    try {
      window.localStorage.removeItem(CONSENT_STORAGE_KEY);
    } catch {}
    document.cookie = `${CONSENT_COOKIE_NAME}=; Path=/; Max-Age=0; SameSite=Lax`;
  }
}

export function consentGranted(value: ConsentState | null, category: keyof ConsentDraft): boolean {
  return !!(value && value[category]);
}

export const CONSENT_INIT_SCRIPT = `
(() => {
  const STORAGE_KEY = "${CONSENT_STORAGE_KEY}";
  const COOKIE_NAME = "${CONSENT_COOKIE_NAME}";
  const VERSION = ${CONSENT_VERSION};
  const MAX_AGE_MS = ${CONSENT_MAX_AGE_DAYS} * 24 * 60 * 60 * 1000;
  const root = document.documentElement;

  function isValid(value) {
    if (!value || typeof value !== "object") return false;
    if (Number(value.version) !== VERSION) return false;
    if (value.necessary !== true) return false;
    if (typeof value.functional !== "boolean" || typeof value.analytics !== "boolean" || typeof value.marketing !== "boolean") return false;
    const decidedAt = new Date(value.decidedAt || "");
    if (Number.isNaN(decidedAt.getTime())) return false;
    return Date.now() - decidedAt.getTime() <= MAX_AGE_MS;
  }

  function apply(value) {
    const next = isValid(value) ? value : null;
    root.dataset.consentReady = next ? "true" : "false";
    root.dataset.consentFunctional = next && next.functional ? "granted" : "denied";
    root.dataset.consentAnalytics = next && next.analytics ? "granted" : "denied";
    root.dataset.consentMarketing = next && next.marketing ? "granted" : "denied";
    window.__deckCheckConsent = next;
  }

  let parsed = null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw) parsed = JSON.parse(raw);
  } catch {}
  apply(parsed);

  if (!parsed) {
    document.cookie = COOKIE_NAME + "=; Path=/; Max-Age=0; SameSite=Lax";
  }
})();
`;
