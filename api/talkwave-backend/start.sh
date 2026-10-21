#!/bin/bash
set -e

PORT=${PORT:-8000}
UVICORN_WORKERS=${UVICORN_WORKERS:-4}
ARQ_WORKERS=${ARQ_WORKERS:-1}

cleanup() {
    echo "Shutting down all processes..."
    kill $(jobs -p) 2>/dev/null
    wait
}
trap cleanup SIGTERM SIGINT

echo "Running database migrations..."
(cd /app/api && alembic upgrade heads) || echo "WARNING: alembic migrations failed (non-fatal)"

echo "Starting ARQ worker(s)..."
for i in $(seq 1 "$ARQ_WORKERS"); do
    python -m arq api.tasks.arq.WorkerSettings &
done

echo "Starting campaign orchestrator..."
python -m api.services.campaign.campaign_orchestrator &

echo "Starting uvicorn on port $PORT with $UVICORN_WORKERS workers..."
uvicorn api.app:app --host 0.0.0.0 --port "$PORT" --workers "$UVICORN_WORKERS" &

wait -n
cleanup
