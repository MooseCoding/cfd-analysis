"""Checks that do not need OpenFOAM."""
import importlib.util
import io
import json
import math
import os
import re
import tempfile
import unittest
from contextlib import redirect_stderr

from cfd.aero import body_coeffs, center_of_pressure, choose_solver, mach_note, static_margin
from cfd import make_config, plan, read_csv, read_results, read_run, sweep
from cfd.config import REPO_ROOT, find_config_path, parse_aoas, resolve
from cfd.env import docker_command, launch_mode, skip_launch
from cfd.geom import (
    choose_scale, frontal_area, make, make_rocket, prepare, read_solids, reference, rocket_reference,
)
from cfd.case import prune_for_results_only
from cfd.report import (
    drop_volume_vtk, find_surface_vtp, find_volume_vtu, fmt_coeff, history_rows, polar_rows,
    report, write_history, write_polar, _sigma_csv,
)


class CoeffTest(unittest.TestCase):
    def test_prune_for_results_only(self):
        with tempfile.TemporaryDirectory() as rundir:
            for name in (
                "report.txt", "results.csv", "summary.json", "case_meta.env", "log.simpleFoam",
                "history.csv", "history.svg",
            ):
                open(os.path.join(rundir, name), "w").close()
            os.makedirs(os.path.join(rundir, "VTK"))
            os.makedirs(os.path.join(rundir, "postProcessing"))
            os.makedirs(os.path.join(rundir, "500"))
            open(os.path.join(rundir, "case.foam"), "w").close()
            prune_for_results_only(rundir)
            left = set(os.listdir(rundir))
            self.assertEqual(
                left,
                {
                    "report.txt", "results.csv", "summary.json", "case_meta.env", "log.simpleFoam",
                    "history.csv", "history.svg",
                },
            )

    def test_fmt_coeff_omits_scatter_when_disabled(self):
        self.assertEqual(fmt_coeff(0.5, 0.01, scatter=False), "0.50000")
        self.assertIn("±", fmt_coeff(0.5, 0.01, scatter=True))
        self.assertEqual(_sigma_csv(0.01, False), "")
        self.assertEqual(_sigma_csv(0.01, True), "1.000000e-02")

    def test_body_axes_and_center_of_pressure(self):
        ca, cn = body_coeffs(0.5, 0.0, 0.0)
        self.assertAlmostEqual(ca, 0.5)
        self.assertAlmostEqual(cn, 0.0)
        ca, cn = body_coeffs(0.2, 0.3, 90.0)
        self.assertAlmostEqual(ca, -0.3)
        self.assertAlmostEqual(cn, 0.2)
        self.assertIsNone(center_of_pressure(1.0, 0.1, 0.1, 0.0))
        x_cp = center_of_pressure(1.0, 0.1, 0.1, 0.5)
        self.assertAlmostEqual(x_cp, 0.98)
        self.assertAlmostEqual(static_margin(x_cp, 1.0, 0.1), -0.2)
        aft = center_of_pressure(1.0, -0.1, 0.1, 0.5)
        self.assertAlmostEqual(static_margin(aft, 1.0, 0.1), 0.2)

    def test_solver_switch(self):
        self.assertEqual(choose_solver(0.2, "auto"), ("simple", False))
        self.assertEqual(choose_solver(0.5, "auto"), ("rho", False))
        self.assertEqual(choose_solver(0.8, "auto"), ("rho", True))
        self.assertEqual(choose_solver(0.2, "rho"), ("rho", False))
        with self.assertRaises(ValueError):
            choose_solver(0.4, "simple")


class ScaleTest(unittest.TestCase):
    def test_plane_target_picks_inches(self):
        name, factor = choose_scale(36.0, "", target=3 * 0.3048)
        self.assertEqual(name, "in")
        self.assertAlmostEqual(factor, 0.0254)

    def test_body_unique_and_ambiguous(self):
        name, factor = choose_scale(0.1, "", mode="body")
        self.assertEqual((name, factor), ("m", 1.0))
        with self.assertRaises(SystemExit):
            choose_scale(1000.0, "", mode="body")


