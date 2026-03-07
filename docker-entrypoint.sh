#!/bin/bash
set -e

echo "Starting Be Rich API..."

# Run Alembic migrations (DB guaranteed ready by health check)
echo "Running database migrations..."
alembic upgrade head

# Start the application
echo "Starting FastAPI server..."
exec uvicorn main:app --reload --host 0.0.0.0 --port 8000