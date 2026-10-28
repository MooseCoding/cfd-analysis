# Mesh

`snappyHexMesh` cuts one watertight surface named `body` out of a Cartesian background mesh. Sizing lives in [cfd/geom.py](../cfd/geom.py) (`prepare`) and the dictionaries in [cfd/mesh.py](../cfd/mesh.py). The flight-condition print shows the level, the predicted y+, and the cell estimate before any OpenFOAM binary runs. See also [Concepts](concepts.md#wall-spacing) for the y+ band those sizes are aiming at.

## What the mesh is

`blockMesh` builds the far-field box. Every face of that box is the patch `farfield`. `snappyHexMesh` refines toward the STL, snaps the surface, and optionally adds prism layers. The wall patch matches `body.*`, so a multi-solid STL becomes `body`, `body_wing`, and similar names.

Feature edges come from `surfaceFeatureExtract` with an included angle of 150°. The surface refinement level is the same on the minimum and the maximum, so the whole body is refined to one level rather than a coarse/fine pair.

## Domain

`D` is the longest side of the cleaned surface bounding box. The background cell size is `dx = D / 8`.

The box starts at 3 `D` upstream of the nose and 6 `D` downstream of the tail. The side and vertical extents are 3 `D` past the body. The box is then stretched so each edge is an integer number of `dx` cells. `--print` does not list these corners; they are the `x0`…`z1` values inside the `setup` dict returned by [plan](../API.md#planning-without-openfoam).

## Background size and snappy level

Each snappy level halves the background cell. The surface spacing is `dx / 2^level`.

| `QUALITY` | Level |
|-----------|-------|
| `coarse` | 3 |
| `medium` | 4 |
| `fine` | 5 |
| `vfine` | 6 |

An empty `QUALITY` chooses a level from the y+ target. The flat-plate skin friction used for that estimate is `Cf = 0.026 / Re^(1/7)`, with Reynolds number `U Lref / ν`. Friction velocity is `U sqrt(Cf / 2)`, and the wall distance for the target y+ is `TARGET_YPLUS * ν / u_tau`. The automatic level is the smallest level whose surface spacing is near twice that wall distance, then it is capped so the cell estimate stays under `CELLCAP`.

The cell estimate is a budget, not a `checkMesh` count: background cells times `1 + 0.15 * 4^(level-2)` when the level is above 2. `checkMesh` writes the real cell count into `summary.json`.

## Near-body and wake boxes

Two searchable boxes add extra refinement inside the far-field mesh. Lengths are fractions of `D`, measured from the body bounding box.

| Box | Level | Extent |
|-----|-------|--------|
| `refNear` | one below the surface level | 0.1 `D` ahead and to the side, 0.3 `D` downstream, 0.23 `D` vertically |
| `refWake` | two below the surface level | 0.3 `D` ahead, 1.5 `D` downstream, 0.25 `D` to the side, 0.4 `D` vertically |

The level is at least 1. These boxes are not config keys. Changing them means editing `prepare` in [cfd/geom.py](../cfd/geom.py).

`locationInMesh` is a point the driver finds outside the body and inside the box, which is where snappy keeps the fluid.

## Quality and the cell cap

`MAX_COMPUTE` sets the default cell cap and, for `light`, the MPI rank count.

| Level | Cell cap | Ranks |
|-------|----------|-------|
| `light` | 1M | 2 |
| `medium` | 4M | all cores |
| `heavy` | 16M | all cores |

`CELLCAP` or `-n` overrides that one quantity. `snappyHexMesh` also has its own `maxGlobalCells` of 8,000,000 in the dictionary; the driver's estimate is what `--print` compares with the cap.

When the cap binds, `--print` says the wall spacing is coarser than the y+ target. `report.txt` repeats that with `cell cap is binding`.

`--smoke` forces `QUALITY=coarse`, which is level 3, and ignores the automatic y+ level for that run.

## Wall functions and prism layers

`LAYERS=0` leaves a single cell at the wall and expects y+ in the wall-function band (average about 30–300, minimum at least 11).

`LAYERS` greater than 0 asks snappy for that many layers on `body.*`. The first layer thickness is `TARGET_YPLUS * ν / u_tau`, the expansion ratio is 1.2, and the minimum thickness is one fifth of the first layer. With layers on, the preview prints a predicted y+ of 80. The layer thickness itself still follows `TARGET_YPLUS`.

Mesh quality limits written into the dictionary include max non-orthogonality 65° (75° on the relaxed pass) and max skewness 4.

## The y+ remesh

After a solve with automatic quality and `LAYERS=0`, the driver reads `yPlus` on the wall. If the average is outside the band, it shifts the level by `round(log2(average / 80))`, stays inside the levels the cell cap allows, and remeshes once. A second solve uses that mesh. `report.txt` records the first level and the level that was kept.

A named `QUALITY`, a prism-layer mesh, an interrupted solve, or a shift that the cap will not allow does not remesh. The y+ table in `report.txt` is still the check to read.

## When a mesh is reused

The mesh folder is `mesh_<name>_lvl<L>_lay<N>/`. It is reused when a previous `checkMesh` log contains `Mesh OK` and the geometry name, level, and layer count are unchanged. Angle of attack is not part of that name, which is why an [angle sweep](tutorial.md#angle-sweep) builds one mesh.

A built-in rocket name includes a short hash of the shape, so editing `BODY_D`, the nose, or the fins starts a new mesh. `-m` deletes the cached mesh and builds it again. Changing speed or altitude can change the automatic level, which is also a new folder.
