import type { Metadata, Viewport } from "next";
import { Fraunces, Inter } from "next/font/google";
import { ConfigProvider } from "@/components/config-context";
import { OfflineBanner } from "@/components/live";
import { DemoBanner } from "@/components/demo-banner";
import { publicConfig } from "@/lib/config";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const fraunces = Fraunces({ subsets: ["latin"], variable: "--font-fraunces", axes: ["opsz"] });

export const metadata: Metadata = {
  title: { default: "People — Someone knows. Meet them.", template: "%s · People" },
  description: "Tell us what you need. Find someone who can help.",
  // Private conversations are never indexed.
  robots: { index: false, follow: false },
};

export const viewport: Viewport = { themeColor: "#faf7f2", width: "device-width", initialScale: 1 };

export const dynamic = "force-dynamic";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const cfg = publicConfig();
  return (
    <html lang="en" className={`${inter.variable} ${fraunces.variable}`}>
      <body className="min-h-dvh">
        <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[60] focus:rounded-lg focus:bg-card focus:px-3 focus:py-2">
          Skip to content
        </a>
        <ConfigProvider value={cfg}>
          <OfflineBanner />
          {cfg.mode === "demo" && <DemoBanner />}
          {children}
        </ConfigProvider>
      </body>
    </html>
  );
}
