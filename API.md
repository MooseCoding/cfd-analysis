# Python API

The `cfd` package runs the same mesh → solve → report pipeline as `./plane-foam.sh` and friends, but from Python. Configuration, dry-run planning, execution, and reading results are all supported. The implementation uses only the Python standard library (no pip dependencies).

For flight profiles, solvers, ParaView, and folder layout, see [README.md](README.md).

## Contents

- [Setup](#setup) and a [quick example](#quick-example)
- [Public exports](#public-exports)
- [Configuration](#configuration) (`make_config`, `resolve`, every field)
- [Planning without OpenFOAM](#planning-without-openfoam)
- [Running a case](#running-a-case) and [`RunResult`](#runresult)
- [Reading results](#reading-results), [VTK and ParaView](#vtk-and-paraview), [CSV columns](#results-csv-columns), [`case_meta.env`](#case_metaenv-keys)
- [Profiles](#profiles), [sweeps](#sweep), [CLI map](#cli-equivalence)
- [Other modules](#other-modules) (atmosphere, coefficients, report rewrite)
- [Tests](#tests) and [errors](#errors)

## Setup

Run Python from the repository root (or any directory where `cfd` is on `PYTHONPATH`):

```bash
cd /path/to/openfoam
python3
```

`plan()` and `read_*()` do not need OpenFOAM. `run()` uses `simpleFoam` already on `PATH`. `python3 -m cfd` (and `./plane-foam.sh`) source a local OpenFOAM `etc/bashrc` or re-exec inside `opencfd/openfoam-run:2512` when Docker is available. `--print` does neither.

```python
import cfd
```

## Quick example

```python
from cfd import make_config, plan, run, read_results

cfg = make_config(
    "config/body.conf",
    stl="model.stl",
    units="m",
    speed=15.0,
    aoa=0.0,
    out="./body_cfd",
)

# Inspect solver choice and paths without OpenFOAM
info = plan(cfg)
print(info["mach"], info["solver"], info["run_dir"])

# Full solve (needs OpenFOAM in PATH)
result = run(cfg)
print(result.rundir, result.coefficients["Cl"], result.coefficients["Cd"])

# History across runs in the output folder (summary records)
for row in read_results("./body_cfd"):
    print(row["geometry"], row["flight"]["aoa_deg"], row["coefficients"]["Cl"], row["coefficients"]["Cd"])
```

## Public exports

| Name | Role |
|------|------|
| `make_config` | Build a `Config` from a `.conf` file plus keyword overrides |
| `from_mapping` | Same as `make_config` (alias in `cfd.config`) |
| `resolve` | Build a `Config` from CLI-style `argv` (as used by `python3 -m cfd`) |
| `plan` | Geometry + reference + solver summary; no OpenFOAM binaries |
| `run` | Full pipeline; returns `RunResult` |
| `sweep` | Solve several angles into one output folder; write `polar.csv` |
| `write_polar` | Rebuild `polar.csv` and `polar.svg` from `summaries.jsonl` |
| `read_csv` | Parse one `results.csv` or `results_partial.csv` |
| `read_results` | Summary records from `summaries.jsonl`, or the wide CSV when that file is missing |
| `list_runs` | `run_*` case directories, oldest first |
| `read_run` | Meta + coefficients for one run folder |
| `RunResult` | Object returned by `run` and `read_run` |
| `Config` | Plain namespace of run settings |

Import either from the package or from submodules:

```python
from cfd import make_config, run
from cfd.config import resolve, from_mapping
```

## Configuration

### `make_config(config_path=None, environ=None, **overrides)`

1. Loads defaults, then the config file (default: `config/body.conf` if `config_path` is omitted).
2. Applies `environ` keys that match config file names (`SPEED`, `AOA`, `STL`, …).
3. Applies `**overrides` using Python attribute names on `Config`.

Example:

```python
cfg = make_config(
    "config/plane.conf",
    environ={},           # optional; defaults to os.environ
    speed=18.0,
    aoa=6.0,
    max_iterations=3000,  # alias of iters; same as CLI --max-iterations
    remesh=True,          # force a new mesh this run
    write_on_exit=True,   # Ctrl+C: write fields and post-process (same as `-w`)
)
```

Relative `stl` paths in a config file are resolved against the config file’s directory. Passing `stl=` in overrides uses the path you give (absolute or relative to the current working directory).

If `out` is empty, it becomes `plane_cfd`, `rocket_cfd`, or `body_cfd` under the repository root (`cfd.config.REPO_ROOT`), not the shell cwd. Relative `OUT` in a config file is resolved against that file’s directory; relative `out` from the API or environment is resolved against `REPO_ROOT`. Config paths like `config/plane.conf` are found via cwd, then `REPO_ROOT`.

### `resolve(argv=None, environ=None)`

Parses the same flags as the CLI (`-a`, `-v`, `-s`, `--config`, …). Useful when you already have an argument list:

```python
from cfd.config import resolve

cfg = resolve(["--config", "config/rocket.conf", "-v", "30", "-a", "0"])
```

### Config fields

Keywords for `make_config` / attributes on `Config` (config file keys in parentheses):

| Field | Config key | Notes |
|-------|------------|--------|
| `profile` | `PROFILE` | `plane`, `rocket`, or `body` |
| `aoa` | `AOA` | Angle of attack, degrees |
| `speed` | `SPEED` | Freestream speed, m/s |
| `alt_m` | `ALT_M` | Altitude, m (0–11000, ISA) |
| `stl` | `STL` | STL path (`body` profile requires this) |
| `span_ft` | `SPAN_FT` | Built-in plane span, feet |
| `units` | `UNITS` | `m`, `mm`, `cm`, `in`, `ft`, or empty/`auto` |
| `quality` | `QUALITY` | `coarse`, `medium`, `fine`, `vfine`, or empty/`auto` |
| `layers` | `LAYERS` | Prism layers (0 = wall functions) |
| `iters`, `max_iterations` | `ITERS` | Max SIMPLE iterations (`controlDict` `endTime`). On `Config`, `max_iterations` is a property backed by `iters`. Passing both keywords with different values exits. |
| `nprocs` | `NPROCS` | MPI ranks (default: CPU count) |
| `max_compute` | `MAX_COMPUTE`, `COMPUTE` | Compute budget: `light`, `medium`, or `heavy` (sets cell cap and, for `light`, MPI ranks unless `CELLCAP` / `NPROCS` are set explicitly) |
| `turb_int` | `TURB_INT` | Freestream turbulence intensity |
| `cellcap` | `CELLCAP` | Mesh cell budget (overrides `MAX_COMPUTE` when set explicitly) |
| `target_yplus` | `TARGET_YPLUS` | Target wall y+ |
| `out` | `OUT` | Output directory |
| `ref_area` | `REF_AREA` | Reference area, m² |
| `ref_length` | `REF_LENGTH`, `REF_CHORD` | MAC / Lref, m |
| `ref_x`, `ref_y`, `ref_z` | `REF_X`, `REF_Y`, `REF_Z` (and `REF_*CG`) | Moment center, m |
| `solver` | `SOLVER` | `auto`, `simple`, or `rho` |
| `target_size_m` | `TARGET_SIZE_M` | Length used when guessing STL units. See below. |
| `write_on_exit` | `WRITE_ON_EXIT` | Partial run on interrupt |
| `report_scatter` | `REPORT_SCATTER` | When false (`--no-scatter`), coefficients in `report.txt` are means only and `sigma_*` CSV fields are left blank |
| `results_only` | `RESULTS_ONLY` | Skip VTK and prune the run directory after reporting (`summary.json`, report, CSV, logs) |
| `smoke` | `SMOKE` | CLI `--smoke`. Forces coarse mesh, 80 iterations, 1 rank, 0 layers. Wins over `-i`, `-n`, `-q`, and `-l` |
| `volume` | `VOLUME` | CLI `--volume`. Keep `internal.vtu` and the `.vtm` multiblock file. Required for streamlines and volume slices in ParaView. Default drops `internal.vtu` after `foamToVTK` |
| `remesh` | — | CLI `-m`; rebuild mesh |
| `open_pv` | — | CLI `-p`; open the wall `.vtp` in ParaView (not the volume; use `volume=True` and open `VTK/*.vtm` yourself for flow visualization) |
| `print_only` | — | CLI `--print`; `run()` prints the condition and returns without meshing |
| `config_path` | — | Absolute path of the file that was loaded |

Built-in rocket only (ignored when `stl` is set). Lengths are metres. See `config/rocket.conf`.

| Field | Config key | Default | Notes |
|-------|------------|---------|--------|
| `body_d` | `BODY_D` | `0.1016` | Diameter (4 in) |
| `body_l` | `BODY_L` | `0.80` | Cylindrical length, not including the nose |
| `nose_l` | `NOSE_L` | `0.20` | Nose length |
| `nose` | `NOSE` | `ogive` | `ogive`, `cone`, or `elliptical` |
| `fin_count` | `FIN_COUNT` | `4` | At least 2 |
| `fin_root` | `FIN_ROOT` | `0.12` | Root chord |
| `fin_tip` | `FIN_TIP` | `0.06` | Tip chord |
| `fin_span` | `FIN_SPAN` | `0.10` | Radial span out from the tube |
| `fin_sweep` | `FIN_SWEEP` | `0.04` | Leading-edge sweep, root to tip |
| `fin_x` | `FIN_X` | empty | Root leading edge from the nose tip. Empty puts the trailing edge at the base. |

`target_size_m` (`TARGET_SIZE_M`) is the length hint used when guessing STL units. For a built-in rocket with no STL it defaults to `nose_l + body_l` inside `plan` / `run`. The plane profile does not use it.

Invalid combinations call `die()` and exit the process (same as the CLI).

## Planning without OpenFOAM

### `plan(cfg) -> dict`

Builds or reuses geometry, cleans the STL, computes reference lengths and mesh sizing, and picks the solver. Does **not** call `blockMesh`, `snappyHexMesh`, or the flow solver.

Returned keys include:

| Key | Content |
|-----|---------|
| `profile`, `geometry`, `geom_dir`, `mesh_dir`, `run_dir`, `out_dir` | Paths and names |
| `aoa_deg`, `speed_ms`, `alt_m`, `mach`, `reynolds` | Flight condition |
| `iters`, `max_iterations` | SIMPLE iteration cap (both keys, same integer) |
| `solver_kind`, `solver`, `transonic`, `solver_reason` | Solver choice |
| `atmosphere` | `rho`, `nu`, `T`, `p`, `a`, … |
| `reference` | `area_m2`, `length_m`, `moment_center_m`, `source`, `overridden`, `diameter_m` |
| `mesh` | `level`, `surface_dx_m`, `predicted_yplus`, `estimated_cells`, … |
| `turbulence` | `intensity`, `k`, `omega` |
| `setup` | Full internal dict used by mesh/case writers (advanced use) |

`plan` may write under `out` (e.g. `geom_*`, cleaned `body.stl`) because it uses the same geometry step as a real run.

Dry run via `run` only (prints to stdout, no solve):

```python
cfg = make_config("config/plane.conf", print_only=True)
run(cfg)
```

## Running a case

### `run(cfg) -> RunResult`

Executes mesh generation, case setup, solve, VTK export, and reporting. Progress is printed to stdout like the shell wrappers.

Requirements:

- OpenFOAM sourced (`blockMesh`, `snappyHexMesh`, `checkMesh`, `simpleFoam` or `rhoSimpleFoam`, `foamToVTK`, …).
- For `profile="body"`, `cfg.stl` must point to an existing file.

On success, the run folder contains `summary.json`, `case_meta.env`, `report.txt`, `results.csv` (if Cl/Cd are finite), and, unless `results_only` is set, VTK under `VTK/` (wall `.vtp`, optional `internal.vtu`, and a `.vtm` multiblock index) plus `postProcessing/`. `internal.vtu` is removed unless `volume` is set. `results_only` leaves `summary.json`, the report, the wide CSV, `case_meta.env`, optional bin CSVs, and logs. The output folder also gets `summaries.jsonl`, `summary.csv`, and a new row in `results.csv` or `results_partial.csv`.

`print_only=True` stops after the flight-condition print. The returned `RunResult` has paths and a short `meta` (`MACH`, `RE`, `GEOMETRY`) and no coefficients. Prefer `plan(cfg)` when you want the full summary dict and no stdout dump.

`run` calls `die()` (process exit) when OpenFOAM binaries are missing, the STL is missing, or the solver fails. An interrupt without `write_on_exit` exits with status 130 and writes nothing. With `write_on_exit`, the first Ctrl+C keeps a partial result (`partial=True`, row goes to `results_partial.csv`).

## `RunResult`

| Attribute | Description |
|-----------|-------------|
| `rundir` | Path to `run_<name>_lvl…_aoa…_v…/` |
| `meshdir` | Path to `mesh_<name>_lvl…_lay…/` |
| `out_dir` | Parent output folder (`plane_cfd`, etc.) |
| `geometry` | Geometry name string (e.g. STL basename or `builtin3ft`) |
| `partial` | True if the solve was interrupted or marked partial |
| `meta` | Dict from `case_meta.env` (`MACH`, `RE`, `REF_AREA`, `GEOMETRY`, …) |
| `row` | `summary.json` when that file exists (numbers and `null`). Otherwise the last wide `results.csv` row (strings) |
| `coefficients` | The `coefficients` object from `summary.json` (`Cl`, `Cd`, `L_over_D`, `lift_N`, `drag_N`). Alias for `row` when the run only has the wide CSV |
| `solve` | Dict from the solver step. Empty when loaded with `read_run`. |

`solve` after a real `run()`:

| Key | Content |
|-----|---------|
| `solved` | `True` when the solver returned |
| `interrupted` | `0`, or `1` if stopped with `-w` / `write_on_exit` |
| `scheme` | `"limitedLinear"`, or `"upwind"` after the one turbulence retry |
| `stop` | `"residuals"`, `"iterations"` (hit the cap), or `"interrupted"` |
| `log` | Path to `log.simpleFoam` or `log.rhoSimpleFoam` |

`get(key, default=None)` checks `row`, then `coefficients`, `flight`, `quality`, and `rocket`, then `meta` (env keys like `SPEED`).

After `run()`:

```python
result = run(cfg)
cl = result.coefficients["Cl"]          # float, or None
mach = result.row["flight"]["mach"]     # also result.meta["MACH"] on a fresh run
log_path = result.solve.get("log")
```

## Reading results

### `read_csv(path) -> list[dict]`

Returns one dict per data row. Missing file → `[]`. Column names match [results CSV format](#results-csv-columns).

### `read_results(out_dir, include_partial=True) -> list[dict]`

Reads `out_dir/summaries.jsonl` when that file exists. Each record matches `summary.json` (numbers and `null`). `include_partial=False` drops records whose `status` is `partial`. If the JSONL file is missing, this falls back to `results.csv` plus `results_partial.csv` and those rows stay strings.

### `list_runs(out_dir) -> list[str]`

Absolute paths to `run_*` directories, sorted by modification time (oldest first).

### `read_run(rundir) -> RunResult`

Loads `summary.json` when present, otherwise `case_meta.env` and the last row of `rundir/results.csv`. Use this to reload an old run without solving again:

```python
from cfd import list_runs, read_run

runs = list_runs("./body_cfd")
latest = read_run(runs[-1])
print(latest.row["status"], latest.coefficients["Cd"])
```

### Per-run files (not wrapped by the API)

You can still open these paths directly:

| Path | Content |
|------|---------|
| `<rundir>/summary.json` | Flight, coefficients, quality, `files.surface` (wall `.vtp`), `files.volume` (`internal.vtu` when `volume=True`) |
| `<rundir>/VTK/*.vtm` | Multiblock VTK: internal volume + boundary (when VTK was written and `results_only` is false) |
| `<rundir>/VTK/.../internal.vtu` | Volume fields for ParaView; present only when `volume=True` / `--volume` |
| `<rundir>/VTK/.../boundary/*.vtp` | Patches including the wall (`body.vtp`, `plane.vtp`, …) and `farfield.vtp` |
| `<out>/summaries.jsonl` | One `summary.json` object per line |
| `<out>/summary.csv` | Short spreadsheet: geometry, status, Cl, Cd, L/D, forces, y+, surface |
| `<rundir>/report.txt` | Long human-readable write-up |
| `<rundir>/history.csv` | One row per iteration: `iteration`, `p`, `Ux`, `Uy`, `Uz`, `k`, `omega`, `Cl`, `Cd` |
| `<rundir>/history.svg` | Worst residual ratio and Cl versus iteration |
| `<out>/polar.csv` | One row per angle after `sweep` or `write_polar`: `aoa_deg`, `Cl`, `Cd`, `L_over_D`, `status`, `mach`, `yplus_pass`, `run` |
| `<out>/polar.svg` | Cl and Cd versus angle |
| `<rundir>/case_meta.env` | Machine-readable run metadata |
| `<rundir>/spanwise_cl.csv` | Plane only. Columns `y_m`, `Cl`, `Cd` (each bin’s contribution to the aircraft coefficient) |
| `<rundir>/axial_load.csv` | Rocket only. Columns `x_m`, `CA`, `CN` |
| `<out>/results.csv` | All converged runs |
| `<out>/results_partial.csv` | Interrupted or partial runs |

Lower-level helpers in `cfd.report` (e.g. `load_meta`, `find_surface_vtp`, `find_volume_vtu`) are available for custom tooling but are not part of the stable `cfd` package surface.

## VTK and ParaView

After a successful solve (or a partial run with `write_on_exit`), the driver runs `foamToVTK -latestTime` unless `results_only` is set. The API does not launch ParaView except when `open_pv=True` (`-p`), which opens the wall surface from `summary.json` → `files.surface`.

| Use case | Config | What to open |
|----------|--------|----------------|
| Wall Cp, y+, pressure | default (wall VTK kept) | `read_run(rundir).row["files"]["surface"]` or `./view-case.sh <rundir>` |
| Slices, streamlines, \|U\| in the volume | `volume=True` | `read_run(rundir).row["files"]["volume"]`, or `VTK/*.vtm` (multiblock: internal + boundary) |
| Numbers only, no VTK | `results_only=True` | No `VTK/` tree |

Example: resolve paths after a volume run without re-solving:

```python
import glob
import os
from cfd import list_runs, read_run
from cfd.report import find_volume_vtu

rundir = list_runs("./plane_cfd")[-1]
run = read_run(rundir)
files = run.row.get("files") or {}
wall = os.path.join(rundir, files["surface"])
vol_rel = files.get("volume") or find_volume_vtu(rundir)
volume = os.path.join(rundir, vol_rel) if vol_rel else ""
vtm = glob.glob(os.path.join(rundir, "VTK", "*.vtm"))
print(wall, volume or (vtm[0] if vtm else "no volume — run with volume=True"))
```

`files.volume` is `null` when the run did not use `volume=True` or when `internal.vtu` was dropped after export. Streamlines, **Slice**, **Clip**, and **Stream Tracer** need the volume file. Slice normals, origins, and stream seeding are in [README.md — Analyzing results in ParaView](README.md#analyzing-results-in-paraview) and [Slices through the flow](README.md#slices-through-the-flow).

## Results CSV columns

Aggregate and per-run `results.csv` files share this header (older partial files may omit newer columns):

`geometry`, `AoA_deg`, `speed_ms`, `Re`, `Mach`, `area_m2`, `MAC_m`, `CofR_x_m`, `CofR_y_m`, `CofR_z_m`, `iterations`, `max_iterations`, `iter_budget_pct`, `residual_worst_field`, `residual_worst_ratio`, `residual_last_met`, `Cl`, `sigma_Cl`, `Cd`, `sigma_Cd`, `Cs`, `sigma_Cs`, `CmPitch`, `sigma_Cm`, `CmRoll`, `sigma_CmRoll`, `CmYaw`, `sigma_CmYaw`, `Cl_p`, `Cl_v`, `Cd_p`, `Cd_v`, `L_over_D`, `lift_N`, `drag_N`, `moment_pitch_Nm`, `yplus_min`, `yplus_max`, `yplus_avg`, `yplus_pass`, `cells`, `nonortho_max`, `skew_max`, `converged`, `scheme`, `refs`, `profile`, `solver`, `alt_m`, `CA`, `CN`, `x_cp_m`, `static_margin`.

Values are strings (as written by CSV); use `float()` where needed. Rocket-only columns `CA`, `CN`, `x_cp_m`, `static_margin` are blank for plane and body runs.

| Column | Meaning |
|--------|---------|
| `geometry` | STL basename, `builtin<span>ft`, or `rocket_<hash>` |
| `AoA_deg`, `speed_ms`, `alt_m`, `Mach` | Flight condition. `Mach` uses ISA speed of sound at `alt_m`. |
| `Re` | Reynolds number on MAC (plane), diameter (rocket), or x-length (body) |
| `area_m2`, `MAC_m` | Reference area and length. `MAC_m` is the MAC, rocket `Lref`, or body length. |
| `CofR_x_m`, `CofR_y_m`, `CofR_z_m` | Moment center, metres |
| `iterations` | Last completed SIMPLE iteration |
| `max_iterations` | The `ITERS` / `-i` cap |
| `iter_budget_pct` | `100 * iterations / max_iterations` |
| `residual_worst_field` | Field with the largest residual/target on the last iteration (`p`, `Ux`, `k`, …) |
| `residual_worst_ratio` | That residual divided by its `residualControl` target. Below `1.0` meets the target. |
| `residual_last_met` | `yes` when every monitored field was under its target on the last iteration |
| `Cl`, `Cd`, `Cs`, `CmPitch`, `CmRoll`, `CmYaw` | **Mean** over the reporting window (converged iterations, otherwise the tail of the history). In `report.txt` these appear as **mean ± sample std dev**. |
| `sigma_*` | **Sample standard deviation** paired with the mean column (`sigma_Cl` with `Cl`, etc.) on the same window. Iteration scatter, not mesh or experimental uncertainty. Empty when `report_scatter` is false. |
| `Cl_p`, `Cd_p` | Pressure part of Cl and Cd |
| `Cl_v`, `Cd_v` | Viscous part of Cl and Cd |
| `L_over_D`, `lift_N`, `drag_N`, `moment_pitch_Nm` | Lift-to-drag and forces in newtons / newton-metres |
| `yplus_min`, `yplus_max`, `yplus_avg` | Wall y+ |
| `yplus_pass` | `yes` when averages sit in 30–300 and the minimum is at least 11 |
| `cells`, `nonortho_max`, `skew_max` | From `checkMesh` |
| `converged` | `yes` (residuals), `no` (hit the iteration cap), or `partial` |
| `scheme` | `limitedLinear` or `upwind` |
| `refs` | How area and length were chosen (`ref_source` in `case_meta.env`) |
| `profile`, `solver` | `plane` / `rocket` / `body`, and `simple` or `rho` |
| `CA`, `CN` | Rocket body axes: `CA = Cd cos α − Cl sin α`, `CN = Cd sin α + Cl cos α` (+x aft, +z up) |
| `x_cp_m` | `x_cg − Cm Lref / CN`. Blank when CN is about zero. |
| `static_margin` | `(x_cp − x_cg) / D` in calibers. Positive means the center of pressure is aft of the moment center. |

## `case_meta.env` keys (selection)

Written under each run directory; keys are uppercase strings:

| Key | Meaning |
|-----|---------|
| `PROFILE`, `GEOMETRY` | Profile and geometry name |
| `SOLVER`, `SOLVER_NAME`, `COMPRESSIBLE` | `simple` or `rho`, application name, `1` if compressible |
| `AOA`, `SPEED`, `ALT_M`, `MACH`, `RE`, `RE_LABEL` | Condition. `RE_LABEL` is `Re_MAC`, `Re_D`, or `Re_L`. |
| `RHO`, `NU` | ISA density and kinematic viscosity |
| `REF_AREA`, `REF_CHORD`, `REF_XCG`, `REF_YCG`, `REF_ZCG`, `REF_DIAMETER` | References used by the force objects |
| `REF_SOURCE`, `REF_OVERRIDE` | Where the reference came from, and whether an override replaced it |
| `CG_DEFAULT` | `1` when a rocket moment center is still mid-length |
| `COMPUTED_AREA`, `COMPUTED_CHORD`, `COMPUTED_XCG` | STL estimate before overrides |
| `TURB_INT`, `K_INF`, `W_INF` | Freestream turbulence |
| `LVL`, `LVL_FIRST`, `SURF_DX`, `LAYERS`, `CELL_EST`, `CAP_HIT` | Mesh. `LVL_FIRST` is the level before a y+ remesh. |
| `TARGET_YPLUS`, `PRED_YPLUS`, `YP_RETRIED`, `YP_PASS` | Wall spacing and whether the y+ check passed |
| `ITERS`, `SCHEME`, `STOP`, `PARTIAL` | Iteration cap and solve outcome |
| `P_TOL`, `U_TOL`, `K_TOL` | SIMPLE residual targets (`1e-5`, `1e-6`, `1e-6`) |
| `LIFT_X`, `LIFT_Z`, `DRAG_X`, `DRAG_Z` | Lift and drag unit-vector components in x and z |
| `LOG`, `CHECKMESH` | Paths to the solver log and `log.checkMesh` |

Use `read_run` or `cfd.report.load_meta(path)` to parse.

## Profiles

| Profile | Config | STL | Notes |
|---------|--------|-----|--------|
| Plane | `config/plane.conf` | Optional (built-in 3 ft default) | `span_ft` for built-in |
| Rocket | `config/rocket.conf` | Optional (built-in example) | `BODY_*`, `FIN_*`, `NOSE` |
| Body | `config/body.conf` | **Required** | Arbitrary watertight STL |

Same coordinate system and outputs as the CLI; see [README.md](README.md).

## Sweep

`sweep(cfg, aoas)` calls `run` once per angle, in order, into `cfg.out`. Mesh sizing does not depend on angle, so the mesh built for the first angle is reused. `cfg.aoa` is restored when the call returns. `cfg.remesh` follows `run`: the first angle may rebuild, and later angles reuse.

If one angle calls `die()` (process exit status 1), that angle is stored as status `failed` and the sweep continues. Ctrl+C (status 130) still stops the process. After the loop, `polar.csv` and `polar.svg` are written in the output folder. The last `summaries.jsonl` record for each angle wins. Failed angles from this call replace that record.

`print_only=True` prints each flight condition and does not write the polar.

```python
from cfd import make_config, sweep, write_polar

cfg = make_config("config/plane.conf", out="./sweep_cfd", speed=20.0)
sweep(cfg, [0, 2, 4, 6])
write_polar("./sweep_cfd")  # same files, from summaries already on disk
```

`write_polar(out_dir)` reads `summaries.jsonl` only. It does not mesh or solve. An empty folder still gets a header-only `polar.csv`.

CLI: `--aoas 0,2,4,6` is `sweep`. `--polar` is `write_polar` and does not start OpenFOAM or Docker. Pass either `-a` or `--aoas`.

## Batch and parametric studies

```python
from cfd import make_config, run, read_results

base = "config/plane.conf"
out = "./sweep_cfd"

for aoa in (0, 2, 4, 6):
    cfg = make_config(base, out=out, aoa=float(aoa), speed=20.0)
    run(cfg)

table = read_results(out)
by_aoa = {r["flight"]["aoa_deg"]: r["coefficients"]["Cl"] for r in table}
```

Meshes are reused when geometry, level, and layer count match (same rules as the shell scripts). Pass `remesh=True` to force regeneration. For angles, prefer `sweep` so a failed angle does not exit the interpreter and so `polar.csv` is written for you. A speed or altitude loop can change the mesh level, because y+ depends on Reynolds number.

## CLI equivalence

| CLI | Python |
|-----|--------|
| `./plane-foam.sh -a 6 -v 18` | `make_config("config/plane.conf", aoa=6, speed=18)` then `run(cfg)` |
| `-i 3000`, `--max-iterations 3000` | `iters=3000` or `max_iterations=3000` |
| `./foam.sh --config config/body.conf -s wing.stl` | `make_config("config/body.conf", stl="wing.stl")` |
| `--print` | `print_only=True` on config, then `run(cfg)`. Does not start Docker |
| `--aoas 0,2,4,6` | `sweep(cfg, [0, 2, 4, 6])` |
| `--polar` | `write_polar(cfg.out)`. Does not start Docker |
| `--smoke` | `smoke=True` (coarse, 80 iterations, 1 rank, 0 layers) |
| `--volume` | `volume=True` (keep `internal.vtu` for ParaView volume views) |
| `-m` | `remesh=True` |
| `-w` | `write_on_exit=True` |
| `-p` | `open_pv=True` (opens the wall `.vtp`) |
| `python3 -m cfd …` | `resolve([...])` then `run(cfg)` |

## Other modules

The names in [Public exports](#public-exports) are the stable surface. These modules are the same code the driver uses. They stay on the standard library and call `die()` on bad input.

| Module | Call it for |
|--------|-------------|
| `cfd.aero` | ISA air, the Mach switch, CA / CN, center of pressure. No OpenFOAM. |
| `cfd.config` | `resolve`, `from_mapping`, `Config` |
| `cfd.geom` | Built-in plane and rocket STLs, cleanup, reference area |
| `cfd.report` | `load_meta`, `find_surface_vtp`, `find_volume_vtu`, `write_history`, `write_polar`, and `report()` to rebuild `summary.json`, `report.txt`, `history.csv`, and `results.csv` from an existing case |
| `cfd.env` | OpenFOAM discovery and the Docker re-exec used by `python3 -m cfd` |
| `cfd.cli` | `main(argv)` — what `python3 -m cfd` runs |

Atmosphere and rocket coefficients without a solve:

```python
from cfd.aero import isa, choose_solver, body_coeffs, center_of_pressure, static_margin

air = isa(1500)                              # T, p, rho, mu, nu, a
kind, transonic = choose_solver(0.25, "auto")  # ("simple", False)
ca, cn = body_coeffs(cd=0.4, cl=0.1, aoa_deg=2.0)
x_cp = center_of_pressure(x_cg=0.5, cm=-0.2, lref=0.1, cn=cn)  # None if CN ~ 0
margin = static_margin(x_cp, x_cg=0.5, diameter=0.1)
```

`choose_solver(mach, "simple")` raises `ValueError` above Mach 0.3. `plan` and `run` turn that into `die()`.

Rebuild a report from a finished run folder (does not re-solve):

```python
from cfd.report import report

report(
    "plane_cfd/run_<name>_lvl<L>_aoa<A>_v<V>",
    "plane_cfd/run_<name>_lvl<L>_aoa<A>_v<V>/case_meta.env",
    "plane_cfd/results.csv",
)
```

`cfd.mesh.build_mesh`, `cfd.case.write_case`, and `cfd.solve.solve_case` are the three steps inside `run`. Call `run` unless you are changing how those dictionaries are written.

## Tests

API helpers that do not need OpenFOAM:

```bash
python3 -m unittest tests.test_cfd
```

`ApiTest` covers `make_config`, `read_results` on `summaries.jsonl`, and the wide-CSV fallback in `tests/data/`.

## Errors

Configuration and setup errors call `cfd.proc.die()`, which prints a message and exits with status 1. There is no exception-based error API today; run scripts in a subprocess if you need to catch failures without exiting your interpreter. `sweep` is the exception: it catches status 1 from one angle, records `failed` in `polar.csv`, and continues. Status 130 from Ctrl+C still exits.
