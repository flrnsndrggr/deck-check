#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${API_BASE:-}" ]]; then
  echo "API_BASE is required (example: https://api.deck.check)"
  exit 1
fi

echo "== Health checks =="
curl -fsS "${API_BASE}/health/live" | jq .
curl -fsS "${API_BASE}/health/ready" | jq .

echo "== Parse =="
PARSE_PAYLOAD='{"decklist_text":"Commander\n1 The Peregrine Dynamo\nDeck\n98 Wastes\n1 Sol Ring\n","bracket":3,"multiplayer":true}'
PARSE_JSON="$(curl -fsS -X POST "${API_BASE}/api/decks/parse" -H "Content-Type: application/json" -d "${PARSE_PAYLOAD}")"
echo "${PARSE_JSON}" | jq '{commander, card_count, parse_errors, parse_warnings}'

echo "== Tag =="
TAG_PAYLOAD="$(jq -n --argjson parsed "${PARSE_JSON}" '{cards: $parsed.cards, commander: $parsed.commander, global_tags: true}')"
TAG_JSON="$(curl -fsS -X POST "${API_BASE}/api/decks/tag" -H "Content-Type: application/json" -d "${TAG_PAYLOAD}")"
echo "${TAG_JSON}" | jq '{cards_count: (.cards|length), tagged_lines_count: (.tagged_lines|length)}'

echo "== Sim run enqueue =="
SIM_PAYLOAD="$(jq -n --argjson tagged "${TAG_JSON}" --argjson parsed "${PARSE_JSON}" '{
  cards: $tagged.cards,
  commander: $parsed.commander,
  runs: 300,
  turn_limit: 8,
  policy: "auto",
  bracket: 3,
  multiplayer: true,
  threat_model: false,
  sim_backend: "vectorized",
  batch_size: 256,
  seed: 42
}')"
JOB_JSON="$(curl -fsS -X POST "${API_BASE}/api/sim/run" -H "Content-Type: application/json" -d "${SIM_PAYLOAD}")"
JOB_ID="$(echo "${JOB_JSON}" | jq -r '.job_id')"
if [[ -z "${JOB_ID}" || "${JOB_ID}" == "null" ]]; then
  echo "Failed to enqueue sim job:"
  echo "${JOB_JSON}" | jq .
  exit 1
fi
echo "Job ID: ${JOB_ID}"

echo "== Sim poll =="
STATUS="queued"
for _ in $(seq 1 120); do
  POLL="$(curl -fsS "${API_BASE}/api/sim/${JOB_ID}")"
  STATUS="$(echo "${POLL}" | jq -r '.status')"
  if [[ "${STATUS}" == "done" ]]; then
    echo "${POLL}" | jq '{status, backend_used: .result.summary.backend_used, p_mana4_t3: .result.summary.milestones.p_mana4_t3}'
    break
  fi
  if [[ "${STATUS}" == "failed" ]]; then
    echo "${POLL}" | jq .
    exit 1
  fi
  sleep 1
done

if [[ "${STATUS}" != "done" ]]; then
  echo "Timed out waiting for sim completion."
  exit 1
fi

echo "Smoke test passed."
