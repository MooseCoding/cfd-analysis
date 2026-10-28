"""Run an OpenFOAM command and keep its log."""
import os
import subprocess
import sys


def die(msg):
    print("ERROR: %s" % msg, file=sys.stderr)
    raise SystemExit(1)


def warn(msg):
    print("WARNING: %s" % msg, file=sys.stderr)


def openfoam_source_hint():
    """Shell one-liner for sourcing OpenFOAM (no machine-specific paths)."""
    custom = os.environ.get("OPENFOAM_BASHRC")
    if custom:
        return "source %s" % custom
    wm = os.environ.get("WM_PROJECT_DIR")
    if wm:
        return "source %s/etc/bashrc" % wm
    foam = os.environ.get("FOAM_INST_DIR")
    if foam:
        return "source %s/etc/bashrc" % foam
    return (
        "source /path/to/OpenFOAM-vNNNN/etc/bashrc\n"
        "       # or export OPENFOAM_BASHRC=/path/to/OpenFOAM-vNNNN/etc/bashrc"
    )


def run(cmd, cwd, log_path, check=True):
    print("  > %s" % " ".join(cmd))
    with open(log_path, "w") as log:
        proc = subprocess.run(cmd, cwd=cwd, stdout=log, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        if check:
            tail = open(log_path, errors="replace").read().splitlines()[-30:]
            if tail:
                print("\n".join(tail), file=sys.stderr)
            die("%s failed - see %s" % (cmd[0], log_path))
        return False
    return True
