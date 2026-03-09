#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

PIDS=$(lsof -ti :8888 2>/dev/null) && echo "$PIDS" | xargs kill && echo "Killed existing server (PID $PIDS)" || echo "No existing server running"

sleep 1

cd "$PROJECT_DIR"
echo "Starting server..."
uv run python demos/temporal_cloak_web.py
