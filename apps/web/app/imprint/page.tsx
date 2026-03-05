import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Imprint | Deck.Check",
  description: "Legal notice and provider information for Deck.Check.",
};

const company = process.env.NEXT_PUBLIC_IMPRINT_COMPANY || "Deck.Check";
const legalEntity = process.env.NEXT_PUBLIC_IMPRINT_LEGAL_ENTITY || "Deck.Check Operations";
const representative = process.env.NEXT_PUBLIC_IMPRINT_REPRESENTATIVE || "To be completed before launch";
const address = process.env.NEXT_PUBLIC_IMPRINT_ADDRESS || "To be completed before launch";
const email = process.env.NEXT_PUBLIC_IMPRINT_EMAIL || "legal@example.com";
const phone = process.env.NEXT_PUBLIC_IMPRINT_PHONE || "To be completed before launch";
const registerCourt = process.env.NEXT_PUBLIC_IMPRINT_REGISTER_COURT || "To be completed before launch";
const registerNumber = process.env.NEXT_PUBLIC_IMPRINT_REGISTER_NUMBER || "To be completed before launch";
const vatId = process.env.NEXT_PUBLIC_IMPRINT_VAT_ID || "To be completed before launch";

export default function ImprintPage() {
  return (
    <main className="legal-shell">
      <section className="legal-card">
        <h1>Imprint</h1>
        <p className="muted">
          Fill all placeholder fields before publishing. Legal requirements vary by country and business model.
        </p>
        <div className="legal-grid">
          <strong>Service Name</strong>
          <span>{company}</span>
          <strong>Legal Entity</strong>
          <span>{legalEntity}</span>
          <strong>Representative</strong>
          <span>{representative}</span>
          <strong>Address</strong>
          <span>{address}</span>
          <strong>Email</strong>
          <span>{email}</span>
          <strong>Phone</strong>
          <span>{phone}</span>
          <strong>Register Court</strong>
          <span>{registerCourt}</span>
          <strong>Register Number</strong>
          <span>{registerNumber}</span>
          <strong>VAT ID</strong>
          <span>{vatId}</span>
        </div>
        <p>
          Responsible for content according to applicable electronic commerce and media law:{" "}
          <strong>{representative}</strong>.
        </p>
        <div className="legal-actions">
          <Link href="/">Back to Deck.Check</Link>
          <Link href="/privacy">Privacy Policy</Link>
        </div>
      </section>
    </main>
  );
}
