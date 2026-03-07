import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Deck.Check",
  description: "Diagnose, refine, and prepare to play the Commander deck you already built.",
};

const capabilityBuckets = [
  {
    title: "Summary",
    text: "See deck health, intent, identity, and the main structural problems worth fixing first.",
  },
  {
    title: "Improve",
    text: "Tune mana, roles, and card choices with a view that stays grounded in what the list is actually doing.",
  },
  {
    title: "Play Prep",
    text: "Goldfish the deck, inspect fastest wins, generate a Rule 0 brief, and leave with a practical primer.",
  },
  {
    title: "Reference",
    text: "Check combos, rules watchouts, and detailed lenses when you need evidence instead of hunches.",
  },
] as const;

export default function LandingPage() {
  return (
    <main className="marketing-shell">
      <header className="marketing-nav">
        <Link className="wordmark" href="/" aria-label="Deck.Check">
          <span className="wordmark-glyph">D</span>
          <span className="wordmark-text">
            Deck<span className="wordmark-dot">.</span>Check
          </span>
        </Link>
        <nav className="marketing-nav-links" aria-label="Primary">
          <Link href="/sample-report">Sample report</Link>
          <Link href="/faq">FAQ</Link>
          <Link href="/app" className="btn btn-primary">
            Open app
          </Link>
        </nav>
      </header>

      <section className="marketing-hero">
        <div className="marketing-kicker">Commander deck prep</div>
        <h1>Diagnose the deck you already built. Then refine it and prepare to play.</h1>
        <p className="marketing-lead">
          Deck.Check imports an existing Commander list, tags it, goldfishes it, and turns the result into concrete
          deck advice, combo evidence, play prep, and rules watchouts.
        </p>
        <div className="marketing-actions">
          <Link href="/app?entry=url" className="btn btn-primary">
            Analyze deck URL
          </Link>
          <Link href="/app?entry=paste" className="btn">
            Paste decklist
          </Link>
        </div>
        <div className="marketing-proof">
          <span>No social feed.</span>
          <span>No deck directory.</span>
          <span>Just analysis, iteration, and play prep.</span>
        </div>
      </section>

      <section className="marketing-section">
        <div className="marketing-section-heading">
          <div className="marketing-kicker">Workspace</div>
          <h2>One app, four jobs</h2>
        </div>
        <div className="marketing-grid">
          {capabilityBuckets.map((bucket) => (
            <article key={bucket.title} className="marketing-card">
              <h3>{bucket.title}</h3>
              <p>{bucket.text}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="marketing-section marketing-sample">
        <div className="marketing-section-heading">
          <div className="marketing-kicker">Sample report</div>
          <h2>See the output before you bring your own deck.</h2>
        </div>
        <p className="marketing-lead marketing-lead-compact">
          The sample report walks through the kinds of findings, prep notes, combo evidence, and deck-shaping guidance
          the workspace produces.
        </p>
        <div className="marketing-actions">
          <Link href="/sample-report" className="btn btn-primary">
            View sample report
          </Link>
          <Link href="/app?entry=url" className="btn">
            Start with a deck URL
          </Link>
        </div>
      </section>

      <footer className="marketing-footer">
        <div className="marketing-footer-links">
          <Link href="/faq">FAQ</Link>
          <Link href="/privacy">Privacy</Link>
          <Link href="/imprint">Imprint</Link>
        </div>
      </footer>
    </main>
  );
}
