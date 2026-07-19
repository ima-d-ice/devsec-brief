# DevSec Brief

**DevSec Brief** is a highly optimized RAG-powered (Retrieval-Augmented Generation) news assistant designed to help developers and security professionals stay up-to-date. It aggregates articles from top Web Development and Cybersecurity RSS feeds, stores them locally, and uses an LLM to answer natural language questions based on the retrieved content.

The retrieval stack is specifically engineered for **zero GPU memory footprint**, running deeply compressed INT8 ONNX models entirely on the CPU. This preserves your VRAM for running heavy local Multi-Agent LLM daemons simultaneously.

## 🚀 Features

  * **Automated Feed Ingestion**: Fetches news from sources like Hacker News, MDN, web.dev, NCSC, CISA, and The Hacker News.
  * **Zero-VRAM Hybrid Retrieval**: Uses a hybrid approach (Semantic embeddings + Keyword routing via `entity_glossary.json`) executed through blazing fast INT8 ONNX binaries on the CPU.
  * **Advanced Reranking**: Re-scores candidate documents using an ONNX-optimized cross-encoder (`mMARCO`) for maximum accuracy.
  * **AI-Powered Answers**: Utilizes **Groq** (Llama 3.1) to synthesize high-speed answers from the retrieved news snippets.
  * **API-First**: A FastAPI backend designed for robust integration with frontends and multi-agent systems.

## 🛠️ Tech Stack

  * **Language**: Python 3.12+
  * **LLM Provider**: [Groq](https://groq.com/) (`llama-3.1-8b-instant`)
  * **Vector Database**: [ChromaDB](https://www.trychroma.com/) (Persistent local storage)
  * **Embeddings & Reranking**: 
    * `BAAI/bge-m3` (Embeddings)
    * `cross-encoder/mmarco` (Reranker)
    * *Both exported to 8-bit Integer (INT8) ONNX models running on the CPUExecutionProvider.*
  * **Backend Framework**: FastAPI
  * **Database**: SQLite (for raw article storage)

## 📋 Prerequisites

1.  **Python**: Ensure you have Python installed (3.10+ recommended).
2.  **Groq API Key**: You need an API key from Groq to perform the LLM generation.
3.  **Local ONNX Compilation**: You must compile the embedding models to ONNX on first setup (see below).

## 📦 Installation

1.  **Clone the repository**.
2.  **Set up a virtual environment** (recommended):
    ```bash
    python -m venv venv
    source venv/bin/activate
    ```
3.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
4.  **Environment Configuration**:
    Create a `.env` file in the root directory and add your Groq API key:
    ```text
    GROQ_API_KEY_4=gsk_...your_key_here...
    ```

## ⚡ Usage

### 1. Compile ONNX Models
Before running the system, export the PyTorch models to INT8 ONNX binaries to ensure the CPU execution pathway is ready:
```bash
python -m src.export_st_onnx
```

### 2. Ingest Data (Refresh)
Fetch the feeds and build the vector index:
```bash
python -m src.refresh
```
This script initializes the SQLite database, fetches the latest RSS feeds, and syncs the vector embeddings to the ChromaDB index (`data/chroma`).

### 3. API Server
Start the REST API for external consumption (or daemon agent integration):
```bash
uvicorn src.api:app --reload
```
The API will be available at `http://127.0.0.1:8000`.
  * **Swagger Documentation**: Visit `http://127.0.0.1:8000/docs` to test endpoints interactively.
  * **Endpoint**: `POST /ask`
    * Payload: `{"query": "your question", "topic": "optional_topic", "k": 6}`.

## 📂 Project Structure

```text
.
├── .gitignore             # Git ignore rules
├── requirements.txt       # Python dependencies
├── src/
│   ├── api.py             # FastAPI application
│   ├── db.py              # SQLite database operations
│   ├── embed_index.py     # ChromaDB embedding logic
│   ├── export_st_onnx.py  # Quantizes HuggingFace models to INT8 ONNX
│   ├── extract_entities.py# Entity extraction for glossary
│   ├── fetch_feeds.py     # RSS feed parsing and ingestion
│   ├── groq_client.py     # API wrapper for Groq rate limits
│   ├── rag.py             # Retrieval logic (Hybrid + ONNX Rerank)
│   └── refresh.py         # Main script to update data and index
└── data/                  # Generated directory for DB, Chroma, and ONNX binaries
    ├── onnx_st/           # Location of compiled ONNX binaries
    └── entity_glossary.json # Lightweight keyword routing index
```

## 🛡️ Supported Feeds

The system currently tracks the following sources:
  * **Web Development**: Hacker News, MDN Blog, web.dev
  * **Cybersecurity**: NCSC (NL), CISA Advisories, The Hacker News
