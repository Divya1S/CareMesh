import type { Metadata } from "next";
import { JetBrains_Mono, Plus_Jakarta_Sans, Sora } from "next/font/google";
import "./globals.css";

const sora = Sora({
  variable: "--font-sora",
  subsets: ["latin"],
  weight: ["600", "700"],
});

const jakarta = Plus_Jakarta_Sans({
  variable: "--font-jakarta",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

const jetbrains = JetBrains_Mono({
  variable: "--font-jetbrains",
  subsets: ["latin"],
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: "CareMesh (portfolio simulation)",
  description:
    "Portfolio project simulating an AI native youth mental health platform. Not a medical service.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body
        className={`${sora.variable} ${jakarta.variable} ${jetbrains.variable} antialiased`}
      >
        <div
          role="note"
          className="bg-ink px-4 py-1.5 text-center text-[0.8125rem] text-surface"
        >
          CareMesh is a portfolio simulation, not a medical service.
        </div>
        {children}
      </body>
    </html>
  );
}
