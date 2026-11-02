#!/bin/bash
# Injects real faults into the running stack, then checks everything recovered unaided.
# Needs make up. Leaves a detached ingestor running.
set -u
cd "$(dirname "$0")/.."
COMPOSE="docker compose -f infra/docker-compose.yml"
LOG=data/logs/ingestor.log
mkdir -p data/logs
PY() { (cd backend && uv run python "$@"); }

ingestor_pid() { pgrep -f 'python.*entrypoints.ingestor' | tail -1; }
start_ingestor() {
  (cd backend && nohup .venv/bin/python -m trading_intel.entrypoints.ingestor >>"../$LOG" 2>&1 &)
  for _ in $(seq 1 40); do
    grep -q ingestor_started "$LOG" && [ -n "$(ingestor_pid)" ] && return 0
    sleep 0.5
  done
}
state() {
  docker compose -f infra/docker-compose.yml exec -T redis redis-cli --raw GET "latest:market.status:$1" 2>/dev/null \
    | python3 -c 'import json,sys
try:
  p=json.load(sys.stdin)["payload"]; print(p["state"], "gaps", p["open_gaps"], p["reasons"][:1])
except Exception: print("NO STATUS")'
}
report() { echo "  spot: $(state binance_spot)"; echo "  usdm: $(state binance_usdm)"; }

echo "== 1 graceful stop"
pid=$(ingestor_pid)
if [ -n "$pid" ]; then kill -TERM "$pid"; sleep 4; pgrep -f 'python.*entrypoints.ingestor' >/dev/null && echo "  still running" || echo "  stopped cleanly"; fi
: >"$LOG"; start_ingestor; sleep 12; report

echo "== 2 second instance is refused"
(cd backend && timeout 20 .venv/bin/python -m trading_intel.entrypoints.ingestor 2>&1 | grep -o 'another ingestor holds lock [0-9]*' | head -1)

echo "== 3 Redis restart"
$COMPOSE restart redis >/dev/null 2>&1; sleep 15; report

echo "== 4 PostgreSQL restart"
$COMPOSE restart postgres >/dev/null 2>&1; sleep 20; report

echo "== 5 kill -9, then 75 seconds of nothing"
kill -9 "$(ingestor_pid)"; sleep 75; start_ingestor; sleep 25; report

echo "== 6 frozen process for 80 seconds, so Binance drops the link"
pid=$(ingestor_pid); kill -STOP "$pid"; sleep 80; kill -CONT "$pid"; sleep 30; report

echo "== log summary"
grep -oE '"event": "[a-z_]+"' "$LOG" | sort | uniq -c | sort -rn | head -14
