#!/usr/bin/env sh
set -eu
WEB_URL="${WEB_URL:-http://localhost:3000}"
API_URL="${API_URL:-http://localhost:8000}"

echo "Checking web: ${WEB_URL}"
curl -fsS "${WEB_URL}" >/dev/null

echo "Checking API: ${API_URL}/health/live"
curl -fsS "${API_URL}/health/live" >/dev/null

echo "Checking API docs: ${API_URL}/docs"
curl -fsS "${API_URL}/docs" >/dev/null

echo "Smoke checks passed."
