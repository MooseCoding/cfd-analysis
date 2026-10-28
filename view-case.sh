#!/usr/bin/env bash
# Open a run's wall surface in ParaView. summary.json names the file.
# case.foam stays empty on macOS Homebrew ParaView, so this script does not open it.
set -euo pipefail

die() { echo "ERROR: $*" >&2; exit 1; }

RUNDIR=${1:-}
if [ -z "$RUNDIR" ]; then
  echo "Usage: $(basename "$0") path/to/run_<name>" >&2
  exit 1
fi
RUNDIR=$(cd "$RUNDIR" && pwd)
[ -f "$RUNDIR/system/controlDict" ] || [ -f "$RUNDIR/summary.json" ] || die "Not a run directory: $RUNDIR"

surface=""
if [ -f "$RUNDIR/summary.json" ]; then
  surface=$(python3 -c 'import json,sys
data=json.load(open(sys.argv[1]))
print((data.get("files") or {}).get("surface") or "")' "$RUNDIR/summary.json")
fi
if [ -n "$surface" ] && [ -f "$RUNDIR/$surface" ]; then
  command -v paraview >/dev/null 2>&1 || die "paraview not in PATH (brew install paraview)"
  echo "==> ParaView: wall surface (Coloring -> Cp or p)"
  echo "    $RUNDIR/$surface"
  exec paraview "$RUNDIR/$surface"
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$ROOT/lib/openfoam-env.sh"
cfd_try_source_openfoam
command -v paraview >/dev/null 2>&1 || die "paraview not in PATH (brew install paraview)"

cd "$RUNDIR"
if command -v foamToVTK >/dev/null 2>&1; then
  if compgen -G 'processor[0-9]*' >/dev/null && command -v reconstructPar >/dev/null 2>&1; then
    echo "==> reconstructPar -latestTime"
    reconstructPar -latestTime
  fi
  echo "==> foamToVTK -latestTime"
  foamToVTK -latestTime
fi

surface_vtp=""
for name in plane.vtp body.vtp; do
  hit=$(find VTK -path "*/boundary/$name" 2>/dev/null | sort -V | tail -1 || true)
  if [ -n "$hit" ]; then
    surface_vtp=$hit
    break
  fi
done
if [ -z "$surface_vtp" ]; then
  surface_vtp=$(find VTK -path '*/boundary/*.vtp' ! -name 'farfield.vtp' 2>/dev/null | sort -V | tail -1 || true)
fi

[ -n "$surface_vtp" ] && [ -f "$surface_vtp" ] || die "No wall VTK in $RUNDIR. Re-run without --results-only."

echo "==> ParaView: wall surface (Coloring -> Cp or p)"
echo "    $RUNDIR/$surface_vtp"
exec paraview "$surface_vtp"
