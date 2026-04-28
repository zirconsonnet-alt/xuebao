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
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
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

load_env

DATA_DIR="$(resolve_path "${XUEBAO_DATA_DIR:-./data}")"
CACHE_DIR="$(resolve_path "${XUEBAO_CACHE_DIR:-./cache}")"
CONFIG_DIR="$(resolve_path "${XUEBAO_CONFIG_DIR:-./config}")"
BACKUP_DIR="$(resolve_path "${XUEBAO_BACKUP_DIR:-./backups}")"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="${BACKUP_DIR}/${STAMP}"

[ -d "$BACKUP_DIR" ] || mkdir -p "$BACKUP_DIR"
[ ! -e "$DEST" ] || fail "backup destination already exists: $DEST"
mkdir -p "$DEST"

copy_if_exists "$DATA_DIR" "$DEST"
copy_if_exists "$CACHE_DIR" "$DEST"
copy_if_exists "$CONFIG_DIR" "$DEST"

printf 'Backup created: %s\n' "$DEST"
