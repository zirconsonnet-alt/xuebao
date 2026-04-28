#!/usr/bin/env sh
set -eu

ROOT="${1:-"$(cd "$(dirname "$0")/.." && pwd)"}"
python3 "$(dirname "$0")/check_layer_imports.py" --root "$ROOT"

