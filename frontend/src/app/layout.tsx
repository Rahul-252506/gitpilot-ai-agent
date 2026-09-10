import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "GitPilot — AI GitHub Issue Resolution Agent",
  description:
    "Investigate GitHub issues with an AI agent: gathers repository context through tools and produces a structured resolution report.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
