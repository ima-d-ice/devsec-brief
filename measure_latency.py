import time
from src.rag import retrieve_super

def measure():
    query = "What are the latest zero-day vulnerabilities in Linux?"
    
    print("\n" + "="*50)
    print("WARM-UP RUN (Compiling ONNX / Initializing connections)")
    print("="*50)
    _ = retrieve_super(query, k=5)
    
    print("\n" + "="*50)
    print("ACTUAL BENCHMARK RUN (Pure Retrieval)")
    print("="*50)
    
    start_time = time.perf_counter()
    result = retrieve_super(query, k=5)
    end_time = time.perf_counter()
    
    total_ms = (end_time - start_time) * 1000
    
    print("\nResults:")
    print(f"- Total Retrieval Latency: {total_ms:.2f} ms")
    print(f"- Documents Retrieved: {len(result['documents'][0])}")

if __name__ == "__main__":
    measure()