class GeometryTest(unittest.TestCase):
    def test_frontal_area_of_a_box(self):
        def face(a, b, c, d):
            return [(a, b, c), (a, c, d)]

        o, x, y, z = (0, 0, 0), (2, 0, 0), (0, 3, 0), (0, 0, 4)
        xy, xz, yz, xyz = (2, 3, 0), (2, 0, 4), (0, 3, 4), (2, 3, 4)
        tris = []
        tris += face(o, y, xy, x)
        tris += face(z, xz, xyz, yz)
        tris += face(o, x, xz, z)
        tris += face(y, yz, xyz, xy)
        tris += face(o, z, yz, y)
        tris += face(x, xy, xyz, xz)
        self.assertAlmostEqual(frontal_area(tris), 3 * 4)

    def test_builtin_plane_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "plane.stl")
            make(path, 3)
            ref = reference(read_solids(path))
        self.assertGreater(ref["area"], 0.05)
        self.assertLess(ref["area"], 0.5)
        self.assertGreater(ref["chord"], 0.05)
        self.assertLess(ref["chord"], 0.4)

    def test_builtin_rocket_reference(self):
        diameter = 0.1016
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "rocket.stl")
            make_rocket(path, diameter, 0.80, 0.20, "ogive", 4, 0.12, 0.06, 0.10, 0.04, None)
            ref = rocket_reference(read_solids(path))
            nu = 1.5e-5
            setup = prepare(
                path, os.path.join(folder, "body.stl"), "m", "auto",
                30.0, nu, 0, 4e6, "", profile="rocket", target_size_m=1.0,
            )
        self.assertAlmostEqual(ref["diameter"], diameter, delta=0.002)
        self.assertAlmostEqual(ref["area"], math.pi * (diameter / 2.0) ** 2, delta=5e-4)
        self.assertAlmostEqual(setup["ref_chord"], diameter, delta=0.01)
        self.assertGreater(setup["lvl"], 0)


