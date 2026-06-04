#!/bin/bash
# Start Historiador server
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Auto-run setup wizard if .env doesn't exist
if [ ! -f .env ]; then
    echo "No .env found — running setup wizard..."
    uv run python3 scripts/setup.py
    echo ""
fi

# Load .env if present
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

echo "Starting Historiador..."
echo "Database: ${DATABASE_URL:-sqlite+aiosqlite:///./historiador.db}"
echo "LLM Model: ${LLM_MODEL:-deepseek-v4-flash}"
echo "LLM API: ${LLM_BASE_URL:-https://api.nan.builders/v1}"
echo "Search:   ${SEARCH_PROVIDER:-duckduckgo}"

exec uvicorn backend.main:app --host 0.0.0.0 --port 8080 --reload