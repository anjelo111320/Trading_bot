#!/bin/bash
# Runs the ingestor detached, with idle sleep prevented, and system sleep while on mains power.
# Keep the computer plugged in with the lid open. To stop: pkill -f entrypoints.ingestor
set -eu
cd "$(dirname "$0")/.."
mkdir -p data/logs
if pgrep -f 'python.*entrypoints.ingestor' >/dev/null; then
  echo "An ingestor is already running."
  exit 1
fi
(cd backend && nohup .venv/bin/python -m trading_intel.entrypoints.ingestor >>../data/logs/ingestor.log 2>&1 &)
sleep 3
pid=$(pgrep -f 'python.*entrypoints.ingestor' | tail -1)
nohup caffeinate -i -s -w "$pid" >/dev/null 2>&1 &
date -u +"Soak started %Y-%m-%dT%H:%M:%SZ, ingestor pid $pid"
