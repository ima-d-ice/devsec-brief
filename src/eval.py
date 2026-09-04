import argparse
import json
import re
import time
from pathlib import Path

from src.rag import retrieve_super, build_context, generate_answer_from_context
from src.groq_pool import safe_groq_call, PRIMARY_MODEL

CORPUS_PATH = Path(__file__).resolve().parents[1] / "data" / "eval_corpus.json"
RESULTS_PATH = Path(__file__).resolve().parents[1] / "data" / "eval_results.json"
REPORT_PATH = Path(__file__).resolve().parents[1] / "eval_report.md"

JUDGE_PROMPT = """You are an objective AI evaluator assessing the performance of a Retrieval-Augmented Generation (RAG) system on software and cybersecurity queries.

Evaluate the following interaction based on four strict metrics. Score each between 0.0 (failing) and 1.0 (perfect):

1. context_precision: Does the retrieved context contain the factual details needed to answer the question? (1.0 = highly relevant details present; 0.0 = completely irrelevant noise)
2. faithfulness: Is the generated answer strictly grounded in the retrieved context? (1.0 = zero hallucinations, all claims supported; 0.0 = contains fabricated or unsupported claims)
3. answer_relevancy: Does the answer directly and concisely address the user's specific question? (1.0 = perfectly answers question; 0.0 = completely off-topic or evasive)
4. semantic_similarity: Does the generated answer capture the core technical facts stated in the ground truth answer? (1.0 = identical technical facts; 0.0 = contradicts or misses ground truth)

Input Data:
<<<QUESTION>>>
{question}
<<<END_QUESTION>>>

<<<RETRIEVED_CONTEXT>>>
{context}
<<<END_RETRIEVED_CONTEXT>>>

<<<GENERATED_ANSWER>>>
{answer}
<<<END_GENERATED_ANSWER>>>

<<<GROUND_TRUTH>>>
{ground_truth}
<<<END_GROUND_TRUTH>>>

Return your response strictly as valid JSON with this schema:
{{
  "context_precision": 0.0,
  "faithfulness": 0.0,
  "answer_relevancy": 0.0,
  "semantic_similarity": 0.0,
  "reasoning": "Brief explanation of scoring"
}}
"""

def evaluate_single(item: dict, judge_context_chars: int = 4500, retrieval_only: bool = False) -> dict:
    """Evaluates one question end-to-end through RAG retrieval, generation, and LLM judge."""
    q = item["question"]
    gt = item["ground_truth"]

    # 1. Retrieval
    t0 = time.perf_counter()
    retrieval_res = retrieve_super(q, k=4)
    retrieval_ms = round((time.perf_counter() - t0) * 1000, 2)
    context = build_context(retrieval_res)

    # Retrieval-only mode: 0 LLM tokens (keyword recall gate)
    keywords = [k.lower() for k in item.get("keywords", [])]
    ctx_lower = context.lower()
    keyword_hits = sum(1 for k in keywords if k and k in ctx_lower)
    keyword_recall = round(keyword_hits / max(len(keywords), 1), 3)
    if retrieval_only:
        return {
            "id": item["id"],
            "category": item.get("category", "general"),
            "question": q,
            "retrieval_ms": retrieval_ms,
            "generation_ms": 0,
            "model_used": "none",
            "keyword_recall": keyword_recall,
            "scores": {
                "context_precision": 0.0,
                "faithfulness": 0.0,
                "answer_relevancy": 0.0,
                "semantic_similarity": 0.0,
            },
            "reasoning": f"retrieval-only, keyword_recall={keyword_recall}",
        }

    # 2. Generation (serve shard)
    t1 = time.perf_counter()
    answer, model_used = generate_answer_from_context(context, q, role="serve")
    generation_ms = round((time.perf_counter() - t1) * 1000, 2)

    # 3. LLM-as-a-Judge Scoring (judge shard, truncated context to fit TPM)
    judge_context = context[:judge_context_chars]
    judge_input = JUDGE_PROMPT.format(
        question=q,
        context=judge_context or "No context retrieved.",
        answer=answer or "No answer generated.",
        ground_truth=gt
    )

    try:
        completion = safe_groq_call(
            messages=[
                {"role": "system", "content": "You are a strict JSON evaluator. Return only raw JSON."},
                {"role": "user", "content": judge_input}
            ],
            temperature=0.1,
            max_tokens=400,
            role="judge",
        )
        content = completion.choices[0].message.content or "{}"
        match = re.search(r"\{.*\}", content, re.DOTALL)
        scores = json.loads(match.group(0)) if match else {}
    except Exception as e:
        print(f"⚠️ Judge evaluation failed for {item['id']}: {e}")
        scores = {
            "context_precision": 0.5,
            "faithfulness": 0.5,
            "answer_relevancy": 0.5,
            "semantic_similarity": 0.5,
            "reasoning": f"Judge error: {e}"
        }

    return {
        "id": item["id"],
        "category": item.get("category", "general"),
        "question": q,
        "retrieval_ms": retrieval_ms,
        "generation_ms": generation_ms,
        "model_used": model_used,
        "keyword_recall": round(
            sum(1 for k in [kk.lower() for kk in item.get("keywords", [])] if k and k in (context or "").lower())
            / max(len(item.get("keywords", [])), 1), 3),
        "scores": {
            "context_precision": float(scores.get("context_precision", 0.0)),
            "faithfulness": float(scores.get("faithfulness", 0.0)),
            "answer_relevancy": float(scores.get("answer_relevancy", 0.0)),
            "semantic_similarity": float(scores.get("semantic_similarity", 0.0)),
        },
        "reasoning": scores.get("reasoning", "")
    }

