"""Find a local OpenFOAM install, or re-exec inside the official Docker image.

``plan()``, ``--print``, ``--polar``, and the unit tests never call :func:`ensure_openfoam`.
``--polar`` together with ``--aoas`` still launches OpenFOAM, because that sweep solves.
"""
import glob
import os
import shutil
import subprocess
import sys

from .config import PACKAGE_ROOT, _FIELDS
from .proc import die

FOAM_IMAGE = os.environ.get("CFD_FOAM_IMAGE", "opencfd/openfoam-run:2512")
READY = "CFD_FOAM_READY"

# Config keys whose values are host paths and must be rewritten inside Docker.
_PATH_ENV = ("STL", "OUT")
_PATH_FLAGS = ("--config", "-s")

SWEEP_FLAGS = ("--aoas", "--yaws", "--speeds")

def skip_launch(argv):
    """True when this invocation must not source OpenFOAM or start Docker."""
    tokens = list(argv)
    for token in tokens:
        if token in ("--print", "-h", "--help"):
            return True
    sweeping = any(token.split("=", 1)[0] in SWEEP_FLAGS for token in tokens)
    if "--polar" in tokens and not sweeping:
        return True
    return False


def launch_mode(argv, ready, foam_on_path, have_bashrc, have_docker):
    """Return ``run``, ``bash``, ``docker``, or ``missing``."""
    if ready or skip_launch(argv) or foam_on_path:
        return "run"
    if have_bashrc:
        return "bash"
    if have_docker:
        return "docker"
    return "missing"


def bashrc_candidates():
    """Local ``etc/bashrc`` files, newest match first within each location."""
    found = []

    def add(path):
        if not path:
            return
        path = os.path.abspath(os.path.expanduser(path))
        if os.path.isfile(path) and path not in found:
            found.append(path)

    custom = os.environ.get("OPENFOAM_BASHRC", "")
    if custom:
        add(custom)
    wm = os.environ.get("WM_PROJECT_DIR", "")
    if wm:
        add(os.path.join(wm, "etc", "bashrc"))
    foam_inst = os.environ.get("FOAM_INST_DIR", "")
    if foam_inst:
        add(os.path.join(foam_inst, "etc", "bashrc"))
    home = os.path.expanduser("~")
    patterns = [
        "/Volumes/OpenFOAM-*/etc/bashrc",
        os.path.join(home, "OpenFOAM", "*", "etc", "bashrc"),
        "/opt/openfoam*/etc/bashrc",
        "/usr/lib/openfoam/*/etc/bashrc",
    ]
    for pattern in patterns:
        for path in sorted(glob.glob(pattern), reverse=True):
            add(path)
    return found


