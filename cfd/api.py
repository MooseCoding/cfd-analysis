"""Programmatic API: configure runs, execute the pipeline, read results."""
import csv
import glob
import hashlib
import json
import os
import shutil

from .aero import choose_solver, freestream, isa, mach_note, solver_name, turbulence
from .case import prune_for_results_only, write_case
from .config import from_mapping
from .geom import estimate_cells, make, make_rocket, prepare
from .mesh import build_mesh
from .proc import die, openfoam_source_hint, run as run_cmd, warn
from .report import drop_volume_vtk, find_surface_vtp, load_meta, report, write_polar, yplus_cmd
from .solve import solve_case


def token(value):
    number = float(value)
    if abs(number - round(number)) < 1e-9 and abs(number) < 1e12:
        return str(int(round(number)))
    return "%.6g" % number


class RunResult(object):
    """Outcome of :func:`run` or :func:`read_run`."""

    __slots__ = (
        "rundir", "meshdir", "out_dir", "geometry", "partial", "meta", "row", "solve",
    )

    def __init__(
        self, rundir=None, meshdir=None, out_dir=None, geometry=None, partial=False,
        meta=None, row=None, solve=None,
    ):
        self.rundir = rundir
        self.meshdir = meshdir
        self.out_dir = out_dir
        self.geometry = geometry
        self.partial = partial
        self.meta = meta or {}
        self.row = row or {}
        self.solve = solve or {}

    @property
    def coefficients(self):
        nested = self.row.get("coefficients") if isinstance(self.row, dict) else None
        if isinstance(nested, dict):
            return nested
        return self.row

    def get(self, key, default=None):
        if isinstance(self.row, dict):
            if key in self.row and self.row[key] not in ("", None):
                return self.row[key]
            for nest in ("coefficients", "flight", "quality", "rocket"):
                block = self.row.get(nest)
                if isinstance(block, dict) and key in block and block[key] is not None:
                    return block[key]
        return self.meta.get(key, default)


def make_config(config_path=None, environ=None, **overrides):
    """Build a run configuration (same fields as the CLI / ``KEY=value`` files).

    Pass overrides as keywords, e.g. ``speed=25``, ``aoa=2``, ``iters=3000``,
    or ``max_iterations=3000`` (alias for ``iters``). Read back ``cfg.iters`` or
    ``cfg.max_iterations`` before calling :func:`run`.
    """
    return from_mapping(config_path, environ, **overrides)


def read_csv(path):
    """Parse ``results.csv`` or ``results_partial.csv`` into a list of row dicts."""
    if not os.path.isfile(path):
        return []
    with open(path, newline="", errors="replace") as handle:
        return list(csv.DictReader(handle))


def read_summaries(path):
    """Parse ``summaries.jsonl`` into a list of summary dicts."""
    if not os.path.isfile(path):
        return []
    rows = []
    with open(path, errors="replace") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            rows.append(json.loads(text))
    return rows


def read_results(out_dir, include_partial=True):
    """Summaries from ``summaries.jsonl``, or the wide CSV when that file is absent.

    JSON records use numbers and ``null``. CSV fallback rows stay strings.
    """
    out_dir = os.path.abspath(out_dir)
    summary_path = os.path.join(out_dir, "summaries.jsonl")
    if os.path.isfile(summary_path):
        rows = read_summaries(summary_path)
        if not include_partial:
            rows = [row for row in rows if row.get("status") != "partial"]
        return rows
    rows = read_csv(os.path.join(out_dir, "results.csv"))
    if include_partial:
        rows.extend(read_csv(os.path.join(out_dir, "results_partial.csv")))
    return rows


def list_runs(out_dir):
    """Run case directories under ``out_dir``, oldest first."""
    out_dir = os.path.abspath(out_dir)
    if not os.path.isdir(out_dir):
        return []
    paths = []
    for name in os.listdir(out_dir):
        if not name.startswith("run_"):
            continue
        path = os.path.join(out_dir, name)
        if os.path.isdir(path):
            paths.append(path)
    paths.sort(key=lambda p: os.path.getmtime(p))
    return paths


