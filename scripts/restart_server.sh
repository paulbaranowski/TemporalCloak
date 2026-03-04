#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

PID=$(lsof -ti :8888 2>/dev/null) && kill "$PID" && echo "Killed existing server (PID $PID)" || echo "No existing server running"

sleep 1

cd "$PROJECT_DIR"
echo "Starting server..."
uv run python demos/temporal_cloak_web_demo.py
