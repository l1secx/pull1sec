#!/usr/bin/env bash
# Start Pull1sec from a source checkout. Override anything with PULL1SEC_* env vars.
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "warning: ffmpeg not found — merging and audio conversion will fail." >&2
fi

if command -v uv >/dev/null 2>&1; then
  exec uv run python -m pull1sec "$@"
fi

if python3 -c 'import fastapi, uvicorn, yt_dlp' >/dev/null 2>&1; then
  exec python3 -m pull1sec "$@"
fi

cat >&2 <<'MSG'
error: dependencies are not installed in this Python, and uv is missing.

Install one of them first:
  uv sync                      # recommended
  python3 -m venv .venv && .venv/bin/pip install -e .

Or install the packaged app:
  npm install -g pull1sec
  curl -fsSL https://raw.githubusercontent.com/l1secx/pull1sec/main/install.sh | bash
MSG
exit 1