class ApiTest(unittest.TestCase):
    def test_find_config_path_from_repo_relative(self):
        with tempfile.TemporaryDirectory() as elsewhere:
            prev = os.getcwd()
            try:
                os.chdir(elsewhere)
                path = find_config_path("config/plane.conf")
                self.assertEqual(path, os.path.join(REPO_ROOT, "config", "plane.conf"))
                cfg = make_config("config/plane.conf", speed=1.0, print_only=True)
                self.assertTrue(cfg.out.startswith(REPO_ROOT))
                self.assertTrue(cfg.out.endswith("plane_cfd"))
            finally:
                os.chdir(prev)

    def test_make_config_overrides(self):
        cfg = make_config(os.path.join(REPO_ROOT, "config", "plane.conf"), speed=22.0, aoa=5.0)
        self.assertEqual(cfg.profile, "plane")
        self.assertEqual(cfg.speed, 22.0)
        self.assertEqual(cfg.aoa, 5.0)

    def test_make_config_max_iterations(self):
        cfg = make_config(os.path.join(REPO_ROOT, "config", "plane.conf"), iters=900)
        self.assertEqual(cfg.iters, 900)
        self.assertEqual(cfg.max_iterations, 900)
        cfg.max_iterations = 1100
        self.assertEqual(cfg.iters, 1100)
        alias = make_config(os.path.join(REPO_ROOT, "config", "plane.conf"), max_iterations=750)
        self.assertEqual(alias.iters, 750)

    def test_max_compute_light(self):
        cfg = make_config(os.path.join(REPO_ROOT, "config", "plane.conf"), max_compute="light", environ={})
        self.assertEqual(cfg.max_compute, "light")
        self.assertEqual(cfg.cellcap, 1000000.0)
        self.assertEqual(cfg.nprocs, 2)
        heavy = resolve(
            ["--config", os.path.join(REPO_ROOT, "config", "plane.conf"), "--max-compute", "heavy"],
            environ={},
        )
        self.assertEqual(heavy.cellcap, 16000000.0)
        capped = resolve(
            ["--config", os.path.join(REPO_ROOT, "config", "plane.conf"), "--max-compute", "light", "-n", "8"],
            environ={},
        )
        self.assertEqual(capped.nprocs, 8)
        self.assertEqual(capped.cellcap, 1000000.0)

    def test_plan_exposes_max_iterations(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = make_config(
                os.path.join(REPO_ROOT, "config", "plane.conf"),
                out=folder,
                max_iterations=1234,
            )
            summary = plan(cfg)
        self.assertEqual(summary["max_iterations"], 1234)
        self.assertEqual(summary["iters"], 1234)

    def test_read_csv_fixture_falls_back_without_json(self):
        fixture = os.path.join(REPO_ROOT, "tests", "data", "results_partial.csv")
        rows = read_csv(fixture)
        self.assertGreaterEqual(len(rows), 1)
        self.assertIn("Cl", rows[0])
        self.assertIn("Cd", rows[0])
        with tempfile.TemporaryDirectory() as out:
            target = os.path.join(out, "results_partial.csv")
            with open(fixture) as src, open(target, "w") as dst:
                dst.write(src.read())
            loaded = read_results(out)
            self.assertEqual(loaded[0]["Cl"], rows[0]["Cl"])
            self.assertIsInstance(loaded[0]["Cl"], str)

    def test_report_writes_summary_json(self):
        with tempfile.TemporaryDirectory() as out:
            case = os.path.join(out, "run_fixture")
            os.makedirs(os.path.join(case, "postProcessing", "forceCoeffs1", "0"))
            coeff = os.path.join(case, "postProcessing", "forceCoeffs1", "0", "coefficient.dat")
            with open(coeff, "w") as handle:
                handle.write("# Time Cl Cd Cs CmPitch CmRoll CmYaw\n")
                handle.write("1 0.40 0.030 0.0 -0.02 0.0 0.0\n")
                handle.write("2 0.42 0.032 0.0 -0.02 0.0 0.0\n")
            vtp_dir = os.path.join(case, "VTK", "run_fixture_2", "boundary")
            os.makedirs(vtp_dir)
            open(os.path.join(vtp_dir, "plane.vtp"), "w").close()
            open(os.path.join(vtp_dir, "farfield.vtp"), "w").close()
            volume = os.path.join(case, "VTK", "run_fixture_2", "internal.vtu")
            open(volume, "w").close()
            self.assertEqual(find_volume_vtu(case), "VTK/run_fixture_2/internal.vtu")
            drop_volume_vtk(case)
            self.assertFalse(os.path.isfile(volume))
            self.assertEqual(find_volume_vtu(case), "")
            self.assertEqual(find_surface_vtp(case), "VTK/run_fixture_2/boundary/plane.vtp")
            meta = os.path.join(case, "case_meta.env")
            with open(meta, "w") as handle:
                handle.write("\n".join([
                    "GEOMETRY=builtin3ft",
                    "PROFILE=plane",
                    "SOLVER=simple",
                    "AOA=4",
                    "SPEED=20",
                    "ALT_M=0",
                    "MACH=0.0588",
                    "RE=400000",
                    "RHO=1.225",
                    "REF_AREA=0.2",
                    "REF_CHORD=0.15",
                    "REF_XCG=0.1",
                    "REF_YCG=0",
                    "REF_ZCG=0",
                    "STOP=residuals",
                    "PARTIAL=0",
                    "YP_PASS=1",
                    "SCHEME=limitedLinear",
                    "REF_SOURCE=wing",
                    "LIFT_X=0",
                    "LIFT_Z=1",
                    "DRAG_X=1",
                    "DRAG_Z=0",
                ]) + "\n")
            report(case, meta, os.path.join(out, "results.csv"))
            one = read_run(case)
            self.assertEqual(one.row["status"], "converged")
            self.assertEqual(one.row["profile"], "plane")
            self.assertNotIn("rocket", one.row)
            self.assertAlmostEqual(one.coefficients["Cl"], 0.41)
            self.assertAlmostEqual(one.coefficients["Cd"], 0.031)
            self.assertIsInstance(one.coefficients["Cl"], float)
            self.assertEqual(one.row["files"]["surface"], "VTK/run_fixture_2/boundary/plane.vtp")
            self.assertIsNone(one.row["files"].get("volume"))
            open(volume, "w").close()
            with open(meta, "a") as handle:
                handle.write("VOLUME=1\n")
            report(case, meta, os.path.join(out, "results.csv"))
            vol_run = read_run(case)
            self.assertEqual(vol_run.row["files"]["volume"], "VTK/run_fixture_2/internal.vtu")
            self.assertFalse(one.partial)
            rows = read_results(out)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[-1]["files"]["volume"], "VTK/run_fixture_2/internal.vtu")
            self.assertAlmostEqual(rows[0]["coefficients"]["lift_N"], one.coefficients["lift_N"])
            stopped = read_results(out, include_partial=False)
            self.assertEqual(len(stopped), 2)
            with open(os.path.join(out, "summary.csv")) as handle:
                header = handle.readline().strip().split(",")
            self.assertEqual(header[0], "geometry")
            self.assertIn("L_over_D", header)
            self.assertNotIn("CA", header)


