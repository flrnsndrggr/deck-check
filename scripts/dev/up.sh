#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/../.."
docker compose up --build -d
echo "Deck.Check stack is up: http://localhost:3000 (web), http://localhost:8000/docs (api docs)"
