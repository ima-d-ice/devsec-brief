# src/monitor.py
import json, glob, sys, time
from pathlib import Path

lanes = {
    "Lane 1 Rem (Q13-20)": (13, 20, "lane1_remaining"),
    "Lane 2 Rem (Q33-40)": (33, 40, "lane2_remaining"),
}

def print_progress():
    print("\033[2J\033[H") # Clear screen
    print("🚀 PARALLEL EVALUATION PROGRESS 🚀")
    print("==================================\n")

    for name, (start, end, tag) in lanes.items():
        total = end - start
        files = sorted(glob.glob(f"eval_results/eval_results_{tag}_*.json"), reverse=True)
        if not files:
            completed = 0
        else:
            try:
                with open(files[0]) as f:
                    completed = len(json.load(f))
            except:
                completed = 0
        
        perc = int((completed / total) * 100)
        bar = "█" * int(perc / 5) + "░" * (20 - int(perc / 5))
        
        # Color coding
        if perc == 100:
            color = "\033[92m" # Green
        elif perc > 0:
            color = "\033[93m" # Yellow
        else:
            color = "\033[90m" # Gray
            
        print(f"{name:<20} |{color}{bar}\033[0m| {completed}/{total} ({perc}%)")
        
        # Read tail of log file
        log_file = Path(f"eval_results/{tag}_run.log")
        if log_file.exists():
            try:
                with open(log_file, "r") as lf:
                    lines = lf.readlines()[-5:]
                    for line in lines:
                        print(f"    \033[36m{line.strip()}\033[0m")
            except Exception:
                pass
        print("")
    
    print("==================================")
    print("Press Ctrl+C to exit monitor.")

if __name__ == "__main__":
    try:
        while True:
            print_progress()
            time.sleep(5)
    except KeyboardInterrupt:
        print("\nExiting monitor.")
