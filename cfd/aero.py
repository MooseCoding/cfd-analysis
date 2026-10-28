"""Freestream, ISA atmosphere, and coefficient definitions. No OpenFOAM."""
import math

R_AIR = 287.058
GAMMA = 1.4


def isa(alt_m):
    """International Standard Atmosphere in the troposphere, 0 to 11 km."""
    h = float(alt_m)
    t0, p0, lapse, g = 288.15, 101325.0, 0.0065, 9.80665
    temperature = t0 - lapse * h
    pressure = p0 * (temperature / t0) ** (g / (R_AIR * lapse))
    rho = pressure / (R_AIR * temperature)
    mu = 1.458e-6 * temperature ** 1.5 / (temperature + 110.4)
    return {
        "T": temperature,
        "p": pressure,
        "rho": rho,
        "mu": mu,
        "nu": mu / rho,
        "a": math.sqrt(GAMMA * R_AIR * temperature),
    }


def freestream(speed, aoa_deg, yaw_deg=0.0):
    """+x is nose to tail. Freestream is +x before angle of attack and yaw are applied.
    Positive yaw gives the flow a +y component."""
    angle = math.radians(float(aoa_deg))
    beta = math.radians(float(yaw_deg))
    ca, sa = math.cos(angle), math.sin(angle)
    cb, sb = math.cos(beta), math.sin(beta)
    dx, dy, dz = ca * cb, sb, sa * cb            # unit flow (drag) direction
    n = math.sqrt(max(1.0 - dz * dz, 0.0))       # |z - (z.d)d|
    if n < 1e-9:
        lift = (-sa, 0.0, ca)                    # flow along z: keep the old fallback
    else:
        lift = (-dz * dx / n, -dz * dy / n, (1.0 - dz * dz) / n)
    return {
        "ca": ca,
        "sa": sa,
        "ux": float(speed) * dx,
        "uy": float(speed) * dy,
        "uz": float(speed) * dz,
        "lift": lift,
        "drag": (dx, dy, dz),
    }

def choose_solver(mach, requested):
    """Return (simple|rho, transonic). simple above Mach 0.3 is rejected."""
    mach = float(mach)
    if requested == "simple":
        if mach > 0.3:
            raise ValueError(
                "Mach is %.4f. simpleFoam is incompressible and is not valid above Mach 0.3." % mach
            )
        return "simple", False
    if requested == "rho":
        return "rho", mach >= 0.7
    if mach <= 0.3:
        return "simple", False
    return "rho", mach >= 0.7


def solver_name(kind):
    return "rhoSimpleFoam" if kind == "rho" else "simpleFoam"


def mach_note(mach):
    """Warning text at Mach 1 and above. Empty below Mach 1."""
    mach = float(mach)
    if mach < 1.0:
        return ""
    return (
        "Mach %.4f is supersonic. Steady rhoSimpleFoam often will not settle a bow shock."
        % mach
    )


def body_coeffs(cd, cl, aoa_deg):
    """Body axes: +x aft, +z up. CA is axial, CN is normal."""
    angle = math.radians(float(aoa_deg))
    ca = cd * math.cos(angle) - cl * math.sin(angle)
    cn = cd * math.sin(angle) + cl * math.cos(angle)
    return ca, cn


def center_of_pressure(x_cg, cm, lref, cn, tol=1e-6):
    """x_cp = x_cg - Cm * Lref / CN. None when CN is about zero."""
    if cn is None or not math.isfinite(cn) or abs(cn) < tol:
        return None
    if not (math.isfinite(x_cg) and math.isfinite(cm) and math.isfinite(lref)):
        return None
    return x_cg - cm * lref / cn


def static_margin(x_cp, x_cg, diameter):
    """Calibers. Positive means the center of pressure is aft of the moment center."""
    if x_cp is None or not diameter or not math.isfinite(diameter) or diameter == 0:
        return None
    if not (math.isfinite(x_cp) and math.isfinite(x_cg)):
        return None
    return (x_cp - x_cg) / diameter


def turbulence(speed, length, intensity):
    k = 1.5 * (float(intensity) * float(speed)) ** 2
    omega = math.sqrt(k) / ((0.09 ** 0.25) * float(length))
    return k, omega, k / omega
