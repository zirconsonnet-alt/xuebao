#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

info() {
  printf '%s\n' "$*"
}

compose() {
  docker compose "$@"
}

resolve_path() {
  case "$1" in
    /*) printf '%s\n' "$1" ;;
    *) printf '%s\n' "${ROOT_DIR}/$1" ;;
  esac
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "$1 is required but was not found."
}

read_env_value() {
  name="$1"
  fallback="${2:-}"
  awk -v key="$name" -v fallback="$fallback" '
    BEGIN { value = fallback }
    /^[[:space:]]*#/ || /^[[:space:]]*$/ { next }
    {
      line = $0
      sub(/\r$/, "", line)
      sub(/^[[:space:]]*export[[:space:]]+/, "", line)
      pos = index(line, "=")
      if (pos == 0) next
      name = substr(line, 1, pos - 1)
      val = substr(line, pos + 1)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", name)
      if (name == key) {
        sub(/^[[:space:]]+/, "", val)
        sub(/[[:space:]]+$/, "", val)
        value = val
      }
    }
    END { print value }
  ' "$ENV_FILE"
}

cd "$ROOT_DIR"

[ "$(uname -s)" != "Linux" ] && fail "scripts/deploy.sh is intended for Linux servers."
[ -f "$ENV_FILE" ] || fail ".env not found. Copy .env.example to .env and fill required values."

require_command docker
docker compose version >/dev/null 2>&1 || fail "Docker Compose plugin is required."

scripts/validate-deploy-env.sh

DATA_DIR="$(resolve_path "$(read_env_value XUEBAO_DATA_DIR ./data)")"
CACHE_DIR="$(resolve_path "$(read_env_value XUEBAO_CACHE_DIR ./cache)")"
CONFIG_DIR="$(resolve_path "$(read_env_value XUEBAO_CONFIG_DIR ./config)")"
BACKUP_DIR="$(resolve_path "$(read_env_value XUEBAO_BACKUP_DIR ./backups)")"

mkdir -p "$DATA_DIR" "$CACHE_DIR" "$CONFIG_DIR" "$BACKUP_DIR"

if [ "$(read_env_value XUEBAO_BACKUP_ON_DEPLOY true)" = "true" ]; then
  scripts/backup-data.sh
fi

info "Building bot image..."
compose build bot

info "Starting bot service..."
compose up -d bot

if compose ps --status running bot | grep -q "bot"; then
  info "Deployment succeeded. Inspect status with: docker compose ps"
  info "Inspect logs with: docker compose logs --tail=100 bot"
else
  compose ps bot >&2 || true
  fail "bot service is not running after deployment."
fi