class ConfigTest(unittest.TestCase):
    def test_file_then_env_then_flags(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "case.conf")
            with open(path, "w") as handle:
                handle.write("PROFILE=plane\nSPEED=11\nAOA=1\nOUT=%s\n" % folder)
            from_file = resolve(["--config", path], environ={})
            self.assertEqual(from_file.profile, "plane")
            self.assertEqual(from_file.speed, 11.0)
            self.assertEqual(from_file.aoa, 1.0)
            from_env = resolve(["--config", path], environ={"SPEED": "15", "AOA": "3"})
            self.assertEqual(from_env.speed, 15.0)
            self.assertEqual(from_env.aoa, 3.0)
            from_flag = resolve(["--config", path, "-a", "7", "-v", "18"], environ={"SPEED": "15", "AOA": "3"})
            self.assertEqual(from_flag.speed, 18.0)
            self.assertEqual(from_flag.aoa, 7.0)
            from_iters = resolve(
                ["--config", path, "--max-iterations", "750"],
                environ={"ITERS": "3000"},
            )
            self.assertEqual(from_iters.iters, 750)
            from_env_iters = resolve(["--config", path], environ={"ITERS": "1200"})
            self.assertEqual(from_env_iters.iters, 1200)
            no_scatter = resolve(["--config", path, "--no-scatter"], environ={})
            self.assertFalse(no_scatter.report_scatter)
            from_env = resolve(["--config", path], environ={"REPORT_SCATTER": "0"})
            self.assertFalse(from_env.report_scatter)
            results_only = resolve(["--config", path, "--results-only"], environ={})
            self.assertTrue(results_only.results_only)
            smoke = resolve(["--config", path, "--smoke", "-n", "8", "-i", "10", "-q", "fine"], environ={})
            self.assertTrue(smoke.smoke)
            self.assertEqual(smoke.quality, "coarse")
            self.assertEqual(smoke.iters, 80)
            self.assertEqual(smoke.nprocs, 1)
            self.assertEqual(smoke.layers, 0)
            from_env = resolve(["--config", path], environ={"SMOKE": "1"})
            self.assertEqual(from_env.iters, 80)
            self.assertEqual(from_env.nprocs, 1)
            volume = resolve(["--config", path, "--volume"], environ={})
            self.assertTrue(volume.volume)
            self.assertFalse(resolve(["--config", path], environ={}).volume)

    def test_shipped_profiles(self):
        plane = resolve(["--config", os.path.join(REPO_ROOT, "config", "plane.conf")], environ={})
        rocket = resolve(["--config", os.path.join(REPO_ROOT, "config", "rocket.conf")], environ={})
        body = resolve(["--config", os.path.join(REPO_ROOT, "config", "body.conf")], environ={})
        self.assertEqual(plane.profile, "plane")
        self.assertEqual(plane.speed, 20.0)
        self.assertEqual(plane.out, os.path.join(REPO_ROOT, "plane_cfd"))
        self.assertEqual(rocket.profile, "rocket")
        self.assertAlmostEqual(rocket.body_d, 0.1016)
        self.assertEqual(rocket.out, os.path.join(REPO_ROOT, "rocket_cfd"))
        self.assertEqual(body.profile, "body")
        self.assertEqual(body.solver, "auto")
        self.assertEqual(body.out, os.path.join(REPO_ROOT, "body_cfd"))


