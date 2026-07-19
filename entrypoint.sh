#!/bin/bash
set -e

echo "=== DevSec Brief Startup ==="

# 1. Ensure ONNX models are compiled
if [ ! -d "/app/data/onnx_st/bge-m3-onnx" ]; then
    echo "[Init] ONNX models not found in volume. Compiling now..."
    python -m src.export_st_onnx
else
    echo "[Init] ONNX binaries found."
fi

# 2. Ensure Database and Index are populated (if completely empty)
if [ ! -f "/app/data/news.db" ]; then
    echo "[Init] Database not found. Running initial feed fetch..."
    python -m src.refresh
else
    echo "[Init] Database found."
fi

# 3. Start the API Server
echo "[Init] Starting FastAPI server on port 8000..."
exec uvicorn src.api:app --host 0.0.0.0 --port 8000
