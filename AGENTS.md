# Agent guide

Steady external-flow CFD for one watertight body: a built-in plane, a built-in rocket, or an STL. The driver is the `cfd` package (Python stdlib only). Shell wrappers exec `python3 -m cfd`. OpenFOAM dictionaries are written by Python; they are not the source of truth.

User-facing behavior, flags, and ParaView steps are in [README.md](README.md). This file is how to work in the repo.

## Safe commands

Run these from the repo root. They do not mesh or solve.

```bash
python3 -m unittest tests.test_cfd
./plane-foam.sh --print
./rocket-foam.sh --print
```

`--print` resolves the flight condition, reference quantities, and solver, then exits. `tests/test_cfd.py` does not need OpenFOAM.

A real run (`./plane-foam.sh`, `./rocket-foam.sh`, `./foam.sh`, or `python3 -m cfd`) calls `blockMesh`, `snappyHexMesh`, and `simpleFoam` or `rhoSimpleFoam`. That can take a long time and writes large case trees. Start one only when the user asked for a solve. The CLI sources a local OpenFOAM `etc/bashrc` or re-execs in `opencfd/openfoam-run:2512` via Docker. `cfd.run()` expects `simpleFoam` already on `PATH`. `./plane-foam.sh --smoke` is the short first run (coarse, 80 iterations, 1 rank).

## Entry points

| Command | Config | Profile |
|---------|--------|---------|
| `./plane-foam.sh` | `config/plane.conf` | built-in RC plane, or an STL |
| `./rocket-foam.sh` | `config/rocket.conf` | built-in ogive/tube/fins, or an STL |
| `./foam.sh -s model.stl` | `config/body.conf` unless `--config` is set | any one body; STL required |
| `./view-case.sh path/to/run_*` | — | open VTK in ParaView |
| `./docs.sh` | — | local guide and API site; does not mesh or solve |

Override order: config file, then already-set environment variables (`SPEED=15 ./plane-foam.sh`), then CLI flags. `./plane-foam.sh --config other.conf` replaces `config/plane.conf`.

Python, from the repo root (or with `PYTHONPATH` set to it):

```python
from cfd import make_config, plan, list_runs, read_results, read_run

cfg = make_config("config/plane.conf", speed=18.0, aoa=6.0, print_only=True)
summary = plan(cfg)          # geometry + reference + solver; no OpenFOAM
rows = read_results("plane_cfd")
case = read_run(list_runs("plane_cfd")[-1])
```

`make_config` keyword names are the `Config` fields (`speed`, `aoa`, `iters`), not the `KEY=value` names. `max_iterations` is an alias of `iters`. `plan` builds the cleaned STL under the output folder. `run(cfg)` is the full mesh and solve. `sweep(cfg, aoas)` repeats `run` across angles and writes `polar.csv`. Each run folder also gets `history.csv` and `history.svg` from `report`. The user-facing reference is [API.md](API.md). Longer guides are [docs/tutorial.md](docs/tutorial.md), [docs/concepts.md](docs/concepts.md), [docs/mesh.md](docs/mesh.md), [docs/troubleshooting.md](docs/troubleshooting.md), and [docs/pipeline.md](docs/pipeline.md). `./docs.sh` renders those with the README and API.

## Where to change code

| Path | Change it for |
|------|----------------|
| `config/*.conf` | Speed, angle, altitude, rocket size, mesh, output folder |
| `cfd/config.py` | Keys, defaults, CLI flags, override order |
| `cfd/geom.py` | Built-in shapes, STL cleanup, reference area and length |
| `cfd/aero.py` | ISA air, Mach switch, CA / CN / center of pressure |
| `cfd/mesh.py` | `blockMesh` / `snappyHexMesh` dictionaries |
| `cfd/case.py` | Boundary conditions, schemes, force function objects |
| `cfd/solve.py` | MPI, Ctrl+C, the one upwind retry |
| `cfd/report.py` | `summary.json`, `report.txt`, `history.csv`, `polar.csv`, and `results.csv` |
| `cfd/plot.py` | SVG charts for history and the polar |
| `cfd/env.py` | Local OpenFOAM discovery and the Docker re-exec |
| `cfd/api.py` | `plan`, `run`, `sweep`, and result readers |

Keep new code on the stdlib. Match the existing style: no type annotations, `die()` / `warn()` from `cfd.proc` for user-facing failures.

Coordinates are **+x** nose to tail, **+y** to the side, **+z** up. Freestream is +x before angle of attack. The snappy surface is named `body`.

## Generated output

Treat these as case data, not source. Edit the Python that writes them.

- `plane_cfd/`, `rocket_cfd/`, `body_cfd/` — meshes, runs, `summary.json`, `summaries.jsonl`, VTK
- `mason/` — archived runs

Those folders are gitignored. `geom_<name>/` holds the cleaned `body.stl`. `mesh_<name>_lvl<L>_lay<N>/` is reused when `checkMesh` says Mesh OK and the geometry, level, and layer count are unchanged. A built-in rocket folder name includes a short hash of the shape. `run_<name>_lvl<L>_aoa<A>_v<V>/` is the case (`_h<alt>` when altitude is not zero). Read `summary.json` in the run folder, or `summaries.jsonl` / `summary.csv` in the output folder. `report.txt` is the long write-up. Prefer `read_run` / `read_results` over parsing logs by hand. Wall VTK is kept by default (`files.surface`); `internal.vtu` stays only with `--volume` (`files.volume`). ParaView slice steps are in README § Slices through the flow.

## Solver facts

Mach uses freestream speed and the ISA atmosphere (`ALT_M`, 0 to 11 km).

| Mach | Solver |
|------|--------|
| ≤ 0.3 | `simpleFoam` |
| > 0.3 | `rhoSimpleFoam` |
| ≥ 0.7 | `rhoSimpleFoam` with `transonic yes` |

`SOLVER=simple` above Mach 0.3 raises. `SOLVER=rho` forces the compressible solver. There is no `rhoCentralFoam` path. At Mach 1 and above, `plan` and the flight-condition print warn that a bow shock may not settle; the solver does not change. Wall functions want average y+ about 30–300 and a minimum of at least 11. `LAYERS=0` is the wall-function mesh. `./view-case.sh` opens the wall `.vtp` named in `summary.json`. `--aoas` sweeps angle of attack and writes `polar.csv`. `--polar` rebuilds that file and does not mesh or solve.