def read_run(rundir):
    """Load one run folder: ``summary.json`` when present, otherwise the wide CSV row."""
    rundir = os.path.abspath(rundir)
    meta_path = os.path.join(rundir, "case_meta.env")
    meta = load_meta(meta_path) if os.path.isfile(meta_path) else {}
    summary_path = os.path.join(rundir, "summary.json")
    if os.path.isfile(summary_path):
        with open(summary_path, errors="replace") as handle:
            row = json.load(handle)
        partial = row.get("status") == "partial" or meta.get("PARTIAL", "0") == "1"
        geometry = row.get("geometry") or meta.get("GEOMETRY")
    else:
        rows = read_csv(os.path.join(rundir, "results.csv"))
        row = rows[-1] if rows else {}
        partial = meta.get("PARTIAL", "0") == "1" or row.get("converged") == "partial"
        geometry = meta.get("GEOMETRY")
    out_dir = os.path.dirname(rundir)
    return RunResult(
        rundir=rundir,
        out_dir=out_dir,
        geometry=geometry,
        partial=partial,
        meta=meta,
        row=row,
    )


def _need(commands):
    missing = [name for name in commands if shutil.which(name) is None]
    if missing:
        die(
            "'%s' not found. Source your OpenFOAM environment first, e.g.\n"
            "       %s" % (missing[0], openfoam_source_hint())
        )


def _procs(nprocs):
    if nprocs <= 1:
        return 1, []
    if shutil.which("mpirun") is None:
        warn("mpirun not found - running serial")
        return 1, []
    flags = ["--allow-run-as-root"] if hasattr(os, "geteuid") and os.geteuid() == 0 else []
    return int(nprocs), flags


def _geometry(cfg):
    os.makedirs(cfg.out, exist_ok=True)
    if cfg.stl:
        if not os.path.isfile(cfg.stl):
            die("STL not found: %s" % cfg.stl)
        name = os.path.splitext(os.path.basename(cfg.stl))[0]
        source = cfg.stl
        folder = os.path.join(cfg.out, "geom_%s" % name)
        os.makedirs(folder, exist_ok=True)
    elif cfg.profile == "plane":
        name = "builtin%sft" % token(cfg.span_ft)
        folder = os.path.join(cfg.out, "geom_%s" % name)
        os.makedirs(folder, exist_ok=True)
        source = os.path.join(folder, "builtin.stl")
        print("==> Building the %s ft plane" % token(cfg.span_ft))
        make(source, cfg.span_ft)
    elif cfg.profile == "rocket":
        folder = os.path.join(cfg.out, "geom_rocket_tmp")
        if os.path.isdir(folder):
            shutil.rmtree(folder)
        os.makedirs(folder)
        source = os.path.join(folder, "builtin.stl")
        print("==> Building the example rocket (%.0f mm diameter)" % (cfg.body_d * 1000.0))
        make_rocket(
            source, cfg.body_d, cfg.body_l, cfg.nose_l, cfg.nose, cfg.fin_count,
            cfg.fin_root, cfg.fin_tip, cfg.fin_span, cfg.fin_sweep, cfg.fin_x,
        )
        digest = hashlib.sha1(open(source, "rb").read()).hexdigest()[:8]
        name = "rocket_%s" % digest
        final = os.path.join(cfg.out, "geom_%s" % name)
        if os.path.isdir(final):
            shutil.rmtree(final)
        os.rename(folder, final)
        folder = final
        source = os.path.join(folder, "builtin.stl")
    else:
        die("profile body needs an STL (-s FILE)")
    return name, folder, source


def _apply_overrides(cfg, setup):
    overridden = False
    if cfg.ref_area is not None:
        setup["ref_area"] = cfg.ref_area
        overridden = True
    if cfg.ref_length is not None:
        setup["ref_chord"] = cfg.ref_length
        overridden = True
    if cfg.ref_x is not None:
        setup["ref_x"] = cfg.ref_x
        setup["cg_default"] = False
        overridden = True
    if cfg.ref_y is not None:
        setup["ref_y"] = cfg.ref_y
        overridden = True
    if cfg.ref_z is not None:
        setup["ref_z"] = cfg.ref_z
        overridden = True
    return overridden


