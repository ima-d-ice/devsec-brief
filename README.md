# DevSec Brief

**DevSec Brief** is a RAG-powered (Retrieval-Augmented Generation) news assistant designed to help developers and security professionals stay up-to-date. It aggregates articles from top Web Development and Cybersecurity RSS feeds, stores them locally, and uses an LLM to answer natural language questions based on the retrieved content.

## 🚀 Features

  * **Automated Feed Ingestion**: Fetches news from sources like Hacker News, MDN, web.dev, NCSC, CISA, and The Hacker News.
  * **Local Vector Search**: Uses **ChromaDB** and `sentence-transformers` to index and retrieve relevant articles semantically.
  * **AI-Powered Answers**: Utilizes **Groq** (running Llama 3.1) to synthesize answers from the retrieved news snippets.
  * **Dual Interfaces**:
      * **CLI**: A command-line tool for quick queries.
      * **API**: A FastAPI backend for integration with frontends.

## 🛠️ Tech Stack

  * **Language**: Python 3.x
  * **LLM Provider**: [Groq](https://groq.com/) (`llama-3.1-8b-instant`)
  * **Vector Database**: [ChromaDB](https://www.trychroma.com/) (Persistent local storage)
  * **Embeddings**: `sentence-transformers/all-MiniLM-L6-v2`
  * **Backend Framework**: FastAPI
  * **Database**: SQLite (for raw article storage)

## 📋 Prerequisites

1.  **Python**: Ensure you have Python installed (3.10+ recommended).
2.  **Groq API Key**: You need an API key from Groq to perform the LLM generation.

## 📦 Installation

1.  **Clone the repository** (or download the source files).

2.  **Set up a virtual environment** (recommended):

    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```

3.  **Install dependencies**:

    ```bash
    pip install -r requirements.txt
    ```

    *Dependencies include `feedparser`, `requests`, `chromadb`, `sentence-transformers`, `python-dotenv`, `groq`, `fastapi`, and `uvicorn`.*

4.  **Environment Configuration**:
    Create a `.env` file in the root directory:

    ```bash
    touch .env
    ```

    Add your Groq API key to the file:

    ```text
    GROQ_API_KEY=gsk_...your_key_here...
    ```

## ⚡ Usage

### 1\. Ingest Data (Refresh)

Before you can ask questions, you need to fetch the feeds and build the vector index. Run the refresh script:

```bash
python -m src.refresh
```

This script performs three actions:

1.  Initializes the SQLite database (`data/articles.db`).
2.  Fetches the latest RSS feeds and saves new articles.
3.  Generates embeddings and syncs them to the ChromaDB index (`data/chroma`).

### 2\. Command Line Interface (CLI)

You can query the system directly from the terminal using `ask.py`.

**Interactive Mode:**

```bash
python ask.py
```

**Direct Query:**

```bash
python ask.py "What are the latest vulnerabilities in Chrome?"
```

**Filter by Topic:**
You can limit the search to `webdev` or `cybersec` using the `--topic` flag:

```bash
python ask.py "New CSS features" --topic webdev
```

### 3\. API Server

To start the REST API for external consumption (e.g., a frontend application):

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
├── ask.py                 # CLI entry point
├── articles_sample.csv    # Sample data format
├── src/
│   ├── api.py             # FastAPI application
│   ├── db.py              # SQLite database operations
│   ├── embed_index.py     # ChromaDB embedding logic
│   ├── fetch_feeds.py     # RSS feed parsing and ingestion
│   ├── rag.py             # RAG logic (Query expansion + Groq generation)
│   └── refresh.py         # Main script to update data and index
└── data/                  # Generated directory for DB and Chroma
```

## 🛡️ Supported Feeds

The system currently tracks the following sources:

  * **Web Development**: Hacker News, MDN Blog, web.dev
  * **Cybersecurity**: NCSC (NL), CISA Advisories, The Hacker News
