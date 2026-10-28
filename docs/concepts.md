# Concepts

How the driver turns a speed, an angle, and a body into the numbers in `summary.json`. The implementation is [cfd/aero.py](../cfd/aero.py) and the force objects in [cfd/case.py](../cfd/case.py). A run that uses these definitions is in the [tutorial](tutorial.md#read-the-numbers).

## Axes

**+x** is nose to tail, **+y** is to the side, and **+z** is up. Freestream is +x before angle of attack is applied. A positive angle raises the freestream in +z: the x-component is `U cos α` and the z-component is `U sin α`.

Lift is perpendicular to that freestream, in the x-z plane. Drag is parallel to the freestream. Side force is along +y. There is no sideslip angle in this driver.

## Atmosphere

Altitude is `ALT_M`, from 0 to 11 km. `isa()` uses the troposphere lapse: temperature falls at 0.0065 K/m from 288.15 K, pressure follows the hydrostatic relation with gas constant 287.058 J/kg/K, and viscosity is Sutherland's law. Density is `p / (R T)`. The speed of sound is `sqrt(1.4 R T)`.

At sea level that is 288.15 K, 101325 Pa, about 1.225 kg/m³, and about 340.3 m/s. A freestream of 20 m/s is Mach 0.0588. Those values are what `--print` reports as `rho`, `nu`, `T`, and `p`.

## Mach number and the solver

Mach is freestream speed divided by the speed of sound at `ALT_M`.

| Mach | What runs |
|------|-----------|
| ≤ 0.3 | `simpleFoam`. Pressure is kinematic (`p/ρ`). |
| > 0.3 | `rhoSimpleFoam`. Perfect gas, Sutherland viscosity, absolute pressure and temperature. |
| ≥ 0.7 | The same compressible solver with `transonic yes`. |
| ≥ 1 | The same solver, plus a warning. |

`SOLVER=simple` above Mach 0.3 stops the run. `SOLVER=rho` forces `rhoSimpleFoam` at any Mach and still turns `transonic` on from 0.7. `SOLVER=auto` is the table above.

At Mach 1 and above, `plan()` and the flight-condition print warn that steady `rhoSimpleFoam` often will not settle a bow shock. The run still uses that solver. This driver has no `rhoCentralFoam` path: that solver is unsteady and CFL-limited, and it does not fit this residual loop. If the bow shock will not settle, the log is the place to look, and [Troubleshooting](troubleshooting.md#high-mach) lists what the driver does next.

## Coefficients

Forces are reduced by dynamic pressure and a reference area:

`q = ½ ρ U²`

`Cl = L / (q A)` and `Cd = D / (q A)`

`L` and `D` are the force components along the lift and drag directions from the angle of attack. Reference area and length depend on the profile:

| Profile | Area | Length | Moment center, if you do not set one |
|---------|------|--------|----------------------------------------|
| Plane | Wing planform | Mean aerodynamic chord | Quarter-chord of that wing |
| Rocket | `π D² / 4` | Diameter | Mid-length of the body |
| Body | Frontal projection | Extent along x | Center of the bounding box |

`L/D` is `Cl / Cd`. Lift and drag in newtons are `Cl q A` and `Cd q A`. Pitching moment uses the moment center and the reference length: `Cm = M / (q A Lref)`.

The reported Cl and Cd are the mean over a window of iterations. The window starts at the first iteration after which every monitored residual stays under its target, and it includes at least the last 50 iterations when the history is that long. Details of the files are in the [API](../API.md#results-csv-columns).

## Rocket axes

Rocket coefficients are also written in body axes. **+x** aft, **+z** up:

`CA = Cd cos α − Cl sin α`

`CN = Cd sin α + Cl cos α`

CA is axial force, positive aft. CN is normal force, positive up.

The center of pressure along x is

`x_cp = x_cg − Cm Lref / CN`

when CN is not about zero. Static margin in calibers is

`(x_cp − x_cg) / D`

Positive means the center of pressure is aft of the moment center. The moment center is the value in `REF_X`. If that key is empty, the driver uses mid-length and `report.txt` says so. Static margin about mid-length is not the static margin about the mass center.

## A worked rocket number

Take Cd = 0.40, Cl = 0.10, and α = 2°. Then

`CA = 0.40 cos 2° − 0.10 sin 2° = 0.39627`

`CN = 0.40 sin 2° + 0.10 cos 2° = 0.11390`

With `x_cg = 0.50` m, `Cm = −0.20`, and `Lref = D = 0.1016` m (the shipped diameter):

`x_cp = 0.50 − (−0.20)(0.1016) / 0.11390 = 0.6784` m

`static margin = (0.6784 − 0.50) / 0.1016 = 1.756` calibers

The same functions are `body_coeffs`, `center_of_pressure`, and `static_margin` in [cfd/aero.py](../cfd/aero.py). The shipped geometry that uses `D = 0.1016` m is in the [tutorial](tutorial.md#built-in-rocket). Its cross-section is `π D² / 4 = 0.008107` m².

## Pressure coefficient

The solver writes a `Cp` field when the function object runs.

Incompressible `simpleFoam` stores kinematic pressure, and the field is `Cp = p / (½ U²)`.

Compressible `rhoSimpleFoam` stores absolute static pressure, and `Cp = (p − p∞) / (½ ρ∞ U²)`. `p∞` and `ρ∞` are the ISA values at `ALT_M`, also printed in `report.txt`.

## Wall spacing

`LAYERS=0` is the wall-function mesh. The k-ω SST wall functions want the average y+ on the wall in about 30–300, and the minimum at least 11. `quality.yplus_pass` is true when every wall patch meets both. `TARGET_YPLUS` (default 80) is the spacing the mesh tries to hit.

Prism layers (`LAYERS` greater than 0) set a first-layer thickness from that same target. How the level and the layer thickness are chosen is in [Mesh](mesh.md#wall-functions-and-prism-layers).

## What the scatter means

`report.txt` prints coefficients as a mean and a sample standard deviation over the reporting window. In `results.csv` the mean is `Cl` and the deviation is `sigma_Cl` (and the same pairing for Cd and the moments).

That deviation is the scatter of the coefficient from iteration to iteration inside the window. A small value means the force history was steady at the end of the run. Mesh uncertainty and the difference from a wind-tunnel measurement are separate questions; this file does not estimate them.

`--no-scatter` prints means only. The `sigma_*` columns stay in the CSV header and are left blank.
