# src/run_parallel_eval.py
"""
Master orchestrator that launches 3 parallel evaluate.py processes,
each using a different Groq API key and dataset slice.
"""
import subprocess
import sys
import json
import time
import os
from datetime import datetime
from pathlib import Path

VENV_PYTHON = Path(__file__).resolve().parents[1] / "venv" / "bin" / "python"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = PROJECT_ROOT / "eval_results"
DATASET_PATH = PROJECT_ROOT / "data" / "evaluation_dataset.json"

# Define the 2 parallel lanes for REMAINING questions
LANES = [
    {"start": 13, "end": 20, "api_key_env": "GROQ_API_KEY_2", "tag": "lane1_remaining"},
    {"start": 33, "end": 40, "api_key_env": "GROQ_API_KEY_3", "tag": "lane2_remaining"},
]


def main():
    # Verify dataset exists
    with open(DATASET_PATH, "r") as f:
        total = len(json.load(f))
    print(f"📊 Dataset loaded: {total} questions total")
    print(f"🚀 Launching {len(LANES)} parallel evaluation processes...\n")

    processes = []
    for lane in LANES:
        tag = lane["tag"]
        cmd = [
            str(VENV_PYTHON), "-m", "src.evaluate",
            "--start", str(lane["start"]),
            "--end", str(lane["end"]),
            "--api_key_env", lane["api_key_env"],
            "--output_tag", tag,
        ]
        log_file = RESULTS_DIR / f"{tag}_run.log"
        f = open(log_file, "w")
        print(f"  ▶ Lane [{lane['start']}:{lane['end']}] using {lane['api_key_env']} (Logging to {log_file.name})")
        
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        
        proc = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
            stdout=f,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
        processes.append((lane, proc, f))

    print(f"\n⏳ All {len(LANES)} processes launched. Waiting for completion...\n")

    # Wait for all processes
    for lane, proc, f in processes:
        tag = lane["tag"]
        proc.wait()
        f.close()
        status = "✅" if proc.returncode == 0 else "❌"
        print(f"\n{'='*80}")
        print(f"{status} {tag} [{lane['start']}:{lane['end']}] exited with code {proc.returncode}")
        print(f"{'='*80}")

    # Aggregate results
    print(f"\n{'='*80}")
    print("📦 Aggregating results...")
    print(f"{'='*80}")

    combined = []
    for lane in LANES:
        tag = lane["tag"]
        # Find the most recent file matching this tag
        matches = sorted(RESULTS_DIR.glob(f"eval_results_{tag}_*.json"), reverse=True)
        if matches:
            with open(matches[0], "r") as f:
                chunk = json.load(f)
            print(f"  ✅ {tag}: loaded {len(chunk)} results from {matches[0].name}")
            combined.extend(chunk)
        else:
            print(f"  ❌ {tag}: No output file found!")

    if combined:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        combined_path = RESULTS_DIR / f"eval_results_combined_{timestamp}.json"
        with open(combined_path, "w") as f:
            json.dump(combined, f, indent=2)
        print(f"\n🎉 Combined {len(combined)} results saved to: {combined_path.name}")
    else:
        print("\n❌ No results to aggregate.")


if __name__ == "__main__":
    main()
