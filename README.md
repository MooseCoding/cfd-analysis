# External-flow CFD

One command builds a mesh and runs steady k-ω SST over a plane, a rocket, or any single watertight body. Numbers you change per run live in a config file. The driver is a small Python package, so the dictionaries and the geometry are ordinary modules.

Below Mach 0.3 the solver is incompressible `simpleFoam`. Above that it switches to compressible `rhoSimpleFoam`, and turns `transonic` on from Mach 0.7.

## Documentation site

`./docs.sh` serves this guide and the rest of the local docs at [http://127.0.0.1:8765/](http://127.0.0.1:8765/). `./docs.sh --build` only writes `site/out/`. Neither command meshes or solves.

| Page | What it covers |
|------|----------------|
| [Tutorial](docs/tutorial.md) | `--print`, a smoke run, the files to read, a rocket, an STL |
| [Concepts](docs/concepts.md) | Axes, ISA, Mach, coefficients, CA / CN, y+, scatter |
| [Mesh](docs/mesh.md) | Domain, levels, wake boxes, layers, reuse |
| [Troubleshooting](docs/troubleshooting.md) | Units, divergence, y+, Ctrl+C, Docker |
| [Pipeline](docs/pipeline.md) | Which file owns each step |
| [API](API.md) | `make_config`, `plan`, `run`, `sweep`, result files |

## Requirements

- `python3` (stdlib only)
- OpenFOAM.com v2512 for a real solve (v2012+ should work). `python3 -m cfd` and the shell wrappers find it:
  1. `simpleFoam` already on `PATH`
  2. otherwise the first `etc/bashrc` from `OPENFOAM_BASHRC`, `$WM_PROJECT_DIR`, `$FOAM_INST_DIR`, `/Volumes/OpenFOAM-*`, `~/OpenFOAM/*`, `/opt/openfoam*`, or `/usr/lib/openfoam/*`
  3. otherwise Docker image `opencfd/openfoam-run:2512` (install Docker Desktop on macOS, Linux, or Windows)

`./plane-foam.sh --print`, `plan()`, and `python3 -m unittest tests.test_cfd` do not need OpenFOAM or Docker.

On Windows, from this folder: `py -3 -m cfd --config config/plane.conf --smoke` with Docker Desktop running.

`mpirun` is used when `NPROCS` is greater than 1. Set `CFD_FOAM_IMAGE` to pin a different OpenFOAM image.

## Quick start

```bash
./plane-foam.sh --smoke          # coarse mesh, 80 iterations, 1 core
./plane-foam.sh --print          # flight condition and reference, no mesh
./plane-foam.sh                  # built-in 3 ft plane, 4 deg, 20 m/s
./rocket-foam.sh                 # example rocket, 0 deg, 30 m/s
./foam.sh -s model.stl -u m      # any other body
```

Open `summary.json` in the run folder (or `summary.csv` in the output folder). `./view-case.sh plane_cfd/run_<...>` opens the wall surface in ParaView.

`--smoke` (or `SMOKE=1`) forces `QUALITY=coarse`, `ITERS=80`, `NPROCS=1`, and `LAYERS=0`. The `MAX_COMPUTE` cell cap still applies. A run without `--smoke` is unchanged.

`./plane-foam.sh -a 6 -v 18` still overrides the config for one run. A mesh is reused when the geometry, level, and layer count are unchanged.

Edit the case in [config/plane.conf](config/plane.conf), [config/rocket.conf](config/rocket.conf), or [config/body.conf](config/body.conf). Each line is `KEY=value` with a comment. Common solver keys: `ITERS` (max SIMPLE iterations, default 2000), `SOLVER`, `TURB_INT`, `NPROCS`, `MAX_COMPUTE`. Resolved order:

1. The config file.
2. Environment variables that are already set (`SPEED=15 ./plane-foam.sh`).
3. CLI flags.

`./plane-foam.sh --config other.conf` uses that file instead of `config/plane.conf`.

## Compute budget

`MAX_COMPUTE` (alias `COMPUTE`) picks how much mesh and parallelism a run may use. Shipped configs default to `medium`. Override with `--max-compute`, `MAX_COMPUTE=light ./plane-foam.sh`, or `make_config(..., max_compute="light")`.

| Level | Estimated cell cap | MPI ranks |
|-------|-------------------|-----------|
| `light` | 1M | 2 |
| `medium` | 4M | all cores |
| `heavy` | 16M | all cores |

Set `CELLCAP` or `NPROCS` explicitly (config, environment, or `-n`) to override the preset for that quantity only.

## Profiles

Coordinates are the same for all three: **+x** nose to tail, **+y** to the side, **+z** up. Freestream is +x before angle of attack. The snappy surface is named `body`, so patches are `body` and `body_<solid>`.

**Plane.** Built-in RC plane, or an STL. Reference is wing area, mean aerodynamic chord, and the quarter-chord. The report is Cl, Cd, moments, L/D, and a spanwise load. A solid whose name contains `wing` (and not `tail`) is the main wing. Unit auto-detect still aims at about 3 ft.

**Rocket.** Built-in ogive, tube, and fins, or an STL. The built-in shape is an example (4 in diameter, about 1 m long, four fins), not a Cobra model. Change `BODY_D`, `BODY_L`, `NOSE`, and the `FIN_*` keys in [config/rocket.conf](config/rocket.conf).

Reference area is the body cross-section, `pi D^2 / 4`. Diameter comes from the longest constant-radius tube, so the fins do not set it. Named solids `nose`, `tube`, or `body` are preferred. `Lref` defaults to the diameter. The moment center defaults to mid-length; set `REF_X` to the real CG or the static margin is not about the mass center.

The report adds:

- `CA = Cd cos α − Cl sin α` and `CN = Cd sin α + Cl cos α` (+x aft, +z up)
- `x_cp = x_cg − Cm Lref / CN`
- static margin `(x_cp − x_cg) / D` in calibers. Positive means the center of pressure is aft of the moment center.
- `axial_load.csv` along x

**Body.** An STL is required. Reference area is the frontal projection, length is the extent along x, and the moment center is the box center unless you override it. The report is Fx, Fy, Fz plus Cl and Cd. If `-u` is omitted and more than one unit is plausible, the run stops and asks for `-u`.

`-A`, `-C`, `-X`, and `-Z` override area, length, and the moment center on every profile. `-C` is the MAC for a plane and `Lref` for a rocket or a body.

## Solver

Mach uses the freestream speed and the ISA atmosphere. `ALT_M` is sea level by default and can go up to 11 km.

| Mach | Solver |
|------|--------|
| ≤ 0.3 | `simpleFoam`, kinematic pressure, wall functions, one y+ remesh |
| > 0.3 | `rhoSimpleFoam`, perfect gas, Sutherland viscosity, absolute p and T |
| ≥ 0.7 | same compressible solver with `transonic yes` |

`SOLVER=simple` above Mach 0.3 is an error. `SOLVER=rho` forces the compressible solver. Coefficients use freestream dynamic pressure either way. Incompressible `Cp = p / (½ U²)`. Compressible `Cp = (p − p∞) / (½ ρ∞ U²)`.

There is no `rhoCentralFoam` mode. That solver is unsteady and CFL-limited, so it does not fit this residual loop. A strong bow shock can still fail to settle; the run retries the turbulence scheme once with upwind and then stops with the log.

## Where the code is

| File | What you change it for |
|------|------------------------|
| `config/*.conf` | Speed, angle, altitude, rocket size, mesh, output folder |
| [cfd/geom.py](cfd/geom.py) | Built-in shapes, STL cleanup, reference area |
| [cfd/case.py](cfd/case.py) | Boundary conditions, schemes, force function objects |
| [cfd/mesh.py](cfd/mesh.py) | `blockMesh` / `snappyHexMesh` |
| [cfd/solve.py](cfd/solve.py) | MPI, Ctrl+C, the upwind retry |
| [cfd/report.py](cfd/report.py) | `summary.json`, `report.txt`, and `results.csv` |
| [cfd/env.py](cfd/env.py) | Local OpenFOAM discovery and the Docker re-exec |
| [cfd/aero.py](cfd/aero.py) | ISA air, Mach switch, CA / CN / center of pressure |
| [API.md](API.md) | Python API: `make_config`, `plan`, `run`, result files |

`./plane-foam.sh` and `./rocket-foam.sh` only exec `python3 -m cfd`.

Checks that do not need OpenFOAM:

```bash
python3 -m unittest tests.test_cfd
```

## Python API

The full reference is [API.md](API.md): configuration fields, `plan` / `run` / `RunResult`, CSV columns, `case_meta.env`, and the helper modules.

Import from the `cfd` package (set `PYTHONPATH` to this repo root, same as the shell wrappers):

```python
from cfd import make_config, plan, run

cfg = make_config("config/plane.conf", speed=22.0, max_iterations=3000)
# same as iters=3000; cfg.iters and cfg.max_iterations are equivalent

preview = plan(cfg)          # no OpenFOAM; includes preview["max_iterations"]
result = run(cfg)            # full mesh + solve + report
row = result.coefficients    # Cl, Cd, L_over_D, lift_N, drag_N from summary.json
```

`from_mapping` is the same as `make_config`. `read_run`, `read_results`, and `list_runs` load existing output folders. `run()` uses OpenFOAM already on `PATH`. The shell wrappers and `python3 -m cfd` are what search for an install or start Docker.

## Output

| Profile | Default folder |
|---------|----------------|
| plane | `plane_cfd` under the repo (`cfd.config.REPO_ROOT`) |
| rocket | `rocket_cfd` under the repo |
| body | `body_cfd` under the repo |

`geom_<name>/` holds the cleaned `body.stl`. `mesh_<name>_lvl<L>_lay<N>/` is reused after `checkMesh` says Mesh OK. A built-in rocket name includes a short hash of the shape, so editing the rocket config starts a new mesh. `run_<name>_lvl<L>_aoa<A>_v<V>/` is the case (`_h<alt>` is added when altitude is not zero). Old meshes that still contain `plane.stl` are not reused.

Each run folder gets `summary.json`: flight condition, Cl, Cd, L/D, forces, y+, status (`converged`, `stopped`, or `partial`), and the relative path of the wall VTK. Rocket CA, CN, center of pressure, and static margin are under `rocket` and are omitted for a plane or a body. The output folder appends the same object to `summaries.jsonl` and a short `summary.csv` (`geometry, profile, status, aoa_deg, speed_m_s, mach, Cl, Cd, L_over_D, lift_N, drag_N, yplus_pass, iterations, cells, surface`). `read_results` loads the JSONL. The terminal prints those few lines; mesh and residual detail stays in `report.txt`.

`results.csv` is still appended for older scripts. It has one wide row per finished run, including `profile`, `solver`, `alt_m`, `max_iterations`, `iter_budget_pct`, residual columns, and, for a rocket, `CA`, `CN`, `x_cp_m`, and `static_margin`. σ on Cl and Cd is the scatter over the converged iterations, not a grid uncertainty. Partial runs (`results_partial.csv`) use the same wide columns.

Each run folder also gets `history.csv` and `history.svg`: residuals and Cl, Cd at every iteration. An angle sweep writes `polar.csv` and `polar.svg` in the output folder. `--polar` rebuilds those two files from `summaries.jsonl` and does not solve.

## Stopping a run

- Without `-w`, Ctrl+C stops the solver and keeps nothing.
- With `-w`, the first Ctrl+C asks for `writeNow` and post-processes a partial result. A second Ctrl+C kills it.

## Analyzing results in ParaView

When a run finishes (or you stop with `-w`), the driver reconstructs decomposed time directories if needed, runs `foamToVTK -latestTime`, and writes `summary.json` plus `report.txt`. The wall patches stay. `internal.vtu` is deleted unless you pass `--volume` or `VOLUME=1`. With `--results-only` or `RESULTS_ONLY=1`, VTK is skipped and the run folder is trimmed to `summary.json`, `report.txt`, `results.csv`, `case_meta.env`, optional bin CSVs, and solver logs.

| Path | What it is |
|------|------------|
| `run_<...>/summary.json` | The numbers and the surface path |
| `run_<...>/VTK/*.vtm` | Multiblock export: volume + boundary patches (when VTK was written) |
| `run_<...>/VTK/.../internal.vtu` | Volume mesh and fields (`U`, `p`, `k`, …). Kept only with `--volume` |
| `run_<...>/VTK/.../boundary/*.vtp` | Wall surface (Cp, p, yPlus) |
| `run_<...>/postProcessing/` | Force bins, `yPlus`, `wallShearStress`, etc. |

### Open the case

```bash
./plane-foam.sh -p                    # solve, then open the wall surface
./view-case.sh plane_cfd/run_<...>    # same surface, from summary.json
paraview plane_cfd/run_<...>/VTK/*.vtm   # volume + body (after --volume)
```

`summary.json` → `files.surface` is the wall path (`plane.vtp` or `body.vtp`, not `farfield.vtp`). With `--volume`, `files.volume` is the relative path to `internal.vtu`. `./view-case.sh` and `-p` open the wall only.

For slices, streamlines, and other volume views, pass **`--volume`** (or `VOLUME=1`) **before** the solve so `internal.vtu` is not deleted after `foamToVTK`. Prefer the **`.vtm`** next to the `VTK/` subfolder: it loads the internal volume and the boundary patches together. `--results-only` skips VTK entirely.

If a run finished without `--volume`, regenerate VTK from the run folder (OpenFOAM on `PATH`):

```bash
cd plane_cfd/run_<...>
reconstructPar -latestTime    # only when processor* folders exist
foamToVTK -latestTime
```

The driver deletes `internal.vtu` after export by default; copy it out before re-post-processing if you need it without solving again.

### Slices through the flow

1. Open `files.volume`, `internal.vtu`, or the `.vtm` (select the **internal** block for filters).
2. **Filters → Slice** (or **Clip** to keep one side of the domain).
3. Set **Plane** **Normal** and **Origin**. Coordinates: **+x** nose to tail, **+y** to the side, **+z** up; freestream is +x before AoA (solved **U** includes AoA).

| View | Normal | Origin (starting point) |
|------|--------|-------------------------|
| Side (flow in the plane) | `(0, 1, 0)` | Mid-body **x**, **y = 0** |
| Top / symmetry | `(0, 0, 1)` | **y = 0** on a symmetric body |
| Streamwise station | `(1, 0, 0)` | **x** at the station you want |

4. Color by **`|U|`**, **U**, **p**, or **Cp** (transonic: centerline slice, e.g. normal **+y** through **y = 0**, for shocks and expansions).
5. Optional: **Glyph** on the slice (vectors **U**) or use **Stream Tracer** (below).

### Fields to look at

**Pressure coefficient.** The solver writes a `Cp` field at each write time. In ParaView, color the wall patch by **Cp**. If `Cp` is missing (see the warning at the end of the run), color by **p** and rescale:

- Incompressible (`simpleFoam`): `Cp = p / (½ U²)` with `U` = freestream speed from the config.
- Compressible (`rhoSimpleFoam`): `p` is absolute static pressure; `Cp = (p − p∞) / (½ ρ∞ U²)` with `p∞` and `ρ∞` from the run’s altitude (also in `report.txt`).

**Flow structure (slices and cuts).** See [Slices through the flow](#slices-through-the-flow) above.

**Streamlines.** Streamlines need the volume VTK, not the wall `.vtp` alone.

1. Open the `.vtm` (or `internal.vtu`).
2. Select the **internal** block if you used a `.vtm`.
3. **Filters → Stream Tracer** (or **Stream Tracer With Custom Source**). Set **Vectors** to **U**.
4. Seed **upstream** of the body in the freestream (e.g. a **Line** or **Point Source** at large +x, outside the model). If no lines appear, move the seeds out of the solid or use **Clip** to keep only fluid cells before tracing.
5. Color lines by **|U|** or **p**. Optional: **Tube** on the tracer output for thickness; **Glyph** on a slice gives sparse arrows.

Large meshes: **Clip** or **Extract Subset** to a box around the vehicle before **Stream Tracer** so ParaView stays responsive.

**Wall resolution.** `yPlus` and `wallShearStress` are written on wall patches at write time. Color the body surface by **yPlus** to check that averages sit in the wall-function band (about 30–300; minimum at least 11). Values also appear in `report.txt` and under `postProcessing/yPlus1/` and `postProcessing/wallShear1/`.

**Aerodynamic loads (outside ParaView).** Open `summary.json` or `summary.csv`. `report.txt` still has the long write-up: coefficients are **mean ± sample std dev** over the converged iteration window by default, and the wide `results.csv` stores the mean (`Cl`, `Cd`, …) and std dev (`sigma_*`) in separate columns. Pass `--no-scatter` or `REPORT_SCATTER=0` to omit the ± scatter (means only; `sigma_*` columns stay in the wide CSV header but are left blank). Plane spanwise load and rocket axial load are exported as CSV when binning succeeded (`spanwise_cl.csv`, `axial_load.csv`).

### ParaView filters (quick reference)

| Goal | Filter | Notes |
|------|--------|--------|
| Symmetry / cut plane | **Slice**, **Clip** | Color **p**, **\|U\|**, or **Cp** on the cut |
| Pressure or speed bands | **Contour** | Useful on **p** or **\|U\|** for shocks |
| Pathlines in the flow | **Stream Tracer** | Seeds upstream; vectors **U** |
| Thick streamlines | **Tube** | Apply to Stream Tracer output |
| Arrows on a plane | **Slice** → **Glyph** | Vectors **U**; use a small scale factor |
| Wall Cp / mesh check | Wall `.vtp` or **body** from `.vtm` | **Cp**, **yPlus** |
| LIC texture (if available) | **Surface LIC** on a slice | 2D slice; vectors **U** |

### ParaView tips

- Turn on **Surface With Edges** once to confirm the snappy surface patch names (`body`, `body_wing`, …).
- Use **Find Data** on the wall patch to read Cp at a point (e.g. wing leading edge).
- Compare two angles of attack by opening two run folders and syncing the camera, or use ParaView’s **Compare** layout.
- `farfield.vtp` is the outer boundary; useful for checking inlet/outlet behavior, not for Cp on the model.
- On macOS Homebrew ParaView, an empty `case.foam` is unreliable; use the VTK paths above instead of opening the OpenFOAM case directory.

## Limits

Steady RANS, one body, external flow. Wall functions want average y+ from 30 to 300 and a minimum of at least 11. This is not a substitute for a wind tunnel.

## Command-line flags

| Flag | Meaning |
|------|---------|
| `-a DEG` | Angle of attack |
| `-v M/S` | Airspeed |
| `-s FILE` | STL |
| `-b FT` | Built-in plane span |
| `-u UNIT` | STL units |
| `-q QUAL` | `coarse`, `medium`, `fine`, `vfine` |
| `-l N` | Prism layers |
| `-i N`, `--max-iterations N` | Max SIMPLE iterations (`ITERS` in config) |
| `--max-compute LEVEL` | `light`, `medium`, or `heavy` (`MAX_COMPUTE` in config) |
| `-n N` | MPI ranks |
| `-A -C -X -Z` | Area, length, moment center x and z |
| `-m` | Rebuild the mesh |
| `-p` | Open the wall surface in ParaView |
| `-w` | Keep a partial run on Ctrl+C |
| `--smoke` | Coarse mesh, 80 iterations, 1 rank, no layers (`SMOKE=1`) |
| `--volume` | Keep volume VTK (`internal.vtu`, `.vtm`) for slices and streamlines (`VOLUME=1`). Default is the wall surface only |
| `--no-scatter` | Means only in `report.txt`; leave `sigma_*` blank in `results.csv` |
| `--results-only` | No ParaView/VTK; delete OpenFOAM fields after the results report |
| `--aoas LIST` | Comma-separated angles. One mesh, one solve each. Writes `polar.csv` and `polar.svg` |
| `--polar` | Rebuild `polar.csv` and `polar.svg` from finished runs. Does not mesh or solve |
| `--print` | Resolve and exit |
| `--config FILE` | Use this config instead of the wrapper's file |
