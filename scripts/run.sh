#!/bin/bash
# Start Historiador server
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Load .env if present
if [ -f .env ]; then
    export $(grep -v ^# .env | xargs)
fi

echo "Starting Historiador..."
echo "Database: ${DATABASE_URL:-sqlite+aiosqlite:///./historiador.db}"
echo "LLM Model: ${LLM_MODEL:-deepseek-v4-flash}"
echo "LLM API: ${LLM_BASE_URL:-https://api.nan.builders/v1}"

exec uvicorn backend.main:app --host 0.0.0.0 --port 8080 --reload