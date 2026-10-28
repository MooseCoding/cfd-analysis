#!/usr/bin/env bash
# Local guide and API. Builds HTML, then serves it. Does not mesh or solve.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ $# -gt 1 ] || { [ $# -eq 1 ] && [ "$1" != "--build" ]; }; then
  echo "ERROR: usage: ./docs.sh [--build]" >&2
  exit 1
fi
python3 "$ROOT/site/build.py" || exit 1
if [ "${1:-}" = "--build" ]; then
  exit 0
fi
exec python3 -m http.server --bind 127.0.0.1 --directory "$ROOT/site/out" 8765