def _paths(cfg, name, setup):
    mesh_yaw = getattr(cfg, "mesh_yaw", None)
    if mesh_yaw is None:
        mesh_yaw = abs(cfg.yaw)
    mesh_name = "mesh_%s_lvl%s_lay%s" % (name, token(setup["lvl"]), token(cfg.layers))
    if mesh_yaw:
        mesh_name += "_yaw%s" % token(mesh_yaw)
    meshdir = os.path.join(cfg.out, mesh_name)
    run_name = "run_%s_lvl%s_aoa%s" % (name, token(setup["lvl"]), token(cfg.aoa))
    if float(cfg.yaw) != 0:
        run_name += "_yaw%s" % token(cfg.yaw)
    run_name += "_v%s" % token(cfg.speed)
    if float(cfg.alt_m) != 0:
        run_name += "_h%s" % token(cfg.alt_m)
    return meshdir, os.path.join(cfg.out, run_name)


def _solver_reason(kind, mach, transonic):
    if kind == "simple":
        return "incompressible, Mach %.4f <= 0.3" % mach
    if transonic:
        return "compressible, transonic on, Mach %.4f" % mach
    return "compressible, Mach %.4f" % mach

def _mesh_yaw(cfg):
    value = getattr(cfg, "mesh_yaw", None)
    return abs(cfg.yaw) if value is None else value

def plan(cfg):
    """Geometry, reference, and solver choice without calling OpenFOAM."""
    atm = isa(cfg.alt_m)
    mach = round(cfg.speed / atm["a"], 4)
    try:
        kind, transonic = choose_solver(mach, cfg.solver)
    except ValueError as exc:
        die(str(exc))
    note = mach_note(mach)
    if note:
        warn(note)
    if cfg.profile == "body" and not cfg.stl:
        die("profile body needs an STL (-s FILE)")
    name, folder, source = _geometry(cfg)
    target = cfg.target_size_m
    if cfg.profile == "rocket" and not target:
        target = cfg.nose_l + cfg.body_l
    setup = prepare(
        source, os.path.join(folder, "body.stl"), cfg.units or "auto", cfg.quality or "auto", 
        cfg.speed, atm["nu"], cfg.layers, cfg.cellcap, cfg.ref_length or "",
        profile=cfg.profile, target_size_m=target, target_yplus=cfg.target_yplus, max_yaw=_mesh_yaw(cfg),
    )
    overridden = _apply_overrides(cfg, setup)
    if setup["ref_chord"] <= 0 or setup["ref_area"] <= 0:
        die("reference length and area must be positive. Pass -A and -C.")
    re_num = int(round(cfg.speed * setup["ref_chord"] / atm["nu"]))
    k_inf, w_inf, _ = turbulence(cfg.speed, setup["ref_chord"], cfg.turb_int)
    meshdir, rundir = _paths(cfg, name, setup)
    return {
        "profile": cfg.profile,
        "geometry": name,
        "geom_dir": folder,
        "mesh_dir": meshdir,
        "run_dir": rundir,
        "out_dir": cfg.out,
        "aoa_deg": cfg.aoa,
        "yaw_deg": cfg.yaw,
        "speed_ms": cfg.speed,
        "alt_m": cfg.alt_m,
        "mach": mach,
        "reynolds": re_num,
        "solver_kind": kind,
        "solver": solver_name(kind),
        "transonic": transonic,
        "solver_reason": _solver_reason(kind, mach, transonic),
        "iters": cfg.iters,
        "max_iterations": cfg.iters,
        "max_compute": cfg.max_compute or "",
        "cellcap": cfg.cellcap,
        "nprocs": cfg.nprocs,
        "atmosphere": dict(atm),
        "reference": {
            "area_m2": setup["ref_area"],
            "length_m": setup["ref_chord"],
            "moment_center_m": (setup["ref_x"], setup["ref_y"], setup["ref_z"]),
            "source": setup["ref_source"],
            "overridden": overridden,
            "diameter_m": setup["diameter"],
        },
        "mesh": {
            "level": setup["lvl"],
            "surface_dx_m": setup["surf_dx"],
            "predicted_yplus": setup["pred_yplus"],
            "target_yplus": setup["target_yplus"],
            "estimated_cells": setup["cell_est"],
            "cell_cap_hit": setup["cap_hit"],
        },
        "turbulence": {"intensity": cfg.turb_int, "k": k_inf, "omega": w_inf},
        "setup": setup,
    }


