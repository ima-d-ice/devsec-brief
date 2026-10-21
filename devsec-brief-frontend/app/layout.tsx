import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "DevSec Brief — Grounded Dev & Security News",
  description:
    "RAG-powered AI briefing over developer and cybersecurity news. Hybrid search, reranked, grounded answers with citations.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" data-theme="light" suppressHydrationWarning>
      <body className="antialiased">
        {children}
      </body>
    </html>
  );
}
