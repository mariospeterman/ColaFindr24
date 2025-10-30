#!/bin/zsh

set -uo pipefail

PROJECT_DIR="/Users/maki/Desktop/colafinder"
VENV_PY="$PROJECT_DIR/venv/bin/python"
SCRIPT="$PROJECT_DIR/monitor_autos.py"
LOGFILE="$PROJECT_DIR/monitor_autos.log"
ENV_FILE="$PROJECT_DIR/.env"

# Read CRON_SCHEDULE from .env or default to every 6 hours
CRON_SCHEDULE_DEFAULT="0 */6 * * *"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC2046
  CRON_SCHEDULE=$(grep -E '^CRON_SCHEDULE=' "$ENV_FILE" | sed 's/^CRON_SCHEDULE=//')
else
  CRON_SCHEDULE=""
fi
[[ -z "$CRON_SCHEDULE" ]] && CRON_SCHEDULE="$CRON_SCHEDULE_DEFAULT"

JOB_LINE="$CRON_SCHEDULE $VENV_PY $SCRIPT >> $LOGFILE 2>&1"
BEGIN_MARK="# --- colafinder-auto BEGIN ---"
END_MARK="# --- colafinder-auto END ---"

ensure_paths() {
  if [[ ! -x "$VENV_PY" ]]; then
    echo "[ERR] $VENV_PY not found or not executable. Activate venv and install deps." >&2
    exit 1
  fi
  if [[ ! -f "$SCRIPT" ]]; then
    echo "[ERR] $SCRIPT not found." >&2
    exit 1
  fi
  touch "$LOGFILE" || true
}

install_job() {
  ensure_paths
  local tmpfile
  tmpfile=$(mktemp)
  if crontab -l >/dev/null 2>&1; then
    crontab -l > "$tmpfile" || true
  else
    : > "$tmpfile"
  fi
  # remove existing block
  sed -i '' "/$BEGIN_MARK/,/$END_MARK/d" "$tmpfile" 2>/dev/null || true
  {
    echo "$BEGIN_MARK"
    echo "$JOB_LINE"
    echo "$END_MARK"
  } >> "$tmpfile"
  crontab "$tmpfile"
  rm -f "$tmpfile"
  echo "[OK] Cron installed: $JOB_LINE"
}

remove_job() {
  local tmpfile
  tmpfile=$(mktemp)
  if ! crontab -l >/dev/null 2>&1; then
    echo "[INFO] No crontab set."
    return 0
  fi
  crontab -l > "$tmpfile"
  sed -i '' "/$BEGIN_MARK/,/$END_MARK/d" "$tmpfile" 2>/dev/null || true
  crontab "$tmpfile"
  rm -f "$tmpfile"
  echo "[OK] Cron removed for colafinder."
}

status_job() {
  local current
  current=$(crontab -l 2>/dev/null || true)
  if echo "$current" | grep -q "$BEGIN_MARK"; then
    echo "[OK] Cron entry present:"
    echo "$current" | sed -n "/$BEGIN_MARK/,/$END_MARK/p"
  else
    echo "[INFO] No colafinder cron entry found."
  fi
}

run_now() {
  ensure_paths
  echo "[INFO] Running once: $VENV_PY $SCRIPT"
  "$VENV_PY" "$SCRIPT"
}

tail_log() {
  tail -n 100 -f "$LOGFILE"
}

usage() {
  echo "Usage: $0 {install|remove|status|run_now|tail}"
}

cmd=${1:-status}
case "$cmd" in
  install) install_job ;;
  remove) remove_job ;;
  status) status_job ;;
  run_now) run_now ;;
  tail) tail_log ;;
  *) usage; exit 1 ;;
esac