def _describe(cfg, setup, atm, mach, re_num, kind, transonic, overridden):
    application = solver_name(kind)
    why = _solver_reason(kind, mach, transonic)
    print("==> Flight condition")
    print("    profile %s,  AoA %s deg,  yaw %s deg,  V %s m/s,  altitude %s m" % (
        cfg.profile, token(cfg.aoa), token(cfg.yaw), token(cfg.speed), token(cfg.alt_m),
    ))
    print("    Mach %s,  Re %s,  solver %s (%s)" % (mach, re_num, application, why))
    note = mach_note(mach)
    if note:
        warn(note)
    print("    max iterations %s  (-i N, or ITERS= in config)" % token(cfg.iters))
    compute = cfg.max_compute or "default"
    print("    max compute %s,  MPI ranks %s  (--max-compute, MAX_COMPUTE=, -n, NPROCS=)" % (
        compute, token(cfg.nprocs),
    ))
    print("    air: rho %.6g kg/m^3,  nu %.6g m^2/s,  T %.2f K,  p %.1f Pa" % (
        atm["rho"], atm["nu"], atm["T"], atm["p"],
    ))
    print("==> Reference (%s)" % setup["ref_source"])
    print("    units %s (x%s), dropped %s degenerate triangles" % (
        setup["scale_name"], setup["scale_factor"], setup["dropped"],
    ))
    if cfg.profile == "plane":
        print("    bins  wing %s, fuselage %s, tail %s" % (
            setup["wing_bins"], setup["fuse_bins"], setup["tail_bins"],
        ))
        print("    area %s m^2,  MAC %s m,  moment center (%s %s %s) m" % (
            setup["ref_area"], setup["ref_chord"], setup["ref_x"], setup["ref_y"], setup["ref_z"],
        ))
    elif cfg.profile == "rocket":
        print("    Aref %s m^2,  D %s m,  Lref %s m,  moment center (%s %s %s) m" % (
            setup["ref_area"], setup["diameter"], setup["ref_chord"],
            setup["ref_x"], setup["ref_y"], setup["ref_z"],
        ))
        if setup["cg_default"]:
            print("    moment center is mid-length. Set REF_X to the real CG before trusting static margin.")
    else:
        print("    frontal area %s m^2,  length %s m,  moment center (%s %s %s) m" % (
            setup["ref_area"], setup["ref_chord"], setup["ref_x"], setup["ref_y"], setup["ref_z"],
        ))
    if overridden:
        print("    an override replaced at least one of area, length, or moment center")
        print("    STL estimate was area %s m^2, Lref %s m, x %s m" % (
            setup["computed_area"], setup["computed_chord"], setup["computed_x"],
        ))
    if setup["ref_source"] == "fallback-projection":
        warn("wing could not be separated from the STL. Pass -A -C -X if you know the wing.")
    print("==> Mesh sizing")
    print("    target y+ %s,  predicted y+ %.4g,  surface %s m,  level %s" % (
        setup["target_yplus"], setup["pred_yplus"], setup["surf_dx"], setup["lvl"],
    ))
    print("    estimated cells %s (cap %s)" % (setup["cell_est"], token(setup["cellcap"])))
    if setup["cap_hit"]:
        print("    the cell cap is binding, so the wall spacing is coarser than the y+ target")


