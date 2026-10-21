"use client";

import { BrandMark } from "./Brand";

const SUGGESTIONS = [
  {
    title: "Linux zero-days",
    query: "What are the latest zero-day vulnerabilities in Linux?",
  },
  {
    title: "Quantum vs RSA",
    query: "How is quantum computing impacting RSA encryption?",
  },
  {
    title: "Supply-chain attacks",
    query: "What are the most recent supply-chain attacks affecting developers?",
  },
  {
    title: "Frontend CVEs",
    query: "Are there any new CVEs or security advisories for React and Next.js?",
  },
];

export default function EmptyState({ onPick }: { onPick: (q: string) => void }) {
  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col items-center px-5 pb-10 pt-14 text-center sm:pt-20">
      <BrandMark size={40} />
      <h1 className="font-display mt-5 text-[1.9rem] leading-tight sm:text-[2.25rem]">
        What can I help with?
      </h1>
      <p
        className="mt-2.5 max-w-md text-[14.5px] leading-relaxed"
        style={{ color: "var(--muted)" }}
      >
        Ask about developer and security news. Answers are grounded in the
        index and cite their sources.
      </p>

      <div className="mt-8 grid w-full grid-cols-1 gap-2.5 sm:grid-cols-2">
        {SUGGESTIONS.map((s) => (
          <button
            key={s.title}
            onClick={() => onPick(s.query)}
            className="lift group rounded-2xl border p-4 text-left"
            style={{
              background: "var(--surface)",
              borderColor: "var(--border)",
            }}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-[13.5px] font-semibold">{s.title}</span>
              <span
                className="text-sm transition-transform group-hover:translate-x-0.5"
                style={{ color: "var(--faint)" }}
              >
                →
              </span>
            </div>
            <div
              className="mt-1 line-clamp-2 text-[12.5px] leading-snug"
              style={{ color: "var(--muted)" }}
            >
              {s.query}
            </div>
          </button>
        ))}
      </div>

      <p
        className="mt-7 flex items-center gap-2 text-[11.5px]"
        style={{ color: "var(--faint)" }}
      >
        <span>
          <kbd className="kbd">Enter</kbd> send
        </span>
        <span>·</span>
        <span>
          <kbd className="kbd">Shift + Enter</kbd> new line
        </span>
      </p>
    </div>
  );
}
