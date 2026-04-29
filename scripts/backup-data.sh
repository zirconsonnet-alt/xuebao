#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

load_env() {
  [ -f "$ENV_FILE" ] || fail ".env not found. Copy .env.example to .env first."
}

resolve_path() {
  case "$1" in
    /*) printf '%s\n' "$1" ;;
    *) printf '%s\n' "${ROOT_DIR}/$1" ;;
  esac
}

copy_if_exists() {
  src="$1"
  dst="$2"
  if [ -e "$src" ]; then
    cp -a "$src" "$dst/"
  fi
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

load_env

DATA_DIR="$(resolve_path "$(read_env_value XUEBAO_DATA_DIR ./data)")"
CACHE_DIR="$(resolve_path "$(read_env_value XUEBAO_CACHE_DIR ./cache)")"
CONFIG_DIR="$(resolve_path "$(read_env_value XUEBAO_CONFIG_DIR ./config)")"
BACKUP_DIR="$(resolve_path "$(read_env_value XUEBAO_BACKUP_DIR ./backups)")"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="${BACKUP_DIR}/${STAMP}"

[ -d "$BACKUP_DIR" ] || mkdir -p "$BACKUP_DIR"
[ ! -e "$DEST" ] || fail "backup destination already exists: $DEST"
mkdir -p "$DEST"

copy_if_exists "$DATA_DIR" "$DEST"
copy_if_exists "$CACHE_DIR" "$DEST"
copy_if_exists "$CONFIG_DIR" "$DEST"

printf 'Backup created: %s\n' "$DEST"
