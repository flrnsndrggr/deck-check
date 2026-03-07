"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  acceptAllConsent,
  applyConsentToDocument,
  buildConsentFromDraft,
  CONSENT_STORAGE_KEY,
  defaultConsentDraft,
  readStoredConsent,
  rejectOptionalConsent,
  type ConsentDraft,
  type ConsentState,
} from "./consent";

const CONSENT_OPTIONS: Array<{
  key: keyof ConsentDraft;
  label: string;
  description: string;
}> = [
  {
    key: "functional",
    label: "Functional",
    description: "For optional convenience features that are not required to run the core product.",
  },
  {
    key: "analytics",
    label: "Analytics",
    description: "For measurement, product telemetry, and usage analysis. Disabled until explicitly enabled here and in the app.",
  },
  {
    key: "marketing",
    label: "Marketing",
    description: "For advertising, pixels, or remarketing integrations. Disabled by default and reserved for future use.",
  },
];

function consentDraftFromState(value: ConsentState | null): ConsentDraft {
  return value
    ? {
        functional: value.functional,
        analytics: value.analytics,
        marketing: value.marketing,
      }
    : defaultConsentDraft();
}

function useConsentPreferencesState() {
  const [ready, setReady] = useState(false);
  const [consent, setConsent] = useState<ConsentState | null>(null);
  const [draft, setDraft] = useState<ConsentDraft>(defaultConsentDraft());

  function persist(next: ConsentState) {
    setConsent(next);
    setDraft(consentDraftFromState(next));
    applyConsentToDocument(next);
  }

  useEffect(() => {
    const stored = readStoredConsent();
    setConsent(stored);
    setDraft(consentDraftFromState(stored));
    applyConsentToDocument(stored);
    setReady(true);
  }, []);

  useEffect(() => {
    function handleStorage(event: StorageEvent) {
      if (event.key && event.key !== CONSENT_STORAGE_KEY) return;
      const stored = readStoredConsent();
      setConsent(stored);
      setDraft(consentDraftFromState(stored));
      applyConsentToDocument(stored);
    }

    window.addEventListener("storage", handleStorage);
    return () => window.removeEventListener("storage", handleStorage);
  }, []);

  return { ready, consent, draft, setDraft, persist };
}

export function ConsentPreferencesPanel({
  onSaved,
  showIntro = true,
}: {
  onSaved?: () => void;
  showIntro?: boolean;
}) {
  const { ready, draft, setDraft, persist } = useConsentPreferencesState();

  function save(next: ConsentState) {
    persist(next);
    onSaved?.();
  }

  if (!ready) {
    return <p className="control-help">Loading privacy choices…</p>;
  }

  return (
    <div className="stack">
      {showIntro ? (
        <div className="account-section-intro">
          <strong>Privacy choices</strong>
          <span>Strictly necessary storage always stays on. Optional categories only turn on if you enable them here.</span>
        </div>
      ) : null}

      <div
        className="mini-card"
        data-surface="2"
        title="The cookies and stored settings the site needs to work at all, such as login, security, and core app state."
        aria-label="Strictly necessary. The cookies and stored settings the site needs to work at all, such as login, security, and core app state."
      >
        <div className="mini-label-row">
          <div className="mini-label">Strictly necessary</div>
          <span className="mini-tooltip-trigger" aria-hidden="true" title="The cookies and stored settings the site needs to work at all, such as login, security, and core app state.">?</span>
        </div>
        <div className="mini-value">Always active</div>
        <p className="control-help">Required for authentication, CSRF protection, security, and core app state.</p>
      </div>

      {CONSENT_OPTIONS.map((option) => (
        <label key={option.key} className="consent-option">
          <div className="consent-option-main">
            <strong>{option.label}</strong>
            <span>{option.description}</span>
          </div>
          <input
            type="checkbox"
            checked={draft[option.key]}
            onChange={(event) => setDraft((current) => ({ ...current, [option.key]: event.target.checked }))}
          />
        </label>
      ))}

      <p className="control-help">
        Optional tracking integrations are currently off by default. These controls are already in place so future analytics, ads, or pixels
        can be gated correctly.
      </p>

      <div className="account-primary-actions">
        <button type="button" className="btn" onClick={() => save(rejectOptionalConsent())}>
          Reject optional
        </button>
        <button type="button" className="btn btn-primary" onClick={() => save(buildConsentFromDraft(draft))}>
          Save choices
        </button>
        <button type="button" className="btn" onClick={() => save(acceptAllConsent())}>
          Accept all
        </button>
      </div>

      <div className="legal-actions">
        <Link href="/privacy">Privacy policy</Link>
      </div>
    </div>
  );
}

export default function ConsentManager() {
  const { ready, consent, persist } = useConsentPreferencesState();
  const [open, setOpen] = useState(false);

  const hasStoredConsent = Boolean(consent);

  if (!ready) return null;

  return (
    <>
      {!hasStoredConsent ? (
        <div className="consent-banner" role="dialog" aria-modal="false" aria-labelledby="consent-title">
          <div className="consent-banner-copy">
            <div className="panel-kicker">Privacy choices</div>
            <h3 id="consent-title">Control optional tracking before it starts.</h3>
            <p>
              Deck.Check uses strictly necessary storage for core app operation. Optional analytics and advertising categories stay off
              unless you allow them.
            </p>
          </div>
          <div className="consent-banner-actions">
            <button type="button" className="btn" onClick={() => persist(rejectOptionalConsent())}>
              Reject optional
            </button>
            <button type="button" className="btn" onClick={() => setOpen(true)}>
              Manage choices
            </button>
            <button type="button" className="btn btn-primary" onClick={() => persist(acceptAllConsent())}>
              Accept all
            </button>
          </div>
        </div>
      ) : null}

      {open ? <button type="button" className="consent-overlay" aria-label="Close privacy choices" onClick={() => setOpen(false)} /> : null}

      <aside className={`consent-drawer ${open ? "open" : ""}`} aria-hidden={!open} role="dialog" aria-modal="true" aria-labelledby="consent-drawer-title">
        <div className="consent-drawer-header">
          <div>
            <div className="panel-kicker">Consent</div>
            <h3 id="consent-drawer-title">Privacy choices</h3>
            <p className="control-help">Rejecting optional categories is as easy as accepting them.</p>
          </div>
          <button type="button" className="account-drawer-close" aria-label="Close privacy choices" onClick={() => setOpen(false)}>
            ×
          </button>
        </div>

        <div className="consent-drawer-body">
          <ConsentPreferencesPanel showIntro={false} onSaved={() => setOpen(false)} />
        </div>
      </aside>
    </>
  );
}
