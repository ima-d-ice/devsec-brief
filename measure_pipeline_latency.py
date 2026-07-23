import os
import time
import re
from dotenv import load_dotenv
from src.rag import answer_question, retrieve_super
from src.groq_client import set_api_key

def get_all_groq_keys():
    load_dotenv()
    keys = []
    for k, v in os.environ.items():
        if k.startswith("GROQ_API_KEY") and v:
            if v not in keys:
                keys.append(v)
    if not keys:
        raise ValueError("No GROQ_API_KEY found in environment")
    final_keys = []
    idx = 0
    while len(final_keys) < 10:
        final_keys.append(keys[idx % len(keys)])
        idx += 1
    return final_keys[:10]

TEST_QUESTIONS = [
    "What are the latest zero-day vulnerabilities in Linux?",
    "How does the new iOS update impact mobile security?",
    "Can you summarize recent ransomware attacks targeting healthcare?",
    "What is the recommended mitigation for CVE-2024-1234?",
    "Are there any new phishing campaigns using AI?",
]

def run_benchmark():
    print("=" * 60)
    print("PIPELINE LATENCY BENCHMARK: 10 Keys, 5 Questions Each")
    print("=" * 60)

    keys = get_all_groq_keys()

    # Warm up ONNX models
    print("\n[Warm-up] Initializing ONNX models and connections...")
    try:
        retrieve_super("Warm up query", k=1)
    except Exception as e:
        print(f"Warm-up note: {e}")

    embed_times = []
    db_times = []
    rerank_times = []
    retrieval_times = []
    gen_times = []
    total_times = []

    total_calls = 0

    for i, key in enumerate(keys):
        print(f"\n--- Activating Key {i+1}/10 (ending in ...{key[-6:]}) ---")
        set_api_key(key)

        for j, q in enumerate(TEST_QUESTIONS):
            print(f"  Q{j+1}: {q}")

            t0 = time.perf_counter()
            try:
                answer = answer_question(q)
                t1 = time.perf_counter()
                latency = t1 - t0

                print(f"    -> Success | Latency: {latency:.2f}s | Output length: {len(answer['answer'])} chars")

                total_calls += 1
                total_times.append(latency)
            except Exception as e:
                print(f"    -> ERROR: {e}")

            time.sleep(1)

    # Now parse our own stdout from the log — but instead let's just
    # re-run a quick isolated retrieval-only benchmark for clean numbers
    print("\n" + "=" * 60)
    print("RETRIEVAL-ONLY LATENCY (10 isolated runs, no generation)")
    print("=" * 60)

    for q in TEST_QUESTIONS * 2:  # 10 runs
        res = retrieve_super(q, k=6)

    print("\n" + "=" * 60)
    print("BENCHMARK COMPLETE")
    if total_calls > 0:
        print(f"Total Successful Calls: {total_calls}/50")
        print(f"Average Pipeline Latency: {sum(total_times)/len(total_times):.2f} seconds")
    print("=" * 60)

if __name__ == "__main__":
    run_benchmark()
