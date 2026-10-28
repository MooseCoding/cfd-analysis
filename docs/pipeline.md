# Pipeline

What happens between a config file and `summary.json`. User-facing steps are in the [tutorial](tutorial.md). This page is the map of the package. `AGENTS.md` is the short version of the same map for editing the repo.

## From config to report

1. Resolve settings: file, then environment, then flags.
2. Pick the solver from Mach number.
3. Build or reuse a cleaned STL and a reference area.
4. Size the mesh and, unless `--print`, run `blockMesh` and `snappyHexMesh`.
5. Write `0/`, `constant/`, and `system/`.
6. Run `simpleFoam` or `rhoSimpleFoam`.
7. Export VTK, write `summary.json`, `report.txt`, `history.csv`, and append the output folder's tables.

`plan(cfg)` stops after step 3 and returns the summary dict. It still writes the cleaned STL. `run(cfg)` is the full list and needs the OpenFOAM binaries on `PATH`.

## Configuration

[cfd/config.py](../cfd/config.py) loads `KEY=value` lines, ignoring comments. Environment variables with the same names override the file when they are already set. CLI flags override both. `make_config` and `resolve` share that order.

Unknown keys call `die()` and exit. `./plane-foam.sh` is a thin wrapper that execs `python3 -m cfd --config config/plane.conf` and appends your flags.

`--print`, `--polar`, and `--help` skip the OpenFOAM search in [cfd/env.py](../cfd/env.py). Any other invocation sources a local `etc/bashrc` or re-execs inside Docker before `run`.

## Plan

[cfd/api.py](../cfd/api.py) `plan` calls `isa` and `choose_solver` in [cfd/aero.py](../cfd/aero.py), then `prepare` in [cfd/geom.py](../cfd/geom.py). The returned dict is what `--print` displays: Mach, Reynolds number, reference, mesh estimate, and freestream `k` and `omega`. At Mach 1 and above it also warns about a bow shock. The thresholds are in [Concepts](concepts.md#mach-number-and-the-solver).

## Geometry

`prepare` reads the STL or writes a built-in one, drops degenerate triangles, scales to metres, and computes the reference. Plane area is the wing planform. Rocket diameter is the longest constant-radius stretch of the tube, ignoring solids whose names look like fins. Body area is the frontal projection.

The built-in plane is a lofted shape from `make` in [cfd/geom.py](../cfd/geom.py). The built-in rocket is `make_rocket`: an ogive, cone, or elliptical nose, a tube, and flat fins. Editing those functions changes the surface the next run will mesh.

## Mesh dictionaries

[cfd/mesh.py](../cfd/mesh.py) writes `blockMeshDict`, `snappyHexMeshDict`, and the feature-extract dictionary, then runs the binaries. A folder that already has `.mesh_ok` and a `checkMesh` log containing `Mesh OK` is copied forward instead. The rules are in [Mesh](mesh.md#when-a-mesh-is-reused).

## Case

[cfd/case.py](../cfd/case.py) writes boundary conditions, schemes, `fvSolution`, and the force function objects. Wall patches match `body.*`. Freestream velocity comes from `freestream()` in [cfd/aero.py](../cfd/aero.py). Force coefficients use the reference area, reference length, and moment center from the plan, including any `-A`, `-C`, `-X`, or `-Z` override.

Incompressible runs write kinematic pressure. Compressible runs write absolute pressure, temperature, and a perfect-gas thermophysical model. Both write `k`, `omega`, and a `Cp` function object.

## Solve

[cfd/solve.py](../cfd/solve.py) runs one rank or `mpirun`. It prints a line every 25 iterations. Ctrl+C behavior is in [Troubleshooting](troubleshooting.md#stopping-with-ctrlc).

The first attempt uses `limitedLinear` on the turbulence divergence. If that attempt does not reach `End`, and it did produce a time directory, the solution is deleted and the case is solved once with upwind. Residual convergence is the line `SIMPLE solution converged` in the log. Reaching `endTime` without that line is status `stopped`.

`sweep` in [cfd/api.py](../cfd/api.py) repeats `run` for each angle. A `die()` from one angle is caught, that angle is marked failed, and the next angle starts. Status 130 from Ctrl+C still stops the process.

## Report

[cfd/report.py](../cfd/report.py) reads the solver log, `postProcessing/forceCoeffs1/*/coefficient.dat`, y+, and `checkMesh`. It writes:

| File | Where |
|------|--------|
| `summary.json` | Run folder, and one JSON line in `summaries.jsonl` |
| `summary.csv` | Output folder, short columns |
| `report.txt` | Run folder |
| `history.csv`, `history.svg` | Run folder, every iteration |
| `results.csv` or `results_partial.csv` | Output folder, wide columns |
| `spanwise_cl.csv` or `axial_load.csv` | Run folder, when that profile's bins exist |
| `polar.csv`, `polar.svg` | Output folder, after a sweep or `--polar` |

`write_polar` reads `summaries.jsonl` and keeps the last record for each angle. Angles that failed in the current sweep replace that record with status `failed`.

## What to edit

| Change | File |
|--------|------|
| A number for one run | `config/*.conf` or a flag |
| A new flag or config key | [cfd/config.py](../cfd/config.py) |
| The built-in shape or the reference | [cfd/geom.py](../cfd/geom.py) |
| Mach switch, ISA, CA, CN | [cfd/aero.py](../cfd/aero.py) |
| Snappy or blockMesh settings | [cfd/mesh.py](../cfd/mesh.py) |
| Boundary conditions or force objects | [cfd/case.py](../cfd/case.py) |
| MPI, Ctrl+C, the upwind retry | [cfd/solve.py](../cfd/solve.py) |
| `summary.json`, history, the polar | [cfd/report.py](../cfd/report.py) |
| Docker or `bashrc` discovery | [cfd/env.py](../cfd/env.py) |
| `plan`, `run`, `sweep` | [cfd/api.py](../cfd/api.py) |

Checks that do not need OpenFOAM:

```bash
python3 -m unittest tests.test_cfd
./plane-foam.sh --print
./docs.sh --build
```
