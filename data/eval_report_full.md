# DevSec-Brief RAG Evaluation Report

**Evaluation Date**: 2026-09-04 05:26:17  
**Evaluated Questions**: 139  
**Judge / Generation Model**: `qwen/qwen3.8-27b`  
**Total Benchmark Duration**: 1050.0s  

---

## 1. Executive Summary (RAG Triad Metrics)

| Metric | Score (0.0 – 1.0) | Benchmark Target | Status |
| :--- | :---: | :---: | :---: |
| **Context Precision** | **0.647** | ≥ 0.70 | ⚠️ REVIEW |
| **Faithfulness (Anti-Hallucination)** | **1.000** | ≥ 0.85 | ✅ PASS |
| **Answer Relevancy** | **0.647** | ≥ 0.80 | ⚠️ REVIEW |
| **Semantic Similarity (Ground Truth)** | **0.636** | ≥ 0.75 | ⚠️ REVIEW |

---

## 2. Latency Profiling

- **Average Retrieval Latency (Embedding + pgvector + RRF + Rerank)**: `3616.0 ms`
- **Average Generation Latency (Groq Key Pool)**: `645.4 ms`
- **Average Total Request Latency**: `4261.4 ms`

---

## 3. Sample Item Breakdown

| ID | Category | Context Precision | Faithfulness | Answer Relevancy | Semantic Similarity |
| :--- | :--- | :---: | :---: | :---: | :---: |
| `cve_01` | cybersec | 0.00 | 1.00 | 0.00 | 0.00 |
| `cve_02` | cybersec | 0.00 | 1.00 | 0.00 | 0.00 |
| `cve_03` | cybersec | 0.00 | 1.00 | 0.00 | 0.00 |
| `cve_04` | cybersec | 0.00 | 1.00 | 0.00 | 0.00 |
| `cve_05` | cybersec | 0.00 | 1.00 | 0.00 | 0.00 |
| `cve_06` | cybersec | 0.00 | 1.00 | 0.00 | 0.00 |
| `cve_07` | cybersec | 0.00 | 1.00 | 0.00 | 0.00 |
| `cve_08` | cybersec | 0.00 | 1.00 | 0.00 | 0.00 |
| `cve_09` | cybersec | 0.00 | 1.00 | 0.00 | 0.00 |
| `cve_10` | cybersec | 0.00 | 1.00 | 0.00 | 0.00 |
| `cve_11` | cybersec | 0.00 | 1.00 | 0.00 | 0.00 |
| `cve_12` | cybersec | 0.00 | 1.00 | 0.00 | 0.00 |
| `web_01` | webdev | 0.00 | 1.00 | 0.00 | 0.00 |
| `web_02` | webdev | 0.00 | 1.00 | 0.00 | 0.00 |
| `web_03` | webdev | 0.10 | 1.00 | 0.00 | 0.00 |
