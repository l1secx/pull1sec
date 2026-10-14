#!/usr/bin/env bash
# Start Pull1sec. Override anything with PULL1SEC_* env vars.
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "warning: ffmpeg not found — merging and audio conversion will fail." >&2
fi

if command -v uv >/dev/null 2>&1; then
  exec uv run python -m pull1sec
fi

exec python3 -m pull1sec
