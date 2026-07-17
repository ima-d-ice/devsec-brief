import sys
import types
dummy_module = types.ModuleType("langchain_community.chat_models.vertexai")
dummy_module.ChatVertexAI = None
sys.modules["langchain_community.chat_models.vertexai"] = dummy_module
# src/evaluate.py
import json
import time
import os
import argparse
import traceback
from datetime import datetime
from pathlib import Path
from typing import ClassVar
import asyncio
from datasets import Dataset
from ragas import evaluate
from ragas.run_config import RunConfig
from ragas.metrics import context_precision, faithfulness, answer_relevancy

# Using LangChain's OpenAI client configured for Groq
from langchain_openai import ChatOpenAI
from langchain_core.outputs import ChatResult
from langchain_huggingface import HuggingFaceEmbeddings

from dotenv import load_dotenv
from src.rag import retrieve_super, build_context, generate_answer_from_context

load_dotenv()

# --- CLI Arguments for Parallel Execution ---
parser = argparse.ArgumentParser(description="RAGAS Evaluation Pipeline")
parser.add_argument("--start", type=int, default=0, help="Start index (inclusive)")
parser.add_argument("--end", type=int, default=None, help="End index (exclusive)")
parser.add_argument("--api_key_env", type=str, default="GROQ_API_KEY", help="Env var name for the Groq API key")
parser.add_argument("--output_tag", type=str, default=None, help="Tag for the output filename")
args = parser.parse_args()

GROQ_API_KEY = os.getenv(args.api_key_env)
if not GROQ_API_KEY:
    raise ValueError(f"API key not found in env var: {args.api_key_env}")

# CRITICAL: Switch the generation client to use THIS lane's API key
from src.groq_client import set_api_key
set_api_key(GROQ_API_KEY)
DATASET_PATH = Path(__file__).resolve().parents[1] / "data" / "evaluation_dataset.json"
RESULTS_DIR = Path(__file__).resolve().parents[1] / "eval_results"
RESULTS_DIR.mkdir(exist_ok=True)

class RateLimitedGroqOpenAI(ChatOpenAI):
    """
    Custom wrapper using OpenAI SDK pointed at Groq.
    Enforces 30 RPM limit and intercepts n>1 requests to loop them.
    """
    MAX_RPD: ClassVar[int] = 950  # Safe limit under 1K RPD
    min_interval: ClassVar[float] = 20.0  # 3 RPM = 1 req every 20 seconds

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._last_call_time = 0.0
        self._request_count = 0

    def _enforce_rate_limit_sync(self):
        if self._request_count >= self.MAX_RPD:
            raise RuntimeError("🛑 Daily RPD limit reached. Halting evaluation.")
        
        current_time = time.time()
        elapsed = current_time - self._last_call_time
        if elapsed < self.min_interval:
            sleep_time = self.min_interval - elapsed
            print(f"  [Rate Limiter] Sleeping for {sleep_time:.1f}s...")
            time.sleep(sleep_time)
            
        self._last_call_time = time.time()
        self._request_count += 1
        print(f"  [API Usage] Request {self._request_count}/{self.MAX_RPD}")

    async def _enforce_rate_limit_async(self):
        if self._request_count >= self.MAX_RPD:
            raise RuntimeError("🛑 Daily RPD limit reached. Halting evaluation.")
        
        current_time = time.time()
        elapsed = current_time - self._last_call_time
        if elapsed < self.min_interval:
            sleep_time = self.min_interval - elapsed
            print(f"  [Rate Limiter] Sleeping for {sleep_time:.1f}s (async)...")
            await asyncio.sleep(sleep_time)
            
        self._last_call_time = time.time()
        self._request_count += 1
        print(f"  [API Usage] Request {self._request_count}/{self.MAX_RPD}")

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._handle_multi_candidate(messages, stop, run_manager, **kwargs)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return await self._ahandle_multi_candidate(messages, stop, run_manager, **kwargs)

    def _handle_multi_candidate(self, messages, stop, run_manager, **kwargs):
        original_n = kwargs.pop('n', getattr(self, 'n', 1))
        old_n = getattr(self, 'n', 1)
        if hasattr(self, 'n'):
            self.n = 1
            
        try:
            if original_n > 1:
                all_generations = []
                for _ in range(original_n):
                    self._enforce_rate_limit_sync()
                    result = super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
                    all_generations.extend(result.generations)
                return ChatResult(generations=all_generations, llm_output=result.llm_output)
            else:
                self._enforce_rate_limit_sync()
                return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        finally:
            if hasattr(self, 'n'):
                self.n = old_n

    async def _ahandle_multi_candidate(self, messages, stop, run_manager, **kwargs):
        original_n = kwargs.pop('n', getattr(self, 'n', 1))
        old_n = getattr(self, 'n', 1)
        if hasattr(self, 'n'):
            self.n = 1
            
        try:
            if original_n > 1:
                all_generations = []
                for _ in range(original_n):
                    await self._enforce_rate_limit_async()
                    result = await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
                    all_generations.extend(result.generations)
                return ChatResult(generations=all_generations, llm_output=result.llm_output)
            else:
                await self._enforce_rate_limit_async()
                return await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
        finally:
            if hasattr(self, 'n'):
                self.n = old_n

