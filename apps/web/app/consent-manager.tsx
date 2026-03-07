"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
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

export default function ConsentManager() {
  const [ready, setReady] = useState(false);
  const [consent, setConsent] = useState<ConsentState | null>(null);
  const [draft, setDraft] = useState<ConsentDraft>(defaultConsentDraft());
  const [open, setOpen] = useState(false);

  const hasStoredConsent = useMemo(() => !!consent, [consent]);

  function persist(next: ConsentState) {
    setConsent(next);
    setDraft({
      functional: next.functional,
      analytics: next.analytics,
      marketing: next.marketing,
    });
    applyConsentToDocument(next);
    setOpen(false);
  }

  useEffect(() => {
    const stored = readStoredConsent();
    setConsent(stored);
    setDraft(
      stored
        ? {
            functional: stored.functional,
            analytics: stored.analytics,
            marketing: stored.marketing,
          }
        : defaultConsentDraft(),
    );
    applyConsentToDocument(stored);
    setReady(true);
  }, []);

  useEffect(() => {
    function handleStorage(event: StorageEvent) {
      if (event.key && event.key !== CONSENT_STORAGE_KEY) return;
      const stored = readStoredConsent();
      setConsent(stored);
      setDraft(
        stored
          ? {
              functional: stored.functional,
              analytics: stored.analytics,
              marketing: stored.marketing,
            }
          : defaultConsentDraft(),
      );
      applyConsentToDocument(stored);
    }

    window.addEventListener("storage", handleStorage);
    return () => window.removeEventListener("storage", handleStorage);
  }, []);

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

      {hasStoredConsent ? (
        <button type="button" className="consent-manage-trigger" onClick={() => setOpen(true)}>
          Privacy choices
        </button>
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

        <div className="consent-drawer-body stack">
          <div className="mini-card" data-surface="2">
            <div className="mini-label">Strictly necessary</div>
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
            <button type="button" className="btn" onClick={() => persist(rejectOptionalConsent())}>
              Reject optional
            </button>
            <button type="button" className="btn btn-primary" onClick={() => persist(buildConsentFromDraft(draft))}>
              Save choices
            </button>
            <button type="button" className="btn" onClick={() => persist(acceptAllConsent())}>
              Accept all
            </button>
          </div>

          <div className="legal-actions">
            <Link href="/privacy">Privacy policy</Link>
          </div>
        </div>
      </aside>
    </>
  );
}
