#!/usr/bin/env bash
# Plane entry point. Edit config/plane.conf. Flags still override it.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m cfd --config "$ROOT/config/plane.conf" "$@"
