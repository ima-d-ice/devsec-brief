"use client";

import type { ChatMetrics } from "@/lib/types";

export default function Metrics({ metrics }: { metrics?: ChatMetrics | null }) {
  if (!metrics) return null;
  const parts: string[] = [];
  if (metrics.model_used) parts.push(`${metrics.model_used}`);
  if (typeof metrics.ttft_ms === "number")
    parts.push(`TTFT ${(metrics.ttft_ms / 1000).toFixed(2)}s`);
  if (typeof metrics.tps === "number" && metrics.tps > 0)
    parts.push(`${metrics.tps} tok/s`);
  if (typeof metrics.tokens === "number" && metrics.tokens > 0)
    parts.push(`${metrics.tokens} tok`);
  const retrieval =
    metrics.retrieval_timings?.total_retrieval_ms ??
    metrics.latency_breakdown_ms?.total_retrieval_ms;
  if (typeof retrieval === "number")
    parts.push(`retrieval ${Math.round(retrieval)}ms`);
  if (typeof metrics.cache_lookup_ms === "number")
    parts.push(`cache ${Math.round(metrics.cache_lookup_ms)}ms`);

  if (parts.length === 0 && !metrics.cache_hit) return null;

  return (
    <div
      className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11.5px]"
      style={{ color: "var(--faint)" }}
    >
      {metrics.cache_hit && (
        <span
          className="rounded-full px-2 py-0.5 font-semibold"
          style={{ background: "var(--accent-soft)", color: "var(--accent)" }}
        >
          ⚡ cached
        </span>
      )}
      {parts.map((p, i) => (
        <span key={i} className="flex items-center gap-2">
          {i > 0 && <span>·</span>}
          <span className="font-mono">{p}</span>
        </span>
      ))}
    </div>
  );
}
