#!/bin/bash
# Starts the stack at login and restarts any part that stops, as launchd user agents.
# The services read .env themselves, so no secret is written into an agent.
#
#   scripts/autostart.sh install        start everything now and at every login
#   scripts/autostart.sh status         what is running, with each agent's last exit code
#   scripts/autostart.sh restart NAME   restart one part, for example after a backend change
#   scripts/autostart.sh rebuild-web    stop the dashboard, build it, start it again
#   scripts/autostart.sh uninstall      stop everything and remove the agents
#
# NAME is one of: awake ingestor quant-worker api web. "awake" keeps the computer from idle
# sleep, and from any sleep on mains power, as scripts/soak.sh did. PostgreSQL and Redis
# restart with OrbStack, which install sets to start at login.
set -eu
cd "$(dirname "$0")/.."
REPO=$(pwd)
AGENTS="$HOME/Library/LaunchAgents"
DOMAIN="gui/$(id -u)"
PREFIX=com.trading-intel
NAMES="awake ingestor quant-worker api web"
PYTHON="$REPO/backend/.venv/bin/python"
TOOLS_PATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin

program() {
  case "$1" in
    awake) ARGS=(/usr/bin/caffeinate -i -s); DIR=$REPO; LOG=/dev/null ;;
    ingestor) ARGS=("$PYTHON" -m trading_intel.entrypoints.ingestor); DIR=$REPO/backend ;;
    quant-worker) ARGS=("$PYTHON" -m trading_intel.entrypoints.quant_worker); DIR=$REPO/backend ;;
    api) ARGS=("$PYTHON" -m trading_intel.entrypoints.api); DIR=$REPO/backend ;;
    web) ARGS=(/opt/homebrew/bin/pnpm start); DIR=$REPO/frontend ;;
    *) echo "Unknown part: $1. Use one of: $NAMES" >&2; exit 2 ;;
  esac
  if [ "$1" != awake ]; then LOG=$REPO/data/logs/$1.log; fi
}

plist() {
  program "$1"
  local arguments=""
  for argument in "${ARGS[@]}"; do arguments+="    <string>$argument</string>"$'\n'; done
  cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$PREFIX.$1</string>
  <key>ProgramArguments</key>
  <array>
$arguments  </array>
  <key>WorkingDirectory</key>
  <string>$DIR</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>$TOOLS_PATH</string>
    <key>PYTHONUNBUFFERED</key>
    <string>1</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ThrottleInterval</key>
  <integer>30</integer>
  <key>StandardOutPath</key>
  <string>$LOG</string>
  <key>StandardErrorPath</key>
  <string>$LOG</string>
</dict>
</plist>
EOF
}

loaded() {
  launchctl print "$DOMAIN/$PREFIX.$1" >/dev/null 2>&1
}

start() {
  local file="$AGENTS/$PREFIX.$1.plist"
  plist "$1" >"$file"
  plutil -lint "$file" >/dev/null
  loaded "$1" || launchctl bootstrap "$DOMAIN" "$file"
}

stop() {
  if loaded "$1"; then launchctl bootout "$DOMAIN/$PREFIX.$1"; fi
}

case "${1:-}" in
  install)
    # A copy started by hand would run twice, and two ingestors would store everything twice.
    manual=$(pgrep -fl 'entrypoints\.(ingestor|quant_worker|api)|pnpm start|next start|caffeinate -i -s -w' || true)
    if [ -n "$manual" ] && ! loaded ingestor; then
      echo "Stop these first, then install again:" >&2
      echo "$manual" >&2
      exit 1
    fi
    [ -x "$PYTHON" ] || { echo "Run make bootstrap first: $PYTHON is missing." >&2; exit 1; }
    [ -d "$REPO/frontend/.next" ] || { echo "Build the dashboard first: cd frontend && pnpm build" >&2; exit 1; }
    mkdir -p "$AGENTS" "$REPO/data/logs"
    orb config set app.start_at_login true
    for name in $NAMES; do start "$name"; done
    echo "Installed. Everything starts at login and restarts if it stops."
    ;;
  status)
    launchctl list | awk -v prefix="$PREFIX." 'NR == 1 || index($3, prefix) == 1'
    echo "PID - means not running. Status is the last exit code; 0 or - is normal."
    ;;
  restart)
    program "${2:?Name a part: $NAMES}"
    launchctl kickstart -k "$DOMAIN/$PREFIX.$2"
    ;;
  rebuild-web)
    stop web
    (cd frontend && pnpm build)
    start web
    ;;
  uninstall)
    for name in $NAMES; do stop "$name"; rm -f "$AGENTS/$PREFIX.$name.plist"; done
    echo "Removed. Nothing starts at login now. OrbStack still does: orb config set app.start_at_login false"
    ;;
  *)
    sed -n '2,13p' "$0"
    exit 2
    ;;
esac