def bashrc_provides_solver(path):
    """True when sourcing ``path`` puts ``simpleFoam`` on ``PATH``."""
    script = 'set +u; . "$1" >/dev/null 2>&1; command -v simpleFoam'
    try:
        proc = subprocess.run(
            ["bash", "-c", script, "cfd", path],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0 and bool(proc.stdout.strip())


def _within(path, root):
    path = os.path.abspath(path)
    root = os.path.abspath(root)
    return path == root or path.startswith(root + os.sep)


def _guest(path, mounts):
    path = os.path.abspath(path)
    best = None
    for host, guest in mounts:
        host = os.path.abspath(host)
        if path == host or path.startswith(host + os.sep):
            if best is None or len(host) > len(best[0]):
                best = (host, guest)
    if best is None:
        return None
    rel = os.path.relpath(path, best[0])
    if rel == ".":
        return best[1]
    return best[1].rstrip("/") + "/" + rel.replace(os.sep, "/")


def _mount_for(path, mounts):
    """Return the container path, adding a mount for a host file outside the repo."""
    path = os.path.abspath(path)
    guest = _guest(path, mounts)
    if guest:
        return guest
    directory = path if os.path.isdir(path) else os.path.dirname(path)
    if not directory or directory == os.path.abspath(os.sep):
        return path
    guest_dir = _guest(directory, mounts)
    if guest_dir:
        return _guest(path, mounts)
    slot = sum(1 for _, dest in mounts if dest.startswith("/mnt/"))
    mounts.append((directory, "/mnt/%d" % slot))
    return _guest(path, mounts)


def _translate_argv(argv, cwd, mounts):
    out = []
    expect_path = False
    for token in argv:
        if expect_path:
            path = token if os.path.isabs(token) else os.path.abspath(os.path.join(cwd, token))
            out.append(_mount_for(path, mounts))
            expect_path = False
            continue
        if token in _PATH_FLAGS:
            expect_path = True
            out.append(token)
            continue
        if os.path.isabs(token) and (os.path.exists(token) or os.path.exists(os.path.dirname(token))):
            out.append(_mount_for(token, mounts))
            continue
        out.append(token)
    return out


def _translate_env(environ, mounts):
    exported = {}
    for key in _FIELDS:
        raw = environ.get(key, "")
        if raw == "":
            continue
        if key in _PATH_ENV and os.path.isabs(raw):
            raw = _mount_for(raw, mounts)
        exported[key] = raw
    return exported


def docker_command(argv, environ, cwd, repo_root, uid=None, gid=None, image=None):
    """``docker run`` argv that re-executes this CLI inside OpenFOAM.

    The repo is mounted at ``/work``. The container workdir is the user's cwd
    when that cwd lives in the repo, and ``/data`` otherwise. ``--config`` and
    ``-s`` paths, plus absolute ``STL`` and ``OUT``, are rewritten to those mounts.
    """
    repo_root = os.path.abspath(repo_root)
    cwd = os.path.abspath(cwd)
    mounts = [(repo_root, "/work")]
    if _within(cwd, repo_root):
        work = _guest(cwd, mounts)
    else:
        mounts.append((cwd, "/data"))
        work = "/data"
    new_argv = _translate_argv(list(argv), cwd, mounts)
    new_env = _translate_env(environ, mounts)
    cmd = ["docker", "run", "--rm"]
    if uid is not None and gid is not None:
        cmd.extend(["-u", "%s:%s" % (uid, gid), "-e", "HOME=/tmp"])
    for host, guest in mounts:
        cmd.extend(["-v", "%s:%s" % (host, guest)])
    cmd.extend(["-w", work, "-e", "%s=1" % READY, "-e", "PYTHONPATH=/work"])
    for key in sorted(new_env):
        cmd.extend(["-e", "%s=%s" % (key, new_env[key])])
    cmd.append(image or FOAM_IMAGE)
    cmd.extend(["python3", "-m", "cfd"])
    cmd.extend(new_argv)
    return cmd


def _exec_bash(rc, argv):
    print("==> Sourcing OpenFOAM (%s)" % rc)
    sys.stdout.flush()
    os.execvp("bash", [
        "bash", "-c",
        'set +u; . "$1"; export %s=1; exec "$2" -m cfd "${@:3}"' % READY,
        "cfd-launch",
        rc,
        sys.executable,
    ] + list(argv))


def _exec_docker(argv):
    uid = os.getuid() if hasattr(os, "getuid") else None
    gid = os.getgid() if hasattr(os, "getgid") else None
    cmd = docker_command(argv, os.environ, os.getcwd(), PACKAGE_ROOT, uid, gid)
    print("==> OpenFOAM is not on PATH. Running in %s" % FOAM_IMAGE)
    sys.stdout.flush()
    os.execvp("docker", cmd)


def missing_openfoam_message():
    return (
        "OpenFOAM is not on PATH, and Docker is not available.\n"
        "       Install OpenFOAM.com v2512 and source its etc/bashrc,\n"
        "       or install Docker and re-run. Docker uses %s." % FOAM_IMAGE
    )


def ensure_openfoam(argv=None):
    """Re-exec with OpenFOAM available. No-op when it is already on ``PATH``."""
    if argv is None:
        argv = sys.argv[1:]
    argv = list(argv)
    ready = os.environ.get(READY) == "1"
    foam_on_path = shutil.which("simpleFoam") is not None
    rc_path = None
    if not ready and not skip_launch(argv) and not foam_on_path:
        for path in bashrc_candidates():
            if bashrc_provides_solver(path):
                rc_path = path
                break
    mode = launch_mode(argv, ready, foam_on_path, rc_path is not None, shutil.which("docker") is not None)
    if mode == "run":
        return
    if mode == "bash":
        _exec_bash(rc_path, argv)
    if mode == "docker":
        _exec_docker(argv)
    die(missing_openfoam_message())
