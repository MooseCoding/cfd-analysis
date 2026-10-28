# Source OpenFOAM into the current shell when solver tools are not already on PATH.
# Set OPENFOAM_BASHRC to your install's etc/bashrc, or source OpenFOAM yourself first.
cfd_try_source_openfoam() {
  command -v reconstructPar >/dev/null 2>&1 && return 0
  local rc=""
  if [ -n "${OPENFOAM_BASHRC:-}" ] && [ -f "$OPENFOAM_BASHRC" ]; then
    rc="$OPENFOAM_BASHRC"
  elif [ -n "${WM_PROJECT_DIR:-}" ] && [ -f "${WM_PROJECT_DIR}/etc/bashrc" ]; then
    rc="${WM_PROJECT_DIR}/etc/bashrc"
  elif [ -n "${FOAM_INST_DIR:-}" ] && [ -f "${FOAM_INST_DIR}/etc/bashrc" ]; then
    rc="${FOAM_INST_DIR}/etc/bashrc"
  else
    local found
    shopt -s nullglob
    for found in /Volumes/OpenFOAM-*/etc/bashrc; do
      rc="$found"
      break
    done
    shopt -u nullglob
  fi
  if [ -n "$rc" ] && [ -f "$rc" ]; then
    set +u
    # shellcheck disable=SC1090
    . "$rc"
    set -u
  fi
}
