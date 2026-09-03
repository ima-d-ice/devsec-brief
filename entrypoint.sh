#!/bin/bash
set -e

echo "Ensuring ONNX models are compiled..."
python src/export_st_onnx.py

# If a command is passed to docker run, execute it instead of starting the API
if [ "$#" -gt 0 ]; then
    exec "$@"
fi

echo "Initializing database schema..."
python -c "from src.db import init_db; init_db()"

echo "Starting API..."
exec uvicorn src.api:app --host 0.0.0.0 --port 8000 --log-config logging.conf.json
