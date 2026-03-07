import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "FAQ | Deck.Check",
  description: "Answers about importing decks, analysis flow, and what Deck.Check is for.",
};

const faqItems = [
  {
    question: "What is Deck.Check for?",
    answer:
      "Deck.Check starts after a deck already exists. It is built to diagnose a Commander list, suggest cleaner iterations, and help you prepare to pilot it at the table.",
  },
  {
    question: "How should I start?",
    answer:
      "Start with a deck URL when possible. The app will try to import the list directly. If the source blocks server-side access, paste the decklist text instead.",
  },
  {
    question: "Which deck URLs are supported?",
    answer:
      "Supported sources include Moxfield and Archidekt. URL import is best-effort, so pasted deck text remains the fallback when a source blocks access.",
  },
  {
    question: "Does Deck.Check host public deck profiles or collections?",
    answer:
      "No. The product is intentionally narrow: analysis, iteration, and play prep. It is not trying to become a community deck directory or social deck platform.",
  },
  {
    question: "Do I need to run the full analysis every time?",
    answer:
      "No. Tag-only mode is there for structural review, combo/reference surfaces, and deck shaping that do not require simulation.",
  },
] as const;

export default function FaqPage() {
  return (
    <main className="legal-shell">
      <article className="legal-card">
        <h1>FAQ</h1>
        <div className="faq-list">
          {faqItems.map((item) => (
            <section key={item.question} className="faq-item">
              <h2>{item.question}</h2>
              <p>{item.answer}</p>
            </section>
          ))}
        </div>
        <div className="legal-actions">
          <Link href="/">Back to Deck.Check</Link>
          <Link href="/app?entry=url">Analyze deck URL</Link>
        </div>
      </article>
    </main>
  );
}
