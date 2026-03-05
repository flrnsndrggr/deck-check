import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Deck.Check",
  description: "Commander deck parser, simulator, and optimizer",
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000"),
  icons: {
    icon: "/icon.svg",
    shortcut: "/icon.svg",
    apple: "/icon.svg",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
