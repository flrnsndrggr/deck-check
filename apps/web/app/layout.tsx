import "./globals.css";
import type { Metadata } from "next";
import { IBM_Plex_Mono, Instrument_Sans } from "next/font/google";
import ConsentManager from "./consent-manager";
import { CONSENT_INIT_SCRIPT } from "./consent";
import { THEME_INIT_SCRIPT } from "./theme";

const fontUi = Instrument_Sans({
  subsets: ["latin"],
  variable: "--font-ui",
  display: "swap",
});

const fontMono = IBM_Plex_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  weight: ["400", "500", "600"],
  display: "swap",
});

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
    <html lang="en" data-theme="dark" data-theme-mode="system" suppressHydrationWarning>
      <body className={`${fontUi.variable} ${fontMono.variable}`}>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
        <script dangerouslySetInnerHTML={{ __html: CONSENT_INIT_SCRIPT }} />
        {children}
        <ConsentManager />
      </body>
    </html>
  );
}