class LaunchTest(unittest.TestCase):
    def test_print_and_help_skip_docker(self):
        self.assertTrue(skip_launch(["--print"]))
        self.assertTrue(skip_launch(["-h"]))
        self.assertTrue(skip_launch(["--polar"]))
        self.assertFalse(skip_launch(["--polar", "--aoas", "0,2"]))
        self.assertEqual(launch_mode(["--print"], False, False, False, True), "run")
        self.assertEqual(launch_mode(["--polar"], False, False, False, True), "run")
        self.assertEqual(launch_mode(["--config", "x"], False, True, False, True), "run")
        self.assertEqual(launch_mode(["--config", "x"], True, False, False, True), "run")
        self.assertEqual(launch_mode(["--config", "x"], False, False, True, True), "bash")
        self.assertEqual(launch_mode(["--config", "x"], False, False, False, True), "docker")
        self.assertEqual(launch_mode(["--config", "x"], False, False, False, False), "missing")

    def test_docker_command_rewrites_repo_and_stl(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = os.path.join(folder, "repo")
            models = os.path.join(folder, "models")
            os.makedirs(os.path.join(repo, "config"))
            os.makedirs(models)
            cfg = os.path.join(repo, "config", "plane.conf")
            stl = os.path.join(models, "body.stl")
            open(cfg, "w").close()
            open(stl, "w").close()
            cmd = docker_command(
                ["--config", cfg, "-s", stl, "-a", "4"],
                {"SPEED": "15", "STL": stl, "OUT": os.path.join(folder, "out")},
                repo,
                repo,
                uid=1000,
                gid=1000,
                image="opencfd/openfoam-run:2512",
            )
        self.assertIn("opencfd/openfoam-run:2512", cmd)
        self.assertIn("python3", cmd)
        self.assertIn("-m", cmd)
        self.assertIn("cfd", cmd)
        joined = " ".join(cmd)
        self.assertIn("-u", cmd)
        self.assertIn("1000:1000", cmd)
        self.assertIn("-w", cmd)
        work = cmd[cmd.index("-w") + 1]
        self.assertEqual(work, "/work")
        config_arg = cmd[cmd.index("--config") + 1]
        self.assertEqual(config_arg, "/work/config/plane.conf")
        stl_arg = cmd[cmd.index("-s") + 1]
        self.assertTrue(stl_arg.startswith("/mnt/"))
        self.assertTrue(stl_arg.endswith("/body.stl"))
        self.assertIn("SPEED=15", joined)
        self.assertIn("STL=" + stl_arg, joined)
        self.assertTrue(any(part.startswith("OUT=/mnt/") or part.startswith("OUT=/work") for part in cmd))


DOCS_FIXTURE = """\
# Guide

## Planning without OpenFOAM

See [the slices](README.md#slices-through-the-flow).

```bash
echo hi
```

| Part | Role |
|------|------|
| wing | lift |
"""


def _load_docs():
    path = os.path.join(REPO_ROOT, "site", "build.py")
    spec = importlib.util.spec_from_file_location("cfd_docs_build", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _same_page_fragments(markdown):
    found = []
    fence = False
    for line in markdown.splitlines():
        if line.startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        i = 0
        while i < len(line):
            if line[i] == "`":
                j = line.find("`", i + 1)
                if j < 0:
                    break
                i = j + 1
                continue
            if line[i] == "[":
                match = re.match(r"\[[^\]]*\]\(([^)]+)\)", line[i:])
                if match:
                    url = match.group(1)
                    if url.startswith("#") and len(url) > 1:
                        found.append(url[1:])
                    i += match.end()
                    continue
            i += 1
    return found


class FeatureTest(unittest.TestCase):
    def test_mach_note_starts_at_sonic(self):
        self.assertEqual(mach_note(0.99), "")
        note = mach_note(1)
        self.assertIn("1.0000", note)
        self.assertIn("bow shock", note)

    def test_plan_warns_from_mach_one(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = make_config(
                os.path.join(REPO_ROOT, "config", "plane.conf"),
                out=folder,
                speed=400.0,
                aoa=0.0,
            )
            buf = io.StringIO()
            with redirect_stderr(buf):
                summary = plan(cfg)
        self.assertGreaterEqual(summary["mach"], 1.0)
        self.assertIn("bow shock", buf.getvalue())

    def test_parse_aoas_and_cli(self):
        self.assertEqual(parse_aoas("0, 2, 4"), [0.0, 2.0, 4.0])
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "case.conf")
            with open(path, "w") as handle:
                handle.write("PROFILE=plane\nOUT=%s\n" % folder)
            cfg = resolve(["--config", path, "--aoas", "0,2,4", "--polar"], environ={})
            self.assertEqual(cfg.aoas, [0.0, 2.0, 4.0])
            self.assertTrue(cfg.polar_only)
            with self.assertRaises(SystemExit):
                resolve(["--config", path, "-a", "1", "--aoas", "0,2"], environ={})

    def test_history_csv_values_are_in_the_svg(self):
        with tempfile.TemporaryDirectory() as folder:
            log = os.path.join(folder, "log.simpleFoam")
            with open(log, "w") as handle:
                handle.write("\n".join([
                    "Time = 1",
                    "Solving for Ux, Initial residual = 1.0e-01, Final residual = 1e-8",
                    "Solving for Uy, Initial residual = 2.0e-01, Final residual = 1e-8",
                    "Solving for Uz, Initial residual = 3.0e-01, Final residual = 1e-8",
                    "Solving for p, Initial residual = 4.0e-01, Final residual = 1e-8",
                    "Solving for k, Initial residual = 5.0e-02, Final residual = 1e-8",
                    "Solving for omega, Initial residual = 6.0e-02, Final residual = 1e-8",
                    "Time = 2",
                    "Solving for Ux, Initial residual = 1.0e-03, Final residual = 1e-8",
                    "Solving for Uy, Initial residual = 2.0e-03, Final residual = 1e-8",
                    "Solving for Uz, Initial residual = 3.0e-03, Final residual = 1e-8",
                    "Solving for p, Initial residual = 4.0e-03, Final residual = 1e-8",
                    "Solving for k, Initial residual = 5.0e-04, Final residual = 1e-8",
                    "Solving for omega, Initial residual = 6.0e-04, Final residual = 1e-8",
                    "",
                ]))
            coeff = os.path.join(folder, "coefficient.dat")
            with open(coeff, "w") as handle:
                handle.write("# Time Cl Cd\n1 0.40 0.030\n2 0.42 0.032\n")
            rows = history_rows(log, coeff, 1e-5, 1e-6, 1e-6)
            self.assertEqual([row["iteration"] for row in rows], [1, 2])
            self.assertAlmostEqual(rows[0]["p"], 0.4)
            self.assertAlmostEqual(rows[0]["residual_ratio"], 0.3 / 1e-6)
            self.assertAlmostEqual(rows[1]["Cl"], 0.42)
            write_history(folder, rows)
            csv_text = open(os.path.join(folder, "history.csv")).read()
            svg = open(os.path.join(folder, "history.svg")).read()
            self.assertIn("iteration,p,Ux,Uy,Uz,k,omega,Cl,Cd", csv_text)
            self.assertIn("<polyline", svg)
            for line in csv_text.splitlines()[1:]:
                for cell in line.split(","):
                    if cell:
                        self.assertIn(cell, svg)

    def test_polar_rows_keep_the_latest_angle_and_a_failure(self):
        records = [
            {
                "status": "converged",
                "flight": {"aoa_deg": 0, "mach": 0.05},
                "coefficients": {"Cl": 0.1, "Cd": 0.02, "L_over_D": 5},
                "quality": {"yplus_pass": True},
            },
            {
                "status": "converged",
                "flight": {"aoa_deg": 4, "mach": 0.05},
                "coefficients": {"Cl": 0.4, "Cd": 0.03, "L_over_D": 13},
                "quality": {"yplus_pass": False},
            },
            {
                "status": "stopped",
                "flight": {"aoa_deg": 0, "mach": 0.05},
                "coefficients": {"Cl": 0.15, "Cd": 0.02, "L_over_D": 7.5},
                "quality": {"yplus_pass": True},
            },
        ]
        rows = polar_rows(records, failed_aoas=[4])
        self.assertEqual([row["aoa_deg"] for row in rows], [0.0, 4.0])
        self.assertAlmostEqual(rows[0]["Cl"], 0.15)
        self.assertEqual(rows[0]["status"], "stopped")
        self.assertEqual(rows[0]["yplus_pass"], "yes")
        self.assertEqual(rows[1]["status"], "failed")
        self.assertIsNone(rows[1]["Cl"])

    def test_write_polar_names_the_run_and_embeds_the_csv(self):
        with tempfile.TemporaryDirectory() as folder:
            record = {
                "geometry": "builtin3ft",
                "status": "converged",
                "flight": {"aoa_deg": 2, "mach": 0.0588},
                "coefficients": {"Cl": 0.2, "Cd": 0.02, "L_over_D": 10},
                "quality": {"yplus_pass": True},
            }
            with open(os.path.join(folder, "summaries.jsonl"), "w") as handle:
                handle.write(json.dumps(record) + "\n")
            run_dir = os.path.join(folder, "run_builtin_aoa2")
            os.makedirs(run_dir)
            with open(os.path.join(run_dir, "summary.json"), "w") as handle:
                json.dump(record, handle)
            write_polar(folder)
            csv_text = open(os.path.join(folder, "polar.csv")).read()
            svg = open(os.path.join(folder, "polar.svg")).read()
            self.assertIn("run_builtin_aoa2", csv_text)
            self.assertIn("2.000000e-01", csv_text)
            self.assertIn("2.000000e-01", svg)
            self.assertIn("<circle", svg)

    def test_sweep_continues_after_a_failed_angle(self):
        import cfd.api as api
        from cfd.proc import die

        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "case.conf")
            with open(path, "w") as handle:
                handle.write("PROFILE=plane\nSPEED=20\nAOA=1\nOUT=%s\n" % folder)
            cfg = make_config(path, out=folder)
            seen = []

            def fake_run(active):
                seen.append(active.aoa)
                if active.aoa == 2:
                    die("boom")
                return api.RunResult(rundir=folder, out_dir=folder, geometry="g")

            original = api.run
            api.run = fake_run
            try:
                results = sweep(cfg, [0, 2, 4])
            finally:
                api.run = original
            self.assertEqual(seen, [0.0, 2.0, 4.0])
            self.assertEqual(cfg.aoa, 1.0)
            self.assertIsNone(results[1])
            self.assertIsNotNone(results[0])
            csv_text = open(os.path.join(folder, "polar.csv")).read()
            self.assertIn("failed", csv_text)

    def test_sweep_print_only_skips_the_polar(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = make_config(
                os.path.join(REPO_ROOT, "config", "plane.conf"),
                out=folder,
                print_only=True,
                speed=20,
            )
            results = sweep(cfg, [0, 2])
            self.assertEqual(len(results), 2)
            self.assertFalse(os.path.isfile(os.path.join(folder, "polar.csv")))
            self.assertEqual(cfg.aoa, 4.0)


class DocsTest(unittest.TestCase):
    def test_fixture_covers_heading_table_fence_and_link(self):
        body, _toc, _title = _load_docs().render_document(DOCS_FIXTURE)
        self.assertIn('id="planning-without-openfoam"', body)
        self.assertIn("<td>wing</td>", body)
        self.assertIn("<pre><code>echo hi</code></pre>", body)
        self.assertIn('href="index.html#slices-through-the-flow"', body)

    def test_readme_and_api_anchors_resolve(self):
        mod = _load_docs()
        rendered = []
        for src, dest, _key, _label in mod.PAGES:
            with open(os.path.join(REPO_ROOT, src), encoding="utf-8") as handle:
                text = handle.read()
            body, toc, title = mod.render_document(text, src)
            self.assertTrue(title, src)
            self.assertTrue(toc, src)
            ids = set(re.findall(r'id="([^"]+)"', body))
            for frag in _same_page_fragments(text):
                self.assertIn(frag, ids, "%s#%s" % (src, frag))
            rendered.append((src, dest, body, ids))
        ids_by_page = {dest: ids for _src, dest, _body, ids in rendered}
        for src, _dest, body, _ids in rendered:
            hrefs = re.findall(r'href="([^"]+)"', body)
            cross = [href for href in hrefs if href.endswith(".html") or ".html#" in href]
            self.assertTrue(cross, src)
            for href in cross:
                page, _, frag = href.partition("#")
                self.assertIn(page, ids_by_page, "%s -> %s" % (src, href))
                if frag:
                    self.assertIn(frag, ids_by_page[page], "%s -> %s" % (src, href))
        with open(os.path.join(REPO_ROOT, "README.md"), encoding="utf-8") as handle:
            readme = mod.render_document(handle.read(), "README.md")[0]
        self.assertIn('href="api.html"', readme)
        self.assertIn('href="tutorial.html"', readme)
        self.assertIn("<code>config/plane.conf</code>", readme)
        self.assertIn("<code>cfd/geom.py</code>", readme)
        self.assertNotIn('href="config/', readme)
        self.assertNotIn('href="cfd/', readme)
        with open(os.path.join(REPO_ROOT, "API.md"), encoding="utf-8") as handle:
            api = mod.render_document(handle.read(), "API.md")[0]
        self.assertIn('id="runresult"', api)
        self.assertIn('id="sweep"', api)
        self.assertIn('href="index.html#analyzing-results-in-paraview"', api)
        self.assertIn("builtin&lt;span&gt;ft", api)


if __name__ == "__main__":
    unittest.main()
