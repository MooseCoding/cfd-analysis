# Troubleshooting

Messages below are the ones the driver prints. The matching stage in the code is in the [pipeline](pipeline.md#from-config-to-report). Normal output is described in the [tutorial](tutorial.md#read-the-numbers).

## Units

`could not detect STL units` means the body profile found more than one of m, mm, cm, in, and ft that would put the longest side between 0.05 m and 20 m. Pass `-u` with the unit the file was written in.

The plane profile instead picks the unit closest to a 3 ft span, among units that land between 0.2 m and 5 m. The rocket profile aims at `NOSE_L + BODY_L`, or at `TARGET_SIZE_M` when that is set. If the cleaned size in `--print` is off by a factor of 10 or 25.4, the unit is wrong. Set `-u` and run again. The mesh folder name will not match, so the old mesh is left unused.

## Missing STL

`profile body needs an STL` means `./foam.sh` had no `-s` and [config/body.conf](../config/body.conf) has an empty `STL`. The plane and rocket profiles can run with an empty `STL`; they build a shape.

`config not found` means `--config` did not resolve against the current directory or the repository root.

`every triangle in the STL was degenerate` means nothing survived cleanup. The file is empty or the coordinates collapsed when scaled.

## simpleFoam above Mach 0.3

`simpleFoam is incompressible and is not valid above Mach 0.3` is raised when `SOLVER=simple` and the Mach number is above 0.3. Leave `SOLVER=auto`, or set `SOLVER=rho`. The thresholds are in [Concepts](concepts.md#mach-number-and-the-solver).

## The solver stopped

`solver did not finish` means the log never reached `End` and the process was not a Ctrl+C. The last lines of `log.simpleFoam` or `log.rhoSimpleFoam` are printed above that message. Typical causes are a diverging field, a mesh `checkMesh` would already have complained about, or a shock the steady solver cannot hold.

`status` in `summary.json` is `stopped` when the iteration cap was reached without the residual targets. Raise `ITERS` or `-i`. The residual block in `report.txt` names the worst field and how many times its target it still is. A ratio below 1 meets the target.

## Upwind retry

If `limitedLinear` on the turbulence divergence does not finish, and the log already contains a time step, the driver renames that log to `log.<solver>.limitedLinear`, clears the solution, and runs once more with upwind. The warning is `limitedLinear on k/omega did not finish; retrying once with upwind`. `summary.json` and `report.txt` then show scheme `upwind`.

A second failure stops. There is no third scheme.

## y+ is outside the band

`report.txt` prints `y+ : NO` when an average is outside 30–300 or a minimum is below 11. With automatic quality and no layers, the driver may already have remeshed once. If it is still outside, the cell cap is probably holding the level down. Use `MAX_COMPUTE=heavy`, set a higher `CELLCAP`, or set `QUALITY` one step finer and accept the larger mesh. Prism layers are the other way to drop the first-cell y+.

`y+ : not written` means the `yPlus` function object produced no table. The solve may have stopped before a write.

## High Mach

At Mach 1 and above the flight-condition block warns that steady `rhoSimpleFoam` often will not settle a bow shock. The solve still starts. If it then hits the upwind retry and still fails, that warning is the reason. Lower the Mach number, or treat a non-converged `report.txt` as an unusable force. This package does not switch to an unsteady density-based solver.

## Stopping with Ctrl+C

Without `-w`, the first Ctrl+C kills the solver and the driver exits with status 130. No `summary.json` is written.

With `-w` (`WRITE_ON_EXIT=1`), the first Ctrl+C sets `stopAt writeNow`. The solver writes the current fields, the driver post-processes them, and `summary.json` has `status` `partial`. A second Ctrl+C kills the process.

During `--aoas`, a failed angle is recorded and the sweep continues. Ctrl+C stops the whole sweep.

## Partial results

`status` `partial` means the fields are from the last completed iteration. Cl and Cd are still means over the available window. `report.txt` starts with `PARTIAL RESULTS`. Those rows go to `results_partial.csv` and stay in `summaries.jsonl`. `read_results(folder, include_partial=False)` drops them.

## OpenFOAM is not on PATH

`python3 -m cfd` and the shell wrappers look for `simpleFoam` on `PATH`, then for an `etc/bashrc`, then for Docker image `opencfd/openfoam-run:2512`. `OpenFOAM is not on PATH, and Docker is not available` means all three missed.

Set `OPENFOAM_BASHRC` to the `etc/bashrc` you want, or install Docker Desktop and rerun. `CFD_FOAM_IMAGE` selects a different image.

`--print`, `--polar`, and `--help` do not start Docker. `--polar` only rebuilds `polar.csv` from runs already in the output folder. `run()` from Python does not search for OpenFOAM; the shell wrapper or `python3 -m cfd` does.
