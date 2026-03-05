import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Privacy | Deck.Check",
  description: "Privacy policy for Deck.Check.",
};

const controller = process.env.NEXT_PUBLIC_IMPRINT_LEGAL_ENTITY || "Deck.Check Operations";
const contactEmail = process.env.NEXT_PUBLIC_PRIVACY_EMAIL || process.env.NEXT_PUBLIC_IMPRINT_EMAIL || "privacy@example.com";
const effectiveDate = process.env.NEXT_PUBLIC_PRIVACY_EFFECTIVE_DATE || "March 5, 2026";

export default function PrivacyPage() {
  return (
    <main className="legal-shell">
      <article className="legal-card">
        <h1>Privacy Policy</h1>
        <p className="muted">Effective date: {effectiveDate}</p>
        <p>
          This policy explains how <strong>{controller}</strong> processes data when you use Deck.Check.
        </p>

        <h2>1. Data We Process</h2>
        <ul>
          <li>Deck content you submit for parsing, simulation, and analysis.</li>
          <li>Technical logs required for reliability, abuse prevention, and diagnostics.</li>
          <li>Job and result metadata needed to run asynchronous simulations.</li>
        </ul>

        <h2>2. Why We Process It</h2>
        <ul>
          <li>Provide deck analysis, tagging, simulations, and recommendations.</li>
          <li>Operate and secure the service.</li>
          <li>Troubleshoot failures and improve quality.</li>
        </ul>

        <h2>3. Storage and Retention</h2>
        <ul>
          <li>Simulation/config metadata is stored in Postgres.</li>
          <li>Queue/cache data is stored in Redis with expiry policies.</li>
          <li>Card reference data is cached from Scryfall to improve performance.</li>
        </ul>

        <h2>4. Third-Party Data Sources</h2>
        <ul>
          <li>Scryfall (card data/images).</li>
          <li>CommanderSpellbook (combo enrichment).</li>
          <li>Optional ecosystem sources used for recommendations and legality updates.</li>
        </ul>

        <h2>5. Your Rights</h2>
        <p>
          Depending on your jurisdiction, you may have rights to access, correction, deletion, objection, or portability.
          Contact us at <strong>{contactEmail}</strong>.
        </p>

        <h2>6. Contact</h2>
        <p>Privacy contact: <strong>{contactEmail}</strong></p>

        <div className="legal-actions">
          <Link href="/">Back to Deck.Check</Link>
          <Link href="/imprint">Imprint</Link>
        </div>
      </article>
    </main>
  );
}
