#!/usr/bin/env bash
# Generic body. Pass -s model.stl, or --config to pick another profile.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m cfd "$@"
