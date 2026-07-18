import json
import random
from pathlib import Path

# Paths
MASTER_EVAL_PATH = Path(__file__).resolve().parents[1] / "eval_results" / "MASTER_EVALUATION_RESULTS.json"
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "data" / "eval_subset_16.json"

def main():
    with open(MASTER_EVAL_PATH, "r") as f:
        data = json.load(f)

    # Categories
    zero_cp = []
    high_cp = []
    medium_cp = []

    for item in data:
        cp = item.get("context_precision")
        if cp is None:
            continue
            
        if cp < 0.1:
            zero_cp.append(item)
        elif cp > 0.9:
            high_cp.append(item)
        elif 0.3 <= cp <= 0.8:
            medium_cp.append(item)

    # We need 6 near zero, 6 high, 4 medium
    # Use a fixed seed for reproducibility
    random.seed(42)
    
    selected_zero = random.sample(zero_cp, min(6, len(zero_cp)))
    selected_high = random.sample(high_cp, min(6, len(high_cp)))
    selected_medium = random.sample(medium_cp, min(4, len(medium_cp)))

    combined = selected_zero + selected_high + selected_medium
    print(f"Selected: {len(selected_zero)} zero, {len(selected_high)} high, {len(selected_medium)} medium. Total = {len(combined)}")

    # Format for evaluate.py
    final_dataset = []
    for item in combined:
        final_dataset.append({
            "question": item["user_input"],
            "expected_answer": item["reference"],
            "original_context_precision": item.get("context_precision")
        })

    # Save
    with open(OUTPUT_PATH, "w") as f:
        json.dump(final_dataset, f, indent=2)
    print(f"Saved to {OUTPUT_PATH}")

if __name__ == "__main__":
    main()
