# Tutorial

This walkthrough stays on the built-in shapes until the last section. `--print` and `plan()` do not mesh or solve. A real solve needs OpenFOAM or Docker, as described in the [guide](../README.md#requirements).

The formulas behind the numbers are in [Concepts](concepts.md). How the mesh is sized is in [Mesh](mesh.md). When a run stops, use [Troubleshooting](troubleshooting.md).

## Before a solve

From the repository root:

```bash
./plane-foam.sh --print
```

That prints the profile, angle, speed, altitude, Mach, Reynolds number, solver, reference area, reference length, and moment center. The built-in plane aims at a 3 ft span. Mach at the shipped 20 m/s, sea-level condition is about 0.059, so the solver is `simpleFoam`.

Change one value for that print without editing the file:

```bash
./plane-foam.sh --print -a 6 -v 18
```

The same check from Python, still with no OpenFOAM call:

```bash
python3 EXAMPLE_PYTHON_API.py
```

## First smoke run

```bash
./plane-foam.sh --smoke
```

`--smoke` forces a coarse mesh, 80 iterations, 1 rank, and no prism layers. It is the short first solve. A later `./plane-foam.sh` without `--smoke` uses the config again (`ITERS` 2000, `MAX_COMPUTE` medium).

The run writes under `plane_cfd/`:

| Path | What it is |
|------|------------|
| `geom_builtin3ft/body.stl` | Cleaned surface |
| `mesh_builtin3ft_lvl3_lay0/` | Mesh cache for this level and layer count |
| `run_builtin3ft_lvl3_aoa4_v20/` | This flight condition |
| `summaries.jsonl`, `summary.csv` | One line per finished run |

Open the run folder's `summary.json` first. `./view-case.sh plane_cfd/run_builtin3ft_lvl3_aoa4_v20` opens the wall surface when ParaView is installed. Slice and streamline steps are in the [guide](../README.md#analyzing-results-in-paraview).

## Read the numbers

`summary.json` is the short record. These fields are the ones to check before trusting a coefficient:

| Field | Meaning |
|-------|---------|
| `status` | `converged`, `stopped`, or `partial` |
| `flight.aoa_deg`, `flight.speed_m_s`, `flight.mach` | The condition that was solved |
| `coefficients.Cl`, `coefficients.Cd`, `coefficients.L_over_D` | Means over the reporting window |
| `quality.yplus_pass` | Wall functions in band |
| `quality.iterations`, `quality.cells` | Last iteration and `checkMesh` cell count |
| `files.surface` | Wall VTK, relative to the run folder |

`report.txt` in the same folder is the long write-up: reference source, residual targets, coefficient means, and y+ by patch. `history.csv` is Cl, Cd, and the initial residuals at every iteration. `history.svg` plots the worst residual ratio and Cl. Open the SVG in a browser.

`plane_cfd/summary.csv` is the spreadsheet of every run in that folder. The wide `results.csv` keeps the mean and the sample standard deviation in separate columns. What that deviation measures is in [Concepts](concepts.md#what-the-scatter-means).

`status` of `stopped` means the iteration cap was reached. `partial` means the run was interrupted and kept. `converged` means the solver reported that the residuals met their targets.

## Angle sweep

An angle change reuses the mesh. Speed and altitude can change the y+ target and start a new mesh, so the sweep flag is angles only.

```bash
./plane-foam.sh --smoke --aoas 0,2,4,6
```

Each angle gets its own `run_*_aoa*_v*` folder. When the loop finishes, `plane_cfd/polar.csv` and `plane_cfd/polar.svg` list Cl, Cd, and L/D against angle. One angle can fail and the others still finish; the failed angle is a row with status `failed`.

Rebuild the polar from runs already on disk, with no solve:

```bash
./plane-foam.sh --polar
```

## Built-in rocket

```bash
./rocket-foam.sh --print
```

The shipped rocket is an example: 0.1016 m diameter, 0.20 m ogive, 0.80 m tube, four fins. It is not a Cobra airframe. Reference area is the body cross-section. The moment center defaults to mid-length, about 0.50 m from the nose tip. Static margin is about that point until you set the real center of gravity:

```bash
./rocket-foam.sh --print -X 0.55
```

`-X` is `REF_X` in [config/rocket.conf](../config/rocket.conf). The report then prints CA, CN, center of pressure, and static margin in calibers. The definitions and a hand calculation are in [Concepts](concepts.md#a-worked-rocket-number).

`./rocket-foam.sh --smoke` is the short rocket solve. Axial load along x is `axial_load.csv` in the run folder when the bins were written.

## An STL, including a Cobra airframe

Any one watertight body uses `./foam.sh`. A rocket-shaped STL can also go through `./rocket-foam.sh -s`, which keeps the rocket reference (cross-section and diameter) instead of the frontal-area reference.

```bash
./foam.sh -s path/to/body.stl -u m --print
./rocket-foam.sh -s path/to/cobra.stl -u m -X 0.40 --print
```

Coordinates on the STL are **+x** nose to tail, **+y** to the side, **+z** up. `-u` is required when more than one unit would put the body in a plausible size range. `-A`, `-C`, and `-X` override area, length, and the moment center when you already know them. Empty reference keys are computed from the surface, which is the wrong wing area if the file has no solid named like a wing.

Name solids `nose`, `tube`, or `body` on a rocket STL so the diameter is taken from the tube and not from the fins. A solid whose name contains `wing` and not `tail` is the main wing for the plane profile.

## Python, without OpenFOAM

```python
from cfd import make_config, plan

cfg = make_config("config/plane.conf", speed=18.0, aoa=6.0)
info = plan(cfg)
print(info["mach"], info["solver"], info["reference"]["area_m2"])
```

`plan` writes the cleaned STL under the output folder and does not call `blockMesh`. `run(cfg)` is the full solve and needs `simpleFoam` on `PATH`. The shell wrappers are what search for an install or start Docker.

A sweep from Python is `sweep(cfg, [0, 2, 4, 6])`. It calls `run` once per angle and writes `polar.csv`. With `print_only=True` it only prints each condition. The field list, CSV columns, and `RunResult` are in the [API](../API.md#sweep).
