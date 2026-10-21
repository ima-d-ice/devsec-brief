"use client";

import { useState } from "react";
import type { Source } from "@/lib/types";

function hostOf(url?: string | null): string {
  if (!url) return "";
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

function fmtDate(iso?: string | null): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    return d.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return "";
  }
}

export default function Sources({ sources }: { sources: Source[] }) {
  const [open, setOpen] = useState(false);
  if (!sources || sources.length === 0) return null;
  return (
    <div
      className="mt-3 overflow-hidden rounded-xl border"
      style={{ borderColor: "var(--border)", background: "var(--surface-2)" }}
    >
      <button
        onClick={() => setOpen(!open)}
        data-testid="sources-toggle"
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-[12.5px] font-medium hover:bg-black/5 dark:hover:bg-white/5"
        style={{ color: "var(--muted)" }}
      >
        <span
          className="flex h-[18px] min-w-[18px] items-center justify-center rounded px-1 text-[10.5px] font-bold"
          style={{ background: "var(--surface-3)", color: "var(--muted)" }}
        >
          {sources.length}
        </span>
        {sources.length === 1 ? "source" : "sources"}
        <span style={{ color: "var(--faint)" }}>
          {open ? "▾" : "▸"}
        </span>
      </button>
      {open && (
        <div className="space-y-1.5 px-2.5 pb-2.5">
          {sources.map((s, i) => {
            const host = hostOf(s.url);
            const date = fmtDate(s.published_at);
            const meta = [s.source, s.category, date, host].filter(Boolean);
            const body = (
              <span className="flex items-start gap-2.5">
                <span
                  className="mt-[3px] font-mono text-[11px]"
                  style={{ color: "var(--faint)" }}
                >
                  {String(i + 1).padStart(2, "0")}
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-[13px] font-medium leading-snug">
                    {s.title || host || s.source || "Untitled source"}
                  </span>
                  {meta.length > 0 && (
                    <span
                      className="mt-0.5 block truncate text-[11.5px]"
                      style={{ color: "var(--faint)" }}
                    >
                      {meta.join("  ·  ")}
                    </span>
                  )}
                </span>
                {s.url && (
                  <span
                    className="ml-auto mt-1 shrink-0 text-xs"
                    style={{ color: "var(--faint)" }}
                  >
                    ↗
                  </span>
                )}
              </span>
            );
            const cls =
              "lift block rounded-xl border px-2.5 py-2 text-left";
            const style = {
              borderColor: "var(--border)",
              background: "var(--surface)",
            } as const;
            return s.url ? (
              <a
                key={i}
                href={s.url}
                target="_blank"
                rel="noreferrer"
                className={cls}
                style={style}
              >
                {body}
              </a>
            ) : (
              <div key={i} className={cls} style={style}>
                {body}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
