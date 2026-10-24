import type { Metadata } from "next";
import { Inter, Inter_Tight, Instrument_Serif, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { Shell } from "@/components/ui/Shell";

const sans = Inter({ subsets: ["latin"], variable: "--font-sans" });
const display = Inter_Tight({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-display" });
const serif = Instrument_Serif({ subsets: ["latin"], weight: "400", style: ["normal", "italic"], variable: "--font-serif" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono" });

export const metadata: Metadata = {
  title: "RTB Platform",
  description: "Live second-price auctions across five DSPs, with a 100 ms deadline.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${display.variable} ${serif.variable} ${mono.variable}`}>
      <body className="font-sans min-h-screen">
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
