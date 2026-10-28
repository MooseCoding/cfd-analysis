#!/usr/bin/env bash
# Rocket entry point. Edit config/rocket.conf. Flags still override it.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m cfd --config "$ROOT/config/rocket.conf" "$@"
