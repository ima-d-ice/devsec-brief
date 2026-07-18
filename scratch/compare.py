import json
import sys
from pathlib import Path

master_path = Path("/Users/imad/Desktop/devsec-brief/eval_results/MASTER_EVALUATION_RESULTS.json")
new_path = Path("/Users/imad/Desktop/devsec-brief/eval_results/eval_results_0_15_20260718_054957.json")

with open(master_path) as f:
    master_data = json.load(f)

with open(new_path) as f:
    new_data = json.load(f)

# Create a lookup dictionary for master
master_lookup = {item["user_input"]: item for item in master_data}

print(f"{'Q#':<4} | {'Old CP':<8} | {'New CP':<8} | {'Old Ret(ms)':<11} | {'New Ret(ms)':<11} | {'Old Gen(ms)':<11} | {'New Gen(ms)':<11}")
print("-" * 85)

for i, new_item in enumerate(new_data):
    q = new_item["user_input"]
    new_cp = new_item.get("context_precision", 0)
    new_ret = new_item.get("retrieval_latency_ms", 0)
    new_gen = new_item.get("generation_latency_ms", 0)
    
    master_item = master_lookup.get(q, {})
    old_cp = master_item.get("context_precision", 0)
    old_ret = master_item.get("retrieval_latency_ms", 0)
    old_gen = master_item.get("generation_latency_ms", 0)
    
    print(f"{(i+1):<4} | {old_cp:<8.2f} | {new_cp:<8.2f} | {old_ret:<11.1f} | {new_ret:<11.1f} | {old_gen:<11.1f} | {new_gen:<11.1f}")
