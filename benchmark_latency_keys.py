import os
import json
import time
from dotenv import load_dotenv
from src.groq_client import set_api_key
from src.rag import answer_question

def main():
    load_dotenv()
    
    keys = [
        os.getenv("GROQ_API_KEY"),
        os.getenv("GROQ_API_KEY_2"),
        os.getenv("GROQ_API_KEY_3")
    ]
    
    if not all(keys):
        print("Missing one or more API keys in .env")
        return
        
    with open("data/evaluation_dataset.json", "r") as f:
        dataset = json.load(f)
        
    # We use only 30 questions from eval_dataset.json
    questions = dataset[:30]
    results = []
    
    print("Starting latency benchmark with 20s intervals...")
    
    for i, item in enumerate(questions):
        # Switch keys every 10 questions (0-9 -> Key 1, 10-19 -> Key 2, 20-29 -> Key 3)
        key_idx = i // 10
        current_key = keys[key_idx]
        
        # Set the key dynamically
        set_api_key(current_key)
        
        question = item["question"]
        print(f"[{i+1}/30] Using Key {key_idx + 1} - Question: {question[:50]}...")
        
        start_time = time.perf_counter()
        try:
            # We measure the full end-to-end true latency for answer_question
            res = answer_question(question)
            success = True
        except Exception as e:
            print(f"Error: {e}")
            success = False
            
        end_time = time.perf_counter()
        
        latency = end_time - start_time
        print(f"Latency: {latency:.4f}s")
        
        results.append({
            "index": i,
            "key_idx": key_idx + 1,
            "latency": latency,
            "success": success
        })
        
        # Sleep for 20 seconds to prevent rate limit exhaustion
        if i < len(questions) - 1:
            print("Sleeping for 20 seconds...\n")
            time.sleep(20)
            
    print("\nBenchmark Complete. Generating report...")
    
    # Generate report data
    report_data = {}
    for r in results:
        k = r["key_idx"]
        if k not in report_data:
            report_data[k] = []
        if r["success"]:
            report_data[k].append(r["latency"])
            
    total_latencies = [r["latency"] for r in results if r["success"]]
    
    print("\n=== LATENCY REPORT ===")
    if total_latencies:
        print(f"Total Successful Requests: {len(total_latencies)}")
        print(f"Average Latency (Overall): {sum(total_latencies)/len(total_latencies):.4f}s")
        print(f"Min Latency: {min(total_latencies):.4f}s")
        print(f"Max Latency: {max(total_latencies):.4f}s")
        
        for k, lats in report_data.items():
            if lats:
                print(f"\nKey {k} ({len(lats)} requests):")
                print(f"  Avg: {sum(lats)/len(lats):.4f}s")
                print(f"  Min: {min(lats):.4f}s")
                print(f"  Max: {max(lats):.4f}s")
            else:
                print(f"\nKey {k}: No successful requests")
    else:
        print("No successful requests.")
        
    # Dump results for further use if needed
    with open("latency_report.json", "w") as f:
        json.dump(results, f, indent=2)
        
if __name__ == "__main__":
    main()