def run_evaluation(sample_size: int = None, sleep_s: float = 2.5, resume: bool = False,
                   retrieval_only: bool = False, out_path: str | None = None,
                   judge_context_chars: int = 4500):
    with open(CORPUS_PATH, "r") as f:
        corpus = json.load(f)

    if sample_size and sample_size < len(corpus):
        corpus = corpus[:sample_size]

    results_path = Path(out_path) if out_path else RESULTS_PATH
    done_ids: set[str] = set()
    prior_results: list[dict] = []
    if resume and results_path.exists():
        try:
            prior = json.loads(results_path.read_text())
            prior_results = prior.get("results", [])
            done_ids = {r["id"] for r in prior_results}
            print(f"↩️ Resuming: {len(done_ids)} already done, skipping.")
        except Exception as e:
            print(f"⚠️ Could not resume from {results_path}: {e}")

    todo = [it for it in corpus if it["id"] not in done_ids]
    print(f"🚀 Starting RAG Evaluation on {len(todo)}/{len(corpus)} questions using {PRIMARY_MODEL} (sleep={sleep_s}s)...")
    start_time = time.perf_counter()
    results = list(prior_results)

    for idx, item in enumerate(todo, 1):
        print(f"[{idx}/{len(todo)}] Evaluating: {item['question'][:60]}...", flush=True)
        try:
            res = evaluate_single(item, judge_context_chars=judge_context_chars, retrieval_only=retrieval_only)
        except Exception as e:
            print(f"⚠️ Item {item['id']} failed: {e}. Backing off 15s...")
            time.sleep(15.0)
            try:
                res = evaluate_single(item, judge_context_chars=judge_context_chars, retrieval_only=retrieval_only)
            except Exception as e2:
                print(f"❌ Item {item['id']} failed twice: {e2}")
                continue
        results.append(res)
        # Throttle to stay under 8K TPM per key (each item ~4.3K tokens)
        if idx < len(todo):
            time.sleep(sleep_s)

    total_time = round(time.perf_counter() - start_time, 2)

    # Compute Aggregate Metrics
    avg_precision = round(sum(r["scores"]["context_precision"] for r in results) / len(results), 3)
    avg_faithfulness = round(sum(r["scores"]["faithfulness"] for r in results) / len(results), 3)
    avg_relevancy = round(sum(r["scores"]["answer_relevancy"] for r in results) / len(results), 3)
    avg_similarity = round(sum(r["scores"]["semantic_similarity"] for r in results) / len(results), 3)
    avg_retrieval_ms = round(sum(r["retrieval_ms"] for r in results) / len(results), 1)
    avg_generation_ms = round(sum(r["generation_ms"] for r in results) / len(results), 1)

    summary = {
        "total_questions": len(results),
        "total_duration_s": total_time,
        "averages": {
            "context_precision": avg_precision,
            "faithfulness": avg_faithfulness,
            "answer_relevancy": avg_relevancy,
            "semantic_similarity": avg_similarity,
            "retrieval_latency_ms": avg_retrieval_ms,
            "generation_latency_ms": avg_generation_ms,
        },
        "results": results
    }

    # Save JSON results
    with open(results_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"✅ Saved raw evaluation data to {results_path}")

    # Generate Markdown Report
    report = f"""# DevSec-Brief RAG Evaluation Report

**Evaluation Date**: {time.strftime('%Y-%m-%d %H:%M:%S')}  
**Evaluated Questions**: {len(results)}  
**Judge / Generation Model**: `{PRIMARY_MODEL}`  
**Total Benchmark Duration**: {total_time}s  

---

## 1. Executive Summary (RAG Triad Metrics)

| Metric | Score (0.0 – 1.0) | Benchmark Target | Status |
| :--- | :---: | :---: | :---: |
| **Context Precision** | **{avg_precision:.3f}** | ≥ 0.70 | {'✅ PASS' if avg_precision >= 0.7 else '⚠️ REVIEW'} |
| **Faithfulness (Anti-Hallucination)** | **{avg_faithfulness:.3f}** | ≥ 0.85 | {'✅ PASS' if avg_faithfulness >= 0.85 else '⚠️ REVIEW'} |
| **Answer Relevancy** | **{avg_relevancy:.3f}** | ≥ 0.80 | {'✅ PASS' if avg_relevancy >= 0.8 else '⚠️ REVIEW'} |
| **Semantic Similarity (Ground Truth)** | **{avg_similarity:.3f}** | ≥ 0.75 | {'✅ PASS' if avg_similarity >= 0.75 else '⚠️ REVIEW'} |

---

## 2. Latency Profiling

- **Average Retrieval Latency (Embedding + pgvector + RRF + Rerank)**: `{avg_retrieval_ms} ms`
- **Average Generation Latency (Groq Key Pool)**: `{avg_generation_ms} ms`
- **Average Total Request Latency**: `{round(avg_retrieval_ms + avg_generation_ms, 1)} ms`

---

## 3. Sample Item Breakdown

| ID | Category | Context Precision | Faithfulness | Answer Relevancy | Semantic Similarity |
| :--- | :--- | :---: | :---: | :---: | :---: |
"""
    for r in results[:15]:
        s = r["scores"]
        report += f"| `{r['id']}` | {r['category']} | {s['context_precision']:.2f} | {s['faithfulness']:.2f} | {s['answer_relevancy']:.2f} | {s['semantic_similarity']:.2f} |\n"

    with open(REPORT_PATH, "w") as f:
        f.write(report)
    print(f"📊 Generated report at {REPORT_PATH}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run DevSec RAG Evaluation Suite")
    parser.add_argument("--sample", type=int, default=None, help="Sample size (e.g. --sample 5)")
    parser.add_argument("--sleep", type=float, default=2.5, help="Seconds between items (TPM guard)")
    parser.add_argument("--resume", action="store_true", help="Skip IDs already in output file")
    parser.add_argument("--retrieval-only", action="store_true", help="Keyword recall only, 0 LLM tokens")
    parser.add_argument("--out", type=str, default=None, help="Output JSON path")
    parser.add_argument("--judge-context-chars", type=int, default=4500)
    args = parser.parse_args()
    run_evaluation(sample_size=args.sample, sleep_s=args.sleep, resume=args.resume,
                   retrieval_only=args.retrieval_only, out_path=args.out,
                   judge_context_chars=args.judge_context_chars)

