"use client";

import { useEffect } from "react";
import {
  readRuntimeConsent,
  subscribeToConsentChanges,
  toTrackingConsentEnvelope,
  type ConsentState,
  type TrackingConsentEnvelope,
} from "./consent";

declare global {
  interface Window {
    dataLayer?: unknown[];
    gtag?: (...args: unknown[]) => void;
    __deckCheckConsent?: ConsentState | null;
    __deckCheckTrackingConsent?: TrackingConsentEnvelope;
  }
}

function ensureTrackingGlobals() {
  if (typeof window === "undefined") return;
  if (!Array.isArray(window.dataLayer)) {
    window.dataLayer = [];
  }
  if (typeof window.gtag !== "function") {
    window.gtag = (...args: unknown[]) => {
      window.dataLayer?.push(args);
    };
  }
}

function publishTrackingConsent(consent: ConsentState | null) {
  if (typeof window === "undefined" || typeof document === "undefined") return;
  ensureTrackingGlobals();
  const envelope = toTrackingConsentEnvelope(consent);
  window.__deckCheckTrackingConsent = envelope;
  document.documentElement.dataset.analyticsReady = envelope.analytics;
  document.documentElement.dataset.marketingReady = envelope.marketing;
  window.gtag?.("consent", consent ? "update" : "default", envelope.googleConsentMode);
  window.dispatchEvent(new CustomEvent("deckcheck:tracking-consent", { detail: envelope }));
}

export default function TrackingConsentBridge() {
  useEffect(() => {
    publishTrackingConsent(readRuntimeConsent());
    return subscribeToConsentChanges((next) => publishTrackingConsent(next));
  }, []);

  return null;
}
