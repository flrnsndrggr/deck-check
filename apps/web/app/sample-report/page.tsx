import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Sample Report | Deck.Check",
  description: "Preview the kinds of findings and prep outputs Deck.Check produces for Commander decks.",
};

const reportSections = [
  {
    title: "Summary",
    text: "Deck health, inferred intent, bracket context, and the problems worth fixing first.",
  },
  {
    title: "Improve",
    text: "Role breakdown, mana base review, card importance, and replacement ideas that stay tied to the deck’s actual plan.",
  },
  {
    title: "Play Prep",
    text: "Goldfish outcomes, fastest wins, a Rule 0 summary, and a primer you can actually use before a game.",
  },
  {
    title: "Reference",
    text: "Combo evidence, rules watchouts, and detail views for when you need to validate a line or a claim.",
  },
] as const;

export default function SampleReportPage() {
  return (
    <main className="legal-shell">
      <article className="legal-card sample-report-card">
        <h1>Sample Report</h1>
        <p className="muted">
          This route is a guided preview of the output shape. The live workspace still does the real work on your deck.
        </p>
        <div className="marketing-grid">
          {reportSections.map((section) => (
            <section key={section.title} className="marketing-card">
              <h2>{section.title}</h2>
              <p>{section.text}</p>
            </section>
          ))}
        </div>
        <div className="legal-actions">
          <Link href="/app?entry=url">Analyze deck URL</Link>
          <Link href="/app?entry=paste">Paste decklist</Link>
        </div>
      </article>
    </main>
  );
}
