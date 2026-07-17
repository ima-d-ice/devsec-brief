# src/debug_check.py
import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

def main():
    print("=== 🛠️ DevSec Brief Debug Check ===")
    print("Goal: Verify all components without wasting LLM generation limits.\n")

    # 1. Check Environment Variables
    print("[1/5] Checking Environment Variables...")
    gemini_key = os.getenv("GEMINI_API_KEY")
    groq_key = os.getenv("GROQ_API_KEY")
    
    if not gemini_key:
        print("❌ FAIL: GEMINI_API_KEY is missing from .env file.")
        return
    print("✅ PASS: GEMINI_API_KEY found.")

    if not groq_key:
        print("❌ FAIL: GROQ_API_KEY is missing from .env file.")
        return
    print("✅ PASS: GROQ_API_KEY found.")

    # 2. Check SQLite Database & Data
    print("\n[2/5] Checking SQLite Database...")
    try:
        from src.db import get_conn
        conn = get_conn()
        count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        conn.close()
        if count == 0:
            print("❌ FAIL: Database is empty. Run `python3 -m src.refresh` first.")
            return
        print(f"✅ PASS: Database has {count} articles.")
    except Exception as e:
        print(f"❌ FAIL: Database error: {e}")
        return

    # 3. Check ChromaDB Vector Store
    print("\n[3/5] Checking ChromaDB Vector Store...")
    try:
        from src.embed_index import collection
        chroma_count = collection.count()
        if chroma_count == 0:
            print("❌ FAIL: ChromaDB is empty. Run `python3 -m src.refresh` first.")
            return
        print(f"✅ PASS: ChromaDB has {chroma_count} vectors.")
    except Exception as e:
        print(f"❌ FAIL: ChromaDB error: {e}")
        return

    # 4. Check Groq API Connection
    print("\n[4/5] Checking Groq API Connection (Listing models is free)...")
    try:
        from groq import Groq
        client = Groq(api_key=groq_key)
        models = client.models.list()
        print(f"✅ PASS: API Key valid. Found {len(models.data)} models available.")
    except Exception as e:
        print(f"❌ FAIL: Groq API connection failed: {e}")
        return

    # 5. Check RAGAS & LangChain Imports + Mock Data Structure
    print("\n[5/5] Checking RAGAS Pipeline Imports & Mock Data...")
    try:
        import sys, types
        sys.modules['langchain_community.chat_models'] = types.ModuleType('chat_models')
        sys.modules['langchain_community.chat_models.vertexai'] = types.ModuleType('vertexai')
        sys.modules['langchain_community.chat_models.vertexai'].ChatVertexAI = type('ChatVertexAI', (), {})
        
        try:
            import langchain_core.exceptions
            langchain_core.exceptions.ContextOverflowError = type('ContextOverflowError', (Exception,), {})
        except Exception:
            pass

        from datasets import Dataset
        from ragas import evaluate
        from ragas.metrics import context_precision, faithfulness, answer_relevancy
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_huggingface import HuggingFaceEmbeddings
        
        # Create mock data to ensure RAGAS can build a Dataset
        mock_data = [{
            "question": "What is 1+1?",
            "ground_truth": "2",
            "answer": "2",
            "contexts": ["1+1 equals 2."]
        }]
        hf_dataset = Dataset.from_list(mock_data)
        
        # Verify the custom RateLimitedGroqOpenAI class can be instantiated
        from src.evaluate import RateLimitedGroqOpenAI
        test_llm = RateLimitedGroqOpenAI(
            model="openai/gpt-oss-120b",
            temperature=0,
            base_url="https://api.groq.com/openai/v1",
            api_key=groq_key
        )
        test_embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
        
        print("✅ PASS: All RAGAS dependencies imported successfully.")
        print("✅ PASS: Mock dataset created successfully.")
        print("✅ PASS: Rate-limited LLM wrapper initialized.")
        
    except ImportError as e:
        print(f"❌ FAIL: Missing dependency: {e}")
        print("Run: pip install ragas datasets langchain-google-genai langchain-huggingface")
        return
    except Exception as e:
        print(f"❌ FAIL: RAGAS setup error: {e}")
        return

    print("\n=== 🎉 ALL CHECKS PASSED ===")
    print("You are safe to run the actual scripts:")
    print("1. python3 -m src.generate_eval_dataset")
    print("2. python3 -m src.evaluate")

if __name__ == "__main__":
    main()
