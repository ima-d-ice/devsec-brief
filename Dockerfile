FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install PyTorch CPU-only version first to avoid downloading 3GB of useless NVIDIA CUDA drivers
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Bake INT8 ONNX models into the image so containers boot with them present
# (entrypoint export then short-circuits; no downloads or fragile export at boot).
RUN python src/export_st_onnx.py

RUN chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]