def _meta(path, cfg, setup, atm, flow, mach, re_num, kind, result, meshdir, rundir, overridden, partial, lvl_first, yp_retried, yp, geometry):
    length_name = {"plane": "Re_MAC", "rocket": "Re_D", "body": "Re_L"}[cfg.profile]
    rows = [
        ("PROFILE", cfg.profile),
        ("SOLVER", kind),
        ("SOLVER_NAME", solver_name(kind)),
        ("COMPRESSIBLE", 1 if kind == "rho" else 0),
        ("AOA", cfg.aoa),
        ("YAW", cfg.yaw),  
        ("SPEED", cfg.speed),
        ("ALT_M", cfg.alt_m),
        ("RHO", atm["rho"]),
        ("NU", atm["nu"]),
        ("MACH", mach),
        ("RE", re_num),
        ("RE_LABEL", length_name),
        ("REF_AREA", setup["ref_area"]),
        ("REF_CHORD", setup["ref_chord"]),
        ("REF_XCG", setup["ref_x"]),
        ("REF_YCG", setup["ref_y"]),
        ("REF_ZCG", setup["ref_z"]),
        ("REF_DIAMETER", "" if setup["diameter"] is None else setup["diameter"]),
        ("REF_SOURCE", setup["ref_source"]),
        ("REF_OVERRIDE", 1 if overridden else 0),
        ("CG_DEFAULT", 1 if setup["cg_default"] else 0),
        ("COMPUTED_AREA", setup["computed_area"]),
        ("COMPUTED_CHORD", setup["computed_chord"]),
        ("COMPUTED_XCG", setup["computed_x"]),
        ("TURB_INT", cfg.turb_int),
        ("K_INF", flow["k"]),
        ("W_INF", flow["omega"]),
        ("LVL", setup["lvl"]),
        ("LVL_FIRST", lvl_first),
        ("SURF_DX", setup["surf_dx"]),
        ("LAYERS", cfg.layers),
        ("CELL_EST", setup["cell_est"]),
        ("CAP_HIT", setup["cap_hit"]),
        ("TARGET_YPLUS", setup["target_yplus"]),
        ("PRED_YPLUS", setup["pred_yplus"]),
        ("YP_RETRIED", yp_retried),
        ("YP_PASS", yp.get("YP_PASS", 0)),
        ("SCHEME", result["scheme"]),
        ("STOP", result["stop"]),
        ("PARTIAL", partial),
        ("GEOMETRY", geometry),
        ("LIFT_X", flow["lift"][0]),
        ("LIFT_Y", flow["lift"][1]),
        ("LIFT_Z", flow["lift"][2]),
        ("DRAG_X", flow["drag"][0]),
        ("DRAG_Y", flow["drag"][1]),
        ("DRAG_Z", flow["drag"][2]),
        ("ITERS", cfg.iters),
        ("REPORT_SCATTER", 1 if cfg.report_scatter else 0),
        ("RESULTS_ONLY", 1 if cfg.results_only else 0),
        ("VOLUME", 1 if cfg.volume else 0),
        ("P_TOL", "1e-5"),
        ("U_TOL", "1e-6"),
        ("K_TOL", "1e-6"),
        ("LOG", result["log"]),
        ("CHECKMESH", os.path.join(meshdir, "log.checkMesh")),
    ]
    with open(path, "w") as handle:
        for key, value in rows:
            handle.write("%s=%s\n" % (key, value))


def _shift_level(setup, new_level, nu):
    setup["lvl"] = new_level
    setup["l1"] = max(new_level - 1, 1)
    setup["l2"] = max(new_level - 2, 1)
    setup["surf_dx"] = setup["dx"] / (2 ** new_level)
    setup["pred_yplus"] = (setup["surf_dx"] / 2.0) * setup["utau"] / nu
    setup["cell_est"] = estimate_cells(setup["nx"], setup["ny"], setup["nz"], new_level)


