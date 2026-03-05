#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/../.."
docker compose down --remove-orphans
echo "Deck.Check stack is down."
