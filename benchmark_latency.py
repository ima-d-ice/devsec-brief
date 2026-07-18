"""
Latency Benchmark: Cold vs Cached Performance
Uses GROQ_API_KEY (key 1) to measure RAG pipeline latency.

Runs each query TWICE:
  1. Cold  – expansion cache is empty → Groq LLM call for query expansion
  2. Warm  – expansion cache hit       → skips the ~600ms Groq expansion call

Reports per-stage timings and totals.
"""

import json
import time
import os
import sys
import statistics
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

# Force GROQ_API_KEY_4 (key 4) to avoid rate limits
GROQ_API_KEY = os.getenv("GROQ_API_KEY_4")
if not GROQ_API_KEY:
    print("❌ GROQ_API_KEY_4 not set in .env")
    sys.exit(1)

print(f"🔑 Using GROQ_API_KEY_4 (key 4) ending in ...{GROQ_API_KEY[-6:]}")

# Initialize the groq client with key 1
from src.groq_client import set_api_key
set_api_key(GROQ_API_KEY)

# Import RAG components
from src.rag import (
    retrieve_super, build_context, generate_answer_from_context,
    _expansion_cache,
)

# ── Config ──────────────────────────────────────────────────────────────

DATASET_PATH = Path(__file__).resolve().parent / "data" / "evaluation_dataset.json"
RESULTS_DIR = Path(__file__).resolve().parent / "eval_results"
SAMPLE_SIZE = 50  # Number of questions to benchmark

# ── Helpers ─────────────────────────────────────────────────────────────

def measure_pipeline_stages(query: str, topic=None):
    """
    Run the full RAG pipeline using retrieve_super() directly so the
    benchmark reflects actual production performance (parallelization,
    batched encoding, etc.) instead of a sequential reimplementation.

    Returns dict with stage names → elapsed seconds.
    """
    timings = {}

    # 1. Retrieval (expand + semantic + keyword + RRF + rerank — all via retrieve_super)
    t0 = time.perf_counter()
    res = retrieve_super(query, topic=topic, k=6)
    timings["retrieval"] = time.perf_counter() - t0

    # 2. Build context
    t1 = time.perf_counter()
    context = build_context(res)
    timings["build_context"] = time.perf_counter() - t1

    # 3. LLM generation (Groq)
    t2 = time.perf_counter()
    if context.strip():
        answer = generate_answer_from_context(context, query)
    else:
        answer = "No context"
    timings["llm_generation"] = time.perf_counter() - t2

    # Total
    timings["total"] = sum(timings.values())

    return timings, answer


def fmt_ms(seconds):
    return f"{seconds * 1000:.1f}ms"


# ── Main ────────────────────────────────────────────────────────────────

