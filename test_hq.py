import asyncio
from src.db import search_keyword
from src.rag import generate_answer_from_context

def main():
    print("Fetching Hydro-Québec article directly from FTS...")
    # 1. Fetch exactly the Hydro-Québec document
    query = "Hydro-Québec"
    results = search_keyword(query, limit=1)
    
    if not results:
        print("No document found!")
        return
        
    doc = results[0]["document"]
    print(f"Document fetched! Total length: {len(doc)} characters.")
    
    # 2. Build the context WITHOUT ANY truncation
    context_str = f"Context Document:\n\n{doc}\n\n{'='*40}"
    
    question = "What are the specific vulnerability types identified in the Hydro-Québec Le Circuit Electrique charging station backend that contribute to its 9.8 CVSS score?"
    
    print(f"\nSending untruncated document (~{len(doc)//4} tokens) to LLM...")
    
    try:
        # 3. Generate answer
        answer = generate_answer_from_context(context_str, question)
        print("\n=== GENERATED ANSWER ===")
        print(answer)
        print("========================")
    except Exception as e:
        print(f"\nFailed! Error: {e}")

if __name__ == "__main__":
    main()