def run_evaluation():
    with open(DATASET_PATH, 'r') as f:
        golden_data = json.load(f)

    # Slice the dataset based on CLI args
    start = args.start
    end = args.end if args.end is not None else len(golden_data)
    golden_data = golden_data[start:end]

    tag = args.output_tag or f"{start}_{end}"
    print(f"=== Starting RAGAS Evaluation Pipeline (slice [{start}:{end}], key={args.api_key_env}) ===")
    print(f"Processing {len(golden_data)} questions.")

    print("Initializing Rate-Limited Groq OpenAI Judge...")
    judge_llm = RateLimitedGroqOpenAI(
        model="openai/gpt-oss-120b",
        temperature=0,
        base_url="https://api.groq.com/openai/v1",
        api_key=GROQ_API_KEY
    )
    judge_embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_path = RESULTS_DIR / f"eval_results_{tag}_{timestamp}.json"
    
    evaluated_results = []
    
    for i, item in enumerate(golden_data):
        question = item["question"]
        global_idx = start + i
        print(f"\n[{global_idx+1}/{start+len(golden_data)}] Processing: {question}")
        
        # Measure retrieval latency
        t_ret_start = time.perf_counter()
        res = retrieve_super(question, topic=None, k=6)
        retrieval_ms = (time.perf_counter() - t_ret_start) * 1000
        
        context_str = build_context(res)
        
        if not context_str.strip():
            print("  -> Skipping: No context found.")
            continue
        
        # Measure generation latency
        t_gen_start = time.perf_counter()
        answer = generate_answer_from_context(context_str, question)
        generation_ms = (time.perf_counter() - t_gen_start) * 1000
        
        print(f"  ⏱️  retrieval: {retrieval_ms:.1f}ms | generation: {generation_ms:.1f}ms")
        
        contexts = []
        if res.get("documents") and res["documents"][0]:
            for doc in res["documents"][0][:3]:
                contexts.append(doc[:4000].strip())
            
        row_data = {
            "question": question,
            "ground_truth": item["expected_answer"],
            "answer": answer,
            "contexts": contexts,
            "retrieval_latency_ms": round(retrieval_ms, 1),
            "generation_latency_ms": round(generation_ms, 1),
        }
        
        hf_dataset = Dataset.from_list([row_data])
        try:
            print("  -> Evaluating with RAGAS...")
            result = evaluate(
                hf_dataset,
                metrics=[context_precision, faithfulness, answer_relevancy],
                llm=judge_llm,
                embeddings=judge_embeddings,
                raise_exceptions=True,
                run_config=RunConfig(max_workers=1, timeout=600)
            )
            result_df = result.to_pandas()
            # Convert single row to dict
            row_result = result_df.to_dict(orient="records")[0]
            # Replace NaNs with None so it can be JSON serialized properly
            for k, v in row_result.items():
                if str(v) == "nan":
                    row_result[k] = None
                    
            # Manually inject latency back in
            row_result["retrieval_latency_ms"] = row_data["retrieval_latency_ms"]
            row_result["generation_latency_ms"] = row_data["generation_latency_ms"]
            
            evaluated_results.append(row_result)
            
            cp = row_result.get("context_precision") or 0.0
            ft = row_result.get("faithfulness") or 0.0
            ar = row_result.get("answer_relevancy") or 0.0
            print(f"  ✅ Scores: Precision={cp:.2f}, Faithfulness={ft:.2f}, Relevancy={ar:.2f}")
            
        except Exception as e:
            print(f"  ❌ RAGAS evaluation failed for this question: {repr(e)}")
            evaluated_results.append(row_data) # Save without scores
            
        with open(save_path, "w") as f_out:
            json.dump(evaluated_results, f_out, indent=2)
        print(f"  💾 Progress saved to {save_path.name}")
        
    print(f"\n✅ Slice [{start}:{end}] complete. {len(evaluated_results)} results saved to: {save_path}")
if __name__ == "__main__":
    run_evaluation()