def run(cfg):
    """Mesh, solve, post-process, and report. Returns a :class:`RunResult`."""
    atm = isa(cfg.alt_m)
    mach = round(cfg.speed / atm["a"], 4)
    try:
        kind, transonic = choose_solver(mach, cfg.solver)
    except ValueError as exc:
        die(str(exc))
    if cfg.profile == "body" and not cfg.stl:
        die("profile body needs an STL (-s FILE)")
    name, folder, source = _geometry(cfg)
    target = cfg.target_size_m
    if cfg.profile == "rocket" and not target:
        target = cfg.nose_l + cfg.body_l
    print("==> Reading the surface and computing the reference")
    setup = prepare(
        source, os.path.join(folder, "body.stl"), cfg.units or "auto", cfg.quality or "auto",
        cfg.speed, atm["nu"], cfg.layers, cfg.cellcap, cfg.ref_length or "",
        profile=cfg.profile, target_size_m=target, target_yplus=cfg.target_yplus,
    )
    overridden = _apply_overrides(cfg, setup)
    if setup["ref_chord"] <= 0 or setup["ref_area"] <= 0:
        die("reference length and area must be positive. Pass -A and -C.")
    re_num = int(round(cfg.speed * setup["ref_chord"] / atm["nu"]))
    _describe(cfg, setup, atm, mach, re_num, kind, transonic, overridden)
    k_inf, w_inf, nut_inf = turbulence(cfg.speed, setup["ref_chord"], cfg.turb_int)
    flow = freestream(cfg.speed, cfg.aoa, cfg.yaw)
    flow.update(k=k_inf, omega=w_inf, nut=nut_inf)
    print("    turbulence: Tu %s,  k %.6g,  omega %.6g" % (cfg.turb_int, k_inf, w_inf))
    if cfg.print_only:
        return RunResult(
            rundir=_paths(cfg, name, setup)[1],
            meshdir=_paths(cfg, name, setup)[0],
            out_dir=cfg.out,
            geometry=name,
            partial=False,
            meta={"MACH": mach, "RE": re_num, "GEOMETRY": name},
        )

    need = ["blockMesh", "snappyHexMesh", "checkMesh", solver_name(kind)]
    if not cfg.results_only:
        need.append("foamToVTK")
    _need(need)
    nprocs, mpiflags = _procs(cfg.nprocs)
    lvl_first = setup["lvl"]
    yp_retried = 0
    attempt = 0
    result = None
    meshdir = rundir = None
    yp = {"YP_PASS": 0, "YP_REASON": "no-data", "NEW_LVL": setup["lvl"]}
    while True:
        meshdir, rundir = _paths(cfg, name, setup)
        build_mesh(meshdir, os.path.join(folder, "body.stl"), setup, cfg.layers, cfg.remesh)
        cfg.remesh = False
        write_case(rundir, meshdir, cfg, setup, flow, atm, kind, transonic, nprocs)
        result = solve_case(
            rundir, solver_name(kind), nprocs, mpiflags, cfg.write_on_exit, kind == "rho",
        )
        if result["interrupted"] == 0:
            yp = yplus_cmd(rundir, setup["lvl"], setup["max_lvl"], cfg.layers)
        if (
            attempt == 0 and setup["quality_used"] == "auto" and cfg.layers == 0
            and result["interrupted"] == 0 and yp["YP_REASON"] == "shift"
            and yp["NEW_LVL"] != setup["lvl"]
        ):
            print("==> y+ is outside the wall-function band (avg %s, min %s, max %s)" % (
                yp["YP_AVG"], yp["YP_MIN"], yp["YP_MAX"],
            ))
            print("    remeshing once at level %s (was %s)" % (yp["NEW_LVL"], setup["lvl"]))
            _shift_level(setup, yp["NEW_LVL"], atm["nu"])
            yp_retried = 1
            attempt = 1
            continue
        break

    print("==> Post-processing")
    if nprocs > 1:
        run_cmd(["reconstructPar", "-latestTime"], rundir, os.path.join(rundir, "log.reconstructPar"))
        for entry in os.listdir(rundir):
            if entry.startswith("processor"):
                shutil.rmtree(os.path.join(rundir, entry), ignore_errors=True)
    if not cfg.results_only:
        if not run_cmd(["foamToVTK", "-latestTime"], rundir, os.path.join(rundir, "log.foamToVTK"), check=False):
            warn("foamToVTK failed; summary.json will have no surface path")
        elif not cfg.volume:
            drop_volume_vtk(rundir)

    partial = bool(result["interrupted"])
    master = os.path.join(cfg.out, "results_partial.csv" if partial else "results.csv")
    meta_path = os.path.join(rundir, "case_meta.env")
    _meta(
        meta_path, cfg, setup, atm, flow, mach, re_num, kind, result,
        meshdir, rundir, overridden, int(partial), lvl_first, yp_retried, yp, name,
    )
    print()
    report(rundir, meta_path, master)
    if cfg.results_only:
        prune_for_results_only(rundir)
    elif not glob.glob(os.path.join(rundir, "[0-9]*", "Cp")) and not glob.glob(
        os.path.join(rundir, "[0-9]*", "Cp.gz"),
    ):
        q_note = 0.5 * cfg.speed ** 2 if kind == "simple" else 0.5 * atm["rho"] * cfg.speed ** 2
        warn("Cp was not written. ParaView still has p; divide by %.8g" % q_note)
    if cfg.open_pv:
        if cfg.results_only:
            die("ParaView was not kept (RESULTS_ONLY / --results-only). Drop -p or disable results-only.")
        surface = find_surface_vtp(rundir)
        target = os.path.join(rundir, surface) if surface else ""
        if surface and os.path.isfile(target) and shutil.which("paraview"):
            import subprocess
            subprocess.Popen(["paraview", target], start_new_session=True)
        elif not shutil.which("paraview"):
            shown = target or os.path.join(rundir, "summary.json")
            warn("paraview not in PATH - open %s manually" % shown)
        else:
            warn("no wall VTK - see %s" % os.path.join(rundir, "summary.json"))

    loaded = read_run(rundir)
    loaded.meshdir = meshdir
    loaded.solve = result
    return loaded


