#!/usr/bin/env python3
"""Small walkthrough of the cfd Python API.

Run from the repository root:

    python3 EXAMPLE_PYTHON_API.py
    python3 EXAMPLE_PYTHON_API.py --solve
    python3 EXAMPLE_PYTHON_API.py --read ./plane_cfd

The default path only calls plan(), so OpenFOAM does not need to be sourced.
--solve calls run() and needs simpleFoam on PATH (use ./plane-foam.sh to discover OpenFOAM or Docker).
--read prints summary.json records already on disk, or the wide CSV if that is all the folder has.
"""
import argparse
import sys

import cfd


def show_plan(info):
    ref = info["reference"]
    mesh = info["mesh"]
    print("geometry     %s" % info["geometry"])
    print("Mach         %s" % info["mach"])
    print("Reynolds     %s" % info["reynolds"])
    print("solver       %s  (%s)" % (info["solver"], info["solver_reason"]))
    print("area         %s m^2" % ref["area_m2"])
    print("length       %s m" % ref["length_m"])
    print("moment ctr   %s m" % (ref["moment_center_m"],))
    print("mesh level   %s   est. cells %s" % (mesh["level"], mesh["estimated_cells"]))
    print("run folder   %s" % info["run_dir"])


def plan_builtin_plane(out):
    """Built-in 3 ft plane. Same idea as ./plane-foam.sh --print."""
    cfg = cfd.make_config(
        "config/plane.conf",
        out=out,
        speed=18.0,
        aoa=6.0,
        iters=500,
        print_only=True,
    )
    print("==> plan()  (no OpenFOAM)")
    show_plan(cfd.plan(cfg))
    return cfg


def _row_bits(row):
    """Summary JSON, or a wide CSV row from an older folder."""
    coeffs = row.get("coefficients")
    flight = row.get("flight")
    if isinstance(coeffs, dict):
        flight = flight or {}
        return (
            row.get("geometry"),
            flight.get("aoa_deg"),
            flight.get("speed_m_s"),
            coeffs.get("Cl"),
            coeffs.get("Cd"),
        )
    return (
        row.get("geometry"),
        row.get("AoA_deg"),
        row.get("speed_ms"),
        row.get("Cl"),
        row.get("Cd"),
    )


def solve_one(cfg):
    """Full pipeline. Needs simpleFoam on PATH. The shell wrappers discover OpenFOAM."""
    cfg.print_only = False
    print("==> run()")
    result = cfd.run(cfg)
    print("rundir       %s" % result.rundir)
    print("partial      %s" % result.partial)
    cl = result.coefficients.get("Cl")
    if cl is not None:
        print("Cl           %s" % cl)
        print("Cd           %s" % result.coefficients.get("Cd"))
        print("L/D          %s" % result.coefficients.get("L_over_D"))
    else:
        print("no coefficient row yet (see %s/summary.json)" % result.rundir)
    return result


def read_folder(out):
    """Reload finished runs without solving again."""
    print("==> read_results(%s)" % out)
    rows = cfd.read_results(out)
    if not rows:
        print("no summaries.jsonl or results.csv under %s" % out)
        return
    for row in rows:
        geometry, aoa, speed, cl, cd = _row_bits(row)
        print("  %s  AoA %s deg  V %s m/s  Cl %s  Cd %s" % (geometry, aoa, speed, cl, cd))

    runs = cfd.list_runs(out)
    if not runs:
        return
    latest = cfd.read_run(runs[-1])
    print("==> latest run")
    print("  %s" % latest.rundir)
    print("  status %s" % latest.row.get("status", ""))
    print("  Mach %s  Re %s" % (latest.get("mach", latest.get("MACH")), latest.get("reynolds", latest.get("RE"))))
    print("  Cl %s" % latest.coefficients.get("Cl", ""))


def sweep_preview():
    """How a parametric study is set up. This only builds configs; it does not solve."""
    print("==> AoA sweep")
    print("  cfd.sweep(cfg, [0, 2, 4, 6]) reuses one mesh and writes polar.csv plus polar.svg")
    print("  each run folder also gets history.csv and history.svg")
    for aoa in (0.0, 2.0, 4.0, 6.0):
        cfg = cfd.make_config("config/plane.conf", out="./sweep_cfd", aoa=aoa, speed=20.0)
        print("  aoa %s deg  speed %s m/s  out %s" % (cfg.aoa, cfg.speed, cfg.out))


def from_cli_flags():
    """Same flags as python3 -m cfd / ./plane-foam.sh."""
    cfg = cfd.resolve(["--config", "config/rocket.conf", "-v", "30", "-a", "0", "--print"])
    print("==> resolve() from CLI-style argv")
    print("  profile %s  aoa %s  speed %s  print_only %s" % (
        cfg.profile, cfg.aoa, cfg.speed, cfg.print_only,
    ))


def main(argv):
    parser = argparse.ArgumentParser(description="Example of the cfd package API")
    parser.add_argument("--solve", action="store_true", help="mesh and solve (needs OpenFOAM)")
    parser.add_argument("--read", metavar="DIR", help="print results already written under DIR")
    parser.add_argument("--out", default="./example_cfd", help="output folder for the plan/solve example")
    args = parser.parse_args(argv)

    if args.read:
        read_folder(args.read)
        return 0

    from_cli_flags()
    print()
    sweep_preview()
    print()
    cfg = plan_builtin_plane(args.out)
    if args.solve:
        print()
        solve_one(cfg)
        print()
        read_folder(args.out)
    else:
        print()
        print("plan only. ./plane-foam.sh --smoke finds OpenFOAM or Docker. --solve here needs simpleFoam on PATH.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
