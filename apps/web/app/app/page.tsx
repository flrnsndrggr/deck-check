import type { Metadata } from "next";
import { Suspense } from "react";
import WorkspaceClient from "../workspace-client";

export const metadata: Metadata = {
  title: "App | Deck.Check",
  description: "Analyze a Commander deck URL or pasted decklist in Deck.Check.",
};

export default function AppPage() {
  return (
    <Suspense fallback={null}>
      <WorkspaceClient />
    </Suspense>
  );
}
