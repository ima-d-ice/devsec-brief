#!/usr/bin/env bash
set -euo pipefail

# Models are baked into the image; schema changes run in the dedicated
# `migrate` Compose service. This entrypoint only starts the requested process.
if [ "$#" -gt 0 ]; then
    exec "$@"
fi

exec uvicorn src.api:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --workers "${UVICORN_WORKERS:-1}" \
    --proxy-headers \
    --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}"
