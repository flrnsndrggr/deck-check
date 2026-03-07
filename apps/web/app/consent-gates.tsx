"use client";

import { useEffect, useState } from "react";
import {
  consentGranted,
  defaultConsentDraft,
  readRuntimeConsent,
  subscribeToConsentChanges,
  type ConsentCategory,
  type ConsentState,
} from "./consent";

function readInitialConsent(): ConsentState | null {
  return readRuntimeConsent();
}

export function useConsentCategory(category: ConsentCategory): boolean {
  const [consent, setConsent] = useState<ConsentState | null>(() => readInitialConsent());

  useEffect(() => {
    setConsent(readRuntimeConsent());
    return subscribeToConsentChanges((next) => setConsent(next));
  }, []);

  return consentGranted(consent, category);
}

export function ConsentCategoryGate({
  category,
  children,
  fallback = null,
}: {
  category: ConsentCategory;
  children: React.ReactNode;
  fallback?: React.ReactNode;
}) {
  const allowed = useConsentCategory(category);
  return <>{allowed ? children : fallback}</>;
}

export const CONSENT_CATEGORIES = Object.keys(defaultConsentDraft()) as ConsentCategory[];