def _halt_sweep(exc):
    code = exc.code
    return code in (None, 0, 130)


def sweep(cfg, aoas):
    """Solve each angle in ``aoas``. The mesh is reused. A failed angle is kept in the polar.

    ``cfg.aoa`` is restored when the sweep returns. ``cfg.remesh`` follows ``run``:
    the first angle may rebuild the mesh, and later angles reuse it.
    ``print_only`` prints each condition and does not write ``polar.csv``.
    """
    angles = [float(angle) for angle in aoas]
    if not angles:
        die("sweep needs at least one angle")
    original = cfg.aoa
    results = []
    failed = []
    print("==> AoA sweep: %s" % ", ".join(token(angle) for angle in angles))
    try:
        for angle in angles:
            cfg.aoa = angle
            try:
                results.append(run(cfg))
            except SystemExit as exc:
                if _halt_sweep(exc):
                    raise
                warn("angle %s deg failed; continuing the sweep" % token(angle))
                results.append(None)
                failed.append((angle, cfg.yaw, cfg.speed))
    finally:
        cfg.aoa = original
        if not cfg.print_only:
            write_polar(cfg.out, failed)
    return results

def sweep_grid(cfg, aoas, yaws, speeds):
    """Solve every (speed, yaw, aoa) combination. A failed case is kept in the polar.

    Speed is the outer loop and AoA the inner one. One mesh per speed and level is
    reused across the yaw and AoA loops, and sized for the largest |yaw| in the list.
    ``cfg.aoa``, ``cfg.yaw`` and ``cfg.speed`` are restored on return.
    """
    aoas = [float(v) for v in aoas]
    yaws = [float(v) for v in yaws]
    speeds = [float(v) for v in speeds]
    if not (aoas and yaws and speeds):
        die("sweep needs at least one angle of attack, yaw, and speed")
    atm = isa(cfg.alt_m)
    kinds = set()
    for speed in speeds:
        try:
            kinds.add(choose_solver(round(speed / atm["a"], 4), cfg.solver)[0])
        except ValueError as exc:
            die(str(exc))
    if len(kinds) > 1:
        warn("speeds cross Mach 0.3, so this grid mixes simpleFoam and rhoSimpleFoam results")
    original = (cfg.aoa, cfg.yaw, cfg.speed)
    results, failed = [], []
    cfg.mesh_yaw = max(abs(v) for v in yaws)
    print("==> Grid sweep: %d speeds x %d yaws x %d AoAs = %d cases" % (
        len(speeds), len(yaws), len(aoas), len(speeds) * len(yaws) * len(aoas),
    ))
    try:
        for speed in speeds:
            for yaw in yaws:
                for angle in aoas:
                    cfg.speed, cfg.yaw, cfg.aoa = speed, yaw, angle
                    try:
                        results.append(run(cfg))
                    except SystemExit as exc:
                        if _halt_sweep(exc):
                            raise
                        warn("speed %s, yaw %s, AoA %s failed; continuing" % (
                            token(speed), token(yaw), token(angle)))
                        results.append(None)
                        failed.append((angle, yaw, speed))
    finally:
        cfg.aoa, cfg.yaw, cfg.speed = original
        cfg.mesh_yaw = None
        if not cfg.print_only:
            write_polar(cfg.out, failed)
    return results