def main():
    with open(DATASET_PATH) as f:
        dataset = json.load(f)

    # Take a sample spread across the dataset
    step = max(1, len(dataset) // SAMPLE_SIZE)
    sample = dataset[::step][:SAMPLE_SIZE]

    print(f"\n{'='*80}")
    print(f"  LATENCY BENCHMARK — {len(sample)} queries, GROQ_API_KEY_2 (key 2)")
    print(f"{'='*80}\n")

    cold_runs = []
    warm_runs = []

    stages = [
        "retrieval", "build_context", "llm_generation", "total"
    ]

    for i, item in enumerate(sample):
        question = item["question"]
        short_q = question[:80] + "..." if len(question) > 80 else question
        print(f"\n[{i+1}/{len(sample)}] {short_q}")

        # ── COLD RUN: Clear expansion cache ──
        _expansion_cache.clear()
        print("  🧊 Cold run (no cache)...")
        cold_timings, _ = measure_pipeline_stages(question)
        cold_runs.append(cold_timings)
        print(f"     Total: {fmt_ms(cold_timings['total'])}  |  "
              f"Retrieval: {fmt_ms(cold_timings['retrieval'])}  |  "
              f"Generation: {fmt_ms(cold_timings['llm_generation'])}")

        # ── WARM RUN: Cache is now populated ──
        print("  🔥 Warm run (cached)...")
        warm_timings, _ = measure_pipeline_stages(question)
        warm_runs.append(warm_timings)
        print(f"     Total: {fmt_ms(warm_timings['total'])}  |  "
              f"Retrieval: {fmt_ms(warm_timings['retrieval'])}  |  "
              f"Generation: {fmt_ms(warm_timings['llm_generation'])}")

        # Savings
        saved = cold_timings["total"] - warm_timings["total"]
        pct = (saved / cold_timings["total"]) * 100 if cold_timings["total"] > 0 else 0
        print(f"     💰 Cache saved: {fmt_ms(saved)} ({pct:.1f}%)")

    # ── Aggregate Stats ─────────────────────────────────────────────────

    print(f"\n\n{'='*80}")
    print(f"  AGGREGATE RESULTS ({len(sample)} queries)")
    print(f"{'='*80}\n")

    header = f"{'Stage':<20} {'Cold Mean':>12} {'Cold Med':>12} {'Warm Mean':>12} {'Warm Med':>12} {'Δ Mean':>12} {'Δ %':>8}"
    print(header)
    print("─" * len(header))

    results_data = {"benchmark_config": {
        "api_key": "GROQ_API_KEY_2 (key 2)",
        "api_key_suffix": GROQ_API_KEY[-6:],
        "sample_size": len(sample),
        "timestamp": datetime.now().isoformat(),
    }, "per_query": [], "aggregate": {}}

    for idx, (cold, warm) in enumerate(zip(cold_runs, warm_runs)):
        results_data["per_query"].append({
            "question": sample[idx]["question"],
            "cold": {k: round(v * 1000, 1) for k, v in cold.items()},
            "warm": {k: round(v * 1000, 1) for k, v in warm.items()},
        })

    for stage in stages:
        cold_vals = [r[stage] for r in cold_runs]
        warm_vals = [r[stage] for r in warm_runs]

        cold_mean = statistics.mean(cold_vals)
        cold_med = statistics.median(cold_vals)
        warm_mean = statistics.mean(warm_vals)
        warm_med = statistics.median(warm_vals)
        delta_mean = cold_mean - warm_mean
        delta_pct = (delta_mean / cold_mean * 100) if cold_mean > 0 else 0

        label = stage.upper() if stage == "total" else stage
        print(f"{label:<20} {fmt_ms(cold_mean):>12} {fmt_ms(cold_med):>12} "
              f"{fmt_ms(warm_mean):>12} {fmt_ms(warm_med):>12} "
              f"{fmt_ms(delta_mean):>12} {delta_pct:>7.1f}%")

        results_data["aggregate"][stage] = {
            "cold_mean_ms": round(cold_mean * 1000, 1),
            "cold_median_ms": round(cold_med * 1000, 1),
            "warm_mean_ms": round(warm_mean * 1000, 1),
            "warm_median_ms": round(warm_med * 1000, 1),
            "delta_mean_ms": round(delta_mean * 1000, 1),
            "delta_pct": round(delta_pct, 1),
        }

    # P50/P95/P99 for total latency
    cold_totals = sorted([r["total"] for r in cold_runs])
    warm_totals = sorted([r["total"] for r in warm_runs])

    def percentile(data, p):
        idx = int(len(data) * p / 100)
        idx = min(idx, len(data) - 1)
        return data[idx]

    print(f"\n{'Percentile':<20} {'Cold':>12} {'Warm':>12} {'Saved':>12}")
    print("─" * 56)
    for p in [50, 90, 95, 99]:
        c = percentile(cold_totals, p)
        w = percentile(warm_totals, p)
        print(f"P{p:<19} {fmt_ms(c):>12} {fmt_ms(w):>12} {fmt_ms(c-w):>12}")

    results_data["percentiles"] = {}
    for p in [50, 90, 95, 99]:
        results_data["percentiles"][f"p{p}"] = {
            "cold_ms": round(percentile(cold_totals, p) * 1000, 1),
            "warm_ms": round(percentile(warm_totals, p) * 1000, 1),
        }

    # Save results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_path = RESULTS_DIR / f"latency_benchmark_{timestamp}.json"
    with open(save_path, "w") as f:
        json.dump(results_data, f, indent=2)
    print(f"\n💾 Results saved to {save_path.name}")


if __name__ == "__main__":
    main()
