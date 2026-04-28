#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

is_placeholder() {
  case "${1:-}" in
    ""|CHANGE_ME*|changeme*|TODO*|todo*|REPLACE_ME*|replace_me*|example|EXAMPLE|placeholder|PLACEHOLDER)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

load_env() {
  [ -f "$ENV_FILE" ] || fail ".env not found. Copy .env.example to .env and fill required values."
}

read_env_value() {
  name="$1"
  default="${2:-}"
  awk -v key="$name" -v default="$default" '
    BEGIN { value = default }
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

require_value() {
  name="$1"
  value="$(read_env_value "$name")"
  if is_placeholder "$value"; then
    fail "$name is missing or still uses a placeholder value."
  fi
}

load_env

require_value ENVIRONMENT
require_value XUEBAO_DATA_DIR
require_value XUEBAO_CONFIG_DIR
require_value XUEBAO_BACKUP_DIR

case "$(read_env_value XUEBAO_BACKUP_ON_DEPLOY true)" in
  true|false) ;;
  *) fail "XUEBAO_BACKUP_ON_DEPLOY must be true or false." ;;
esac

printf 'Deployment environment validation passed.\n'
