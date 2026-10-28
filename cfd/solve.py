"""Run simpleFoam or rhoSimpleFoam, with one upwind retry and a Ctrl+C stop."""
import os
import re
import shutil
import signal
import subprocess
import time

from .case import write_schemes
from .proc import die, run, warn


def _latest_time(log_path):
    last = None
    if not os.path.isfile(log_path):
        return None
    for line in open(log_path, errors="replace"):
        match = re.match(r"^Time = (\d+)", line)
        if match:
            last = int(match.group(1))
    return last


def _ended(log_path):
    if not os.path.isfile(log_path):
        return False
    for line in open(log_path, errors="replace"):
        if line.strip() == "End":
            return True
    return False


def _has_time(log_path):
    return _latest_time(log_path) is not None


def _write_now(rundir):
    path = os.path.join(rundir, "system", "controlDict")
    text = open(path).read()
    updated = re.sub(r"(?m)^stopAt\s+.*$", "stopAt          writeNow;", text, count=1)
    with open(path, "w") as handle:
        handle.write(updated)


def clean_solution(rundir):
    for name in os.listdir(rundir):
        path = os.path.join(rundir, name)
        if name.startswith("processor") or name in ("postProcessing", "dynamicCode"):
            shutil.rmtree(path, ignore_errors=True)
        elif name != "0" and name[:1].isdigit() and os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)


def _command(rundir, application, nprocs, mpiflags):
    if nprocs > 1:
        run(["decomposePar", "-force"], rundir, os.path.join(rundir, "log.decomposePar"))
        return ["mpirun", *mpiflags, "-np", str(nprocs), application, "-parallel"]
    return [application]


def _run_once(rundir, cmd, log_path, write_on_exit):
    interrupted = [0]
    holder = {}

    def handler(signum, frame):
        interrupted[0] += 1
        pid = holder.get("pid")
        print()
        if interrupted[0] >= 2:
            print("!! Second interrupt - killing solver now.")
            if pid:
                try:
                    os.killpg(pid, signal.SIGKILL)
                except OSError:
                    pass
            raise SystemExit(130)
        if write_on_exit:
            print("!! Interrupted - solver will write current fields and stop (Ctrl+C again to force quit)...")
            _write_now(rundir)
        else:
            print("!! Interrupted - stopping solver.")
            if pid:
                try:
                    os.killpg(pid, signal.SIGTERM)
                except OSError:
                    pass

    old_int = signal.signal(signal.SIGINT, handler)
    old_term = signal.signal(signal.SIGTERM, handler)
    try:
        with open(log_path, "w") as log:
            child = subprocess.Popen(
                cmd, cwd=rundir, stdout=log, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, start_new_session=True,
            )
        holder["pid"] = child.pid
        last = 0
        while child.poll() is None:
            try:
                time.sleep(1)
            except InterruptedError:
                continue
            iteration = _latest_time(log_path)
            if iteration is not None and iteration >= last + 25:
                print("    iteration %s" % iteration)
                last = iteration
        child.wait()
    finally:
        signal.signal(signal.SIGINT, old_int)
        signal.signal(signal.SIGTERM, old_term)
    return _ended(log_path), interrupted[0]


def solve_case(rundir, application, nprocs, mpiflags, write_on_exit, compressible):
    print("==> Solving with %s on %s core(s)  (log: %s)" % (
        application, nprocs, os.path.join(rundir, "log.%s" % application),
    ))
    if write_on_exit:
        print("    Ctrl+C = stop, write current fields, post-process.  Press twice to force quit.")
    else:
        print("    Ctrl+C = stop the solver and exit, nothing written (use -w to keep results).")
    scheme = "limitedLinear"
    log_path = os.path.join(rundir, "log.%s" % application)
    write_schemes(rundir, "bounded Gauss limitedLinear 1", compressible)
    solved, interrupted = _run_once(rundir, _command(rundir, application, nprocs, mpiflags), log_path, write_on_exit)
    if not solved and interrupted == 0 and _has_time(log_path):
        warn("limitedLinear on k/omega did not finish; retrying once with upwind")
        os.rename(log_path, log_path + ".limitedLinear")
        clean_solution(rundir)
        write_schemes(rundir, "bounded Gauss upwind", compressible)
        scheme = "upwind"
        solved, interrupted = _run_once(
            rundir, _command(rundir, application, nprocs, mpiflags), log_path, write_on_exit,
        )
    if interrupted >= 1 and not write_on_exit:
        print("==> Stopped by user. Nothing written. (Use -w next time to keep results.)")
        raise SystemExit(130)
    if not solved:
        tail = open(log_path, errors="replace").read().splitlines()[-40:]
        if tail:
            print("\n".join(tail))
        die("solver did not finish - see %s" % log_path)
    text = open(log_path, errors="replace").read()
    if interrupted >= 1:
        print("    (stopped early by user - results are from the last completed iteration, NOT converged)")
        stop = "interrupted"
    elif "SIMPLE solution converged" in text:
        print("    (residuals converged)")
        stop = "residuals"
    else:
        print("    (reached max iterations)")
        stop = "iterations"
    return {
        "solved": True,
        "interrupted": interrupted,
        "scheme": scheme,
        "stop": stop,
        "log": log_path,
    }
