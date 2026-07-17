import os
import json
import time
from dotenv import load_dotenv
from src.groq_client import set_api_key
from src.rag import answer_question

def main():
    load_dotenv()
    
    # Using only GROQ_API_KEY
    current_key = os.getenv("GROQ_API_KEY")
    if not current_key:
        print("Missing GROQ_API_KEY in .env")
        return
        
    with open("data/evaluation_dataset.json", "r") as f:
        dataset = json.load(f)
        
    # We use only 10 questions for this benchmark
    questions = dataset[:10]
    results = []
    
    print("Starting Llama 3.1 8b Instant latency benchmark (10 questions, 20s interval)...")
    
    # Set the key
    set_api_key(current_key)
    
    for i, item in enumerate(questions):
        question = item["question"]
        print(f"[{i+1}/10] Question: {question[:50]}...")
        
        start_time = time.perf_counter()
        try:
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
            "latency": latency,
            "success": success
        })
        
        if i < len(questions) - 1:
            print("Sleeping for 20 seconds...\n")
            time.sleep(20)
            
    print("\nBenchmark Complete.")
        
if __name__ == "__main__":
    main()
