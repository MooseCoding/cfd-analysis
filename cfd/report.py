"""Force report, y+ check, and CSV history. Stdlib only."""
import json, math, os, re, sys

from .aero import body_coeffs, center_of_pressure, static_margin
from .plot import write_panels
from .proc import warn

def dot(a, b):
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]

# ----------------------------------------------------------------------- y+ ---
def read_yplus(case):
    rows = []
    root = os.path.join(case, "postProcessing")
    if not os.path.isdir(root):
        return None, []
    for dirpath, _, files in os.walk(root):
        if "yPlus.dat" not in files:
            continue
        parent = os.path.basename(os.path.dirname(dirpath))
        if "yPlus" not in parent and "yPlus" not in dirpath:
            continue
        hdr, data, _ = read_dat(os.path.join(dirpath, "yPlus.dat"))
        if not hdr or not data:
            continue
        times = [float(r[0]) for r in data]
        last = max(times)
        for r in data:
            if abs(float(r[0]) - last) > 1e-6:
                continue
            rows.append(r)
        if rows:
            return hdr, rows
    return None, []

def yplus_cmd(case, lvl, maxlvl, layers):
    lvl, maxlvl, layers = int(lvl), int(maxlvl), int(float(layers))
    hdr, rows = read_yplus(case)
    empty = {
        "YP_PASS": 0, "YP_AVG": float("nan"), "YP_MIN": float("nan"), "YP_MAX": float("nan"),
        "NEW_LVL": lvl, "YP_REASON": "no-data",
    }
    if not rows or not hdr:
        return empty
    mins, maxs, avgs = [], [], []
    for r in rows:
        nums = []
        for tok in r[1:]:
            try:
                nums.append(float(tok))
            except ValueError:
                pass
        if len(nums) >= 3:
            mins.append(nums[-3]); maxs.append(nums[-2]); avgs.append(nums[-1])
    if not avgs:
        return empty
    avg = sum(avgs)/len(avgs)
    ymin, ymax = min(mins), max(maxs)
    passed = all(30.0 <= a <= 300.0 for a in avgs) and all(m >= 11.0 for m in mins)
    if layers > 0 or passed or avg <= 0:
        new, reason = lvl, ("ok" if passed else "layers" if layers > 0 else "no-change")
    else:
        shift = int(round(math.log(avg / 80.0, 2)))
        new = max(3, min(maxlvl, lvl + shift))
        if new == lvl:
            reason = "cap" if lvl >= maxlvl and shift > 0 else "no-change"
        else:
            reason = "shift"
    return {
        "YP_PASS": 1 if passed else 0,
        "YP_AVG": avg, "YP_MIN": ymin, "YP_MAX": ymax,
        "NEW_LVL": new, "YP_REASON": reason,
    }

# -------------------------------------------------------------------- report ---
def read_dat(path):
    hdr, rows, comments = None, [], []
    if not os.path.isfile(path):
        return None, [], []
    for line in open(path, errors="replace"):
        s = line.strip()
        if not s: continue
        if s.startswith("#"):
            comments.append(s)
            t = s.lstrip("#").split()
            if t and t[0] == "Time":
                hdr = t
            continue
        if hdr:
            parts = s.split()
            if len(parts) >= len(hdr):
                rows.append(parts[:len(hdr)])
    return hdr, rows, comments

def find_dat(case, *names):
    root = os.path.join(case, "postProcessing")
    hits = []
    if not os.path.isdir(root):
        return None
    for dirpath, _, files in os.walk(root):
        for n in names:
            if n in files:
                hits.append(os.path.join(dirpath, n))
    if not hits:
        return None
    hits.sort(key=lambda p: os.path.getmtime(p))
    return hits[-1]

def load_meta(path):
    d = {}
    for line in open(path):
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s: continue
        k, v = s.split("=", 1)
        d[k.strip()] = v.strip().strip('"')
    return d

def fnum(x, bad="nan"):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return float("nan")
    return v

def stats(xs):
    xs = [float(x) for x in xs]
    n = len(xs)
    if n == 0:
        return float("nan"), float("nan"), float("nan"), float("nan")
    m = sum(xs)/n
    if n < 2:
        sig = 0.0
    else:
        sig = math.sqrt(sum((x-m)**2 for x in xs) / (n-1))
    return m, sig, min(xs), max(xs)

def fmt_pm(mean, sig):
    if not math.isfinite(mean):
        return "n/a"
    if not math.isfinite(sig):
        return "%.5f" % mean
    if sig >= 5e-5:
        return "%.5f ± %.5f" % (mean, sig)
    return "%.5f ± %.2e" % (mean, sig)


def fmt_coeff(mean, sig, scatter=True):
    if scatter:
        return fmt_pm(mean, sig)
    if not math.isfinite(mean):
        return "n/a"
    return "%.5f" % mean


def _sigma_csv(sig, scatter):
    if not scatter or not math.isfinite(sig):
        return ""
    return "%.6e" % sig

def _residual_ratios(vals, p_tol, u_tol, k_tol):
    """Per-field initial residual divided by the SIMPLE residualControl target."""
    if not vals:
        return []
    rows = []
    if "p" in vals and p_tol > 0:
        rows.append(("p", vals["p"], p_tol, vals["p"] / p_tol))
    for name in ("Ux", "Uy", "Uz"):
        if name in vals and u_tol > 0:
            rows.append((name, vals[name], u_tol, vals[name] / u_tol))
    for name in ("k", "omega"):
        if name in vals and k_tol > 0:
            rows.append((name, vals[name], k_tol, vals[name] / k_tol))
    for name in ("h", "e"):
        if name in vals and p_tol > 0:
            rows.append((name, vals[name], p_tol, vals[name] / p_tol))
    return rows


def residuals_met(vals, p_tol, u_tol, k_tol):
    need = ("Ux", "Uy", "Uz", "p", "k", "omega")
    if any(n not in vals for n in need):
        return False
    ratios = _residual_ratios(vals, p_tol, u_tol, k_tol)
    if not ratios:
        return False
    return all(r[3] < 1.0 for r in ratios)


def residual_summary(vals, p_tol, u_tol, k_tol):
    """Return ratios, worst field name, worst ratio, all targets met on this iteration."""
    ratios = _residual_ratios(vals, p_tol, u_tol, k_tol)
    if not ratios:
        return [], None, float("nan"), False
    worst = max(ratios, key=lambda item: item[3])
    return ratios, worst[0], worst[3], residuals_met(vals, p_tol, u_tol, k_tol)


def residual_series(path):
    """Ordered ``(iteration, {field: initial residual})`` pairs from a solver log."""
    series = []
    cur = None
    if not path or not os.path.isfile(path):
        return series
    rx = re.compile(r"Solving for (\w+), Initial residual = ([+\-0-9.eE]+)")
    tm = re.compile(r"^Time = (\d+)")
    for line in open(path, errors="replace"):
        match = tm.match(line)
        if match:
            cur = int(match.group(1))
            series.append((cur, {}))
            continue
        match = rx.search(line)
        if match and cur is not None and match.group(1) not in series[-1][1]:
            series[-1][1][match.group(1)] = float(match.group(2))
    return series


def parse_residuals(path, p_tol, u_tol, k_tol):
    blocks = {}
    for iteration, vals in residual_series(path):
        blocks[iteration] = vals
    if not blocks:
        return {}, None
    def ok(vals):
        return residuals_met(vals, p_tol, u_tol, k_tol)
    times = sorted(blocks)
    flags = [ok(blocks[t]) for t in times]
    start = None
    for i in range(len(flags)):
        if flags[i] and all(flags[i:]):
            start = i
            break
    t_from = None
    if times:
        if start is None:
            i0 = max(0, len(times)-50)
        else:
            i0 = start
            if len(times) - i0 < 50:
                i0 = max(0, len(times)-50)
        t_from = times[i0]
    last = blocks[times[-1]] if times else {}
    return last, t_from

def checkmesh_stats(path):
    cells, nonortho, skew = float("nan"), float("nan"), float("nan")
    if not os.path.isfile(path):
        return cells, nonortho, skew
    for line in open(path, errors="replace"):
        m = re.search(r"cells:\s+(\d+)", line)
        if m: cells = float(m.group(1))
        m = re.search(r"non-orthogonality Max:\s+([0-9.eE+-]+)", line)
        if m: nonortho = float(m.group(1))
        m = re.search(r"Max skewness = ([0-9.eE+-]+)", line)
        if m: skew = float(m.group(1))
    return cells, nonortho, skew

def series(rows, col, name):
    if name not in col:
        return []
    i = col[name]
    out = []
    for r in rows:
        try: out.append(float(r[i]))
        except ValueError: return []
    return out

def window(rows, hdr, t_from):
    if not rows or not hdr:
        return []
    if t_from is None:
        return rows[-min(50, len(rows)):]
    i = 0
    for k, r in enumerate(rows):
        if float(r[0]) + 1e-9 >= t_from:
            i = k
            break
    else:
        i = max(0, len(rows)-50)
    if len(rows) - i < min(50, len(rows)):
        i = max(0, len(rows)-min(50, len(rows)))
    return rows[i:]

def coeff_block(path, t_from):
    hdr, rows, _ = read_dat(path) if path else (None, [], [])
    if not hdr or not rows:
        return None
    use = window(rows, hdr, t_from)
    col = {n: i for i, n in enumerate(hdr)}
    out = {"n": len(use), "t0": float(use[0][0]), "t1": float(use[-1][0]), "iters": float(rows[-1][0])}
    for name in ("Cl", "Cd", "Cs", "CmPitch", "CmRoll", "CmYaw", "Cm"):
        xs = series(use, col, name)
        if xs:
            out[name] = stats(xs)
    if "CmPitch" not in out and "Cm" in out:
        out["CmPitch"] = out["Cm"]
    return out

def force_components(path, t_from, lift, drag, q, area):
    hdr, rows, _ = read_dat(path) if path else (None, [], [])
    if not hdr or not rows:
        return None
    use = window(rows, hdr, t_from)
    col = {n: i for i, n in enumerate(hdr)}
    def vecs(prefix):
        xs, ys, zs = series(use, col, prefix+"_x"), series(use, col, prefix+"_y"), series(use, col, prefix+"_z")
        if not xs: return None
        return list(zip(xs, ys, zs))
    pres, visc = vecs("pressure"), vecs("viscous")
    tot = vecs("total")
    if not pres or not visc:
        return None
    def proj(vs, direction):
        return [dot(v, direction)/(q*area) for v in vs]
    Cl_p, Cd_p = proj(pres, lift), proj(pres, drag)
    Cl_v, Cd_v = proj(visc, lift), proj(visc, drag)
    out = {
        "Cl_p": stats(Cl_p), "Cd_p": stats(Cd_p),
        "Cl_v": stats(Cl_v), "Cd_v": stats(Cd_v),
    }
    if tot:
        out["lift_N"] = stats([dot(v, lift) for v in tot])
        out["drag_N"] = stats([dot(v, drag) for v in tot])
        out["Fx"] = stats([v[0] for v in tot])
        out["Fy"] = stats([v[1] for v in tot])
        out["Fz"] = stats([v[2] for v in tot])
    return out

def moment_my(path, t_from):
    hdr, rows, _ = read_dat(path) if path else (None, [], [])
    if not hdr or not rows:
        return None
    use = window(rows, hdr, t_from)
    col = {n: i for i, n in enumerate(hdr)}
    xs = series(use, col, "total_y")
    if not xs: return None
    return stats(xs)

def _bin_forces(case, folder, axis):
    """Last-time bin forces as (coord, Fx, Fy, Fz) in newtons."""
    path = None
    root = os.path.join(case, "postProcessing")
    if os.path.isdir(root):
        cands = []
        for dirpath, _, files in os.walk(root):
            if folder not in dirpath:
                continue
            for fn in files:
                if fn.endswith(".dat"):
                    cands.append(os.path.join(dirpath, fn))
        cands.sort()
        path = cands[-1] if cands else None
    if not path:
        return []
    hdr, rows, comments = read_dat(path)
    if not hdr or not rows:
        return []
    last = rows[-1]
    col = {n: i for i, n in enumerate(hdr)}
    bins = []
    for key in col:
        m = re.match(r"patch_(\d+)_x$", key)
        if m:
            bins.append(int(m.group(1)))
    bins.sort()
    ends = []
    needle = "%s co-ords" % axis
    for c in comments:
        if needle in c:
            for tok in c.split():
                try:
                    ends.append(float(tok))
                except ValueError:
                    pass
            break
    centers = []
    if len(ends) >= 2:
        delta = ends[1] - ends[0]
        centers = [y - 0.5*delta for y in ends]
    elif len(ends) == 1:
        centers = ends
    out = []
    for i in bins:
        try:
            F = (float(last[col["patch_%d_x" % i]]),
                 float(last[col["patch_%d_y" % i]]),
                 float(last[col["patch_%d_z" % i]]))
        except (KeyError, ValueError, IndexError):
            continue
        coord = centers[i] if i < len(centers) else float("nan")
        out.append((coord, F[0], F[1], F[2]))
    return out

def spanwise(case, lift, drag, q, area):
    out = []
    for y, fx, fy, fz in _bin_forces(case, "spanLoad", "y"):
        F = (fx, fy, fz)
        cl = dot(F, lift)/(q*area) if area else float("nan")
        cd = dot(F, drag)/(q*area) if area else float("nan")
        out.append((y, cl, cd))
    return out

def axial_loads(case, q, area):
    out = []
    scale = (q*area) if area else 0.0
    for x, fx, fy, fz in _bin_forces(case, "axialLoad", "x"):
        if scale:
            out.append((x, fx/scale, fz/scale))
        else:
            out.append((x, float("nan"), float("nan")))
    return out

def yplus_table(case):
    hdr, rows = read_yplus(case)
    if not rows:
        return []
    table = []
    for r in rows:
        name, nums = None, []
        for tok in r[1:]:
            try: nums.append(float(tok))
            except ValueError:
                name = tok if name is None else name + "_" + tok
        if name and len(nums) >= 3:
            table.append((name, nums[-3], nums[-2], nums[-1]))
    return table

def csv_escape(v):
    s = str(v)
    if any(c in s for c in ",\"\n"):
        return '"' + s.replace('"', '""') + '"'
    return s

CSV_HEADER = ",".join([
    "geometry","AoA_deg","yaw_deg","speed_ms","Re","Mach","area_m2","MAC_m",    "CofR_x_m","CofR_y_m","CofR_z_m","iterations","max_iterations","iter_budget_pct",
    "residual_worst_field","residual_worst_ratio","residual_last_met",
    "Cl","sigma_Cl","Cd","sigma_Cd","Cs","sigma_Cs",
    "CmPitch","sigma_Cm","CmRoll","sigma_CmRoll","CmYaw","sigma_CmYaw",
    "Cl_p","Cl_v","Cd_p","Cd_v","L_over_D","lift_N","drag_N","moment_pitch_Nm",
    "yplus_min","yplus_max","yplus_avg","yplus_pass",
    "cells","nonortho_max","skew_max","converged","scheme","refs",
    "profile","solver","alt_m","CA","CN","x_cp_m","static_margin",
])

def append_csv(path, values, header=None):
    """Append one row. Rotate the file when an older header is in the way."""
    if header is None:
        header = CSV_HEADER
    line = ",".join(csv_escape(v) for v in values)
    if os.path.exists(path):
        with open(path) as f:
            first = f.readline().strip()
        if first and first != header:
            bak = path + ".bak"
            if os.path.exists(bak):
                bak = path + ".bak." + str(int(os.path.getmtime(path)))
            os.rename(path, bak)
            print("rotated %s -> %s (header changed)" % (path, bak), file=sys.stderr)
    new = not os.path.exists(path)
    with open(path, "a") as f:
        if new:
            f.write(header + "\n")
        f.write(line + "\n")


SUMMARY_COLUMNS = (
    "geometry", "profile", "status", "aoa_deg", "yaw_deg", "speed_m_s", "mach",    "Cl", "Cd", "L_over_D", "lift_N", "drag_N", "yplus_pass",
    "iterations", "cells", "surface",
)
SUMMARY_HEADER = ",".join(SUMMARY_COLUMNS)


def _json_num(value, ndigits=6):
    number = fnum(value, bad="nan")
    if not math.isfinite(number):
        return None
    return round(number, ndigits)


def _json_int(value):
    number = fnum(value, bad="nan")
    if not math.isfinite(number):
        return None
    return int(round(number))


def find_surface_vtp(case):
    """Wall patch under ``VTK/``, relative to ``case``. Empty when there is none."""
    vtk = os.path.join(case, "VTK")
    if not os.path.isdir(vtk):
        return ""
    found = []
    for dirpath, _, files in os.walk(vtk):
        if os.path.basename(dirpath) != "boundary":
            continue
        for name in files:
            if name.endswith(".vtp") and name != "farfield.vtp":
                found.append(os.path.join(dirpath, name))
    if not found:
        return ""

    def sort_key(path):
        name = os.path.basename(path)
        prefer = 0 if name in ("plane.vtp", "body.vtp") else 1
        time_val = -1
        for part in path.replace("\\", "/").split("/"):
            tail = part.rsplit("_", 1)[-1]
            if tail.isdigit():
                time_val = int(tail)
        return (-time_val, prefer, name)

    found.sort(key=sort_key)
    rel = os.path.relpath(found[0], case)
    return rel.replace(os.sep, "/")


def find_volume_vtu(case):
    """Volume mesh ``internal.vtu`` under ``VTK/``, relative to ``case``. Empty when there is none."""
    vtk = os.path.join(case, "VTK")
    if not os.path.isdir(vtk):
        return ""
    found = []
    for dirpath, _, files in os.walk(vtk):
        for name in files:
            if name == "internal.vtu":
                found.append(os.path.join(dirpath, name))
    if not found:
        return ""

    def sort_key(path):
        time_val = -1
        for part in path.replace("\\", "/").split("/"):
            tail = part.rsplit("_", 1)[-1]
            if tail.isdigit():
                time_val = int(tail)
        return (-time_val, path)

    found.sort(key=sort_key)
    rel = os.path.relpath(found[0], case)
    return rel.replace(os.sep, "/")


def drop_volume_vtk(case):
    """Remove ``internal.vtu`` so a run keeps the wall surface only."""
    vtk = os.path.join(case, "VTK")
    if not os.path.isdir(vtk):
        return
    for dirpath, _, files in os.walk(vtk):
        for name in files:
            if name == "internal.vtu":
                os.remove(os.path.join(dirpath, name))


def _summary_status(partial, stop):
    if partial:
        return "partial"
    if stop == "residuals":
        return "converged"
    return "stopped"


def build_summary(geometry, profile, status, flight, coefficients, quality, surface, rocket=None, volume=None):
    """One run, as a JSON-ready dict. ``rocket`` is omitted for plane and body."""
    record = {
        "geometry": geometry,
        "profile": profile,
        "status": status,
        "flight": flight,
        "coefficients": coefficients,
        "quality": quality,
        "files": {
            "surface": surface or None,
            "volume": volume or None,
            "report": "report.txt",
        },
    }
    if rocket is not None:
        record["rocket"] = rocket
    return record


def _summary_csv_row(record):
    flight = record.get("flight") or {}
    coeffs = record.get("coefficients") or {}
    quality = record.get("quality") or {}
    files = record.get("files") or {}

    def cell(value):
        if value is None:
            return ""
        return value

    return [
        record.get("geometry") or "",
        record.get("profile") or "",
        record.get("status") or "",
        cell(flight.get("aoa_deg")),
        cell(flight.get("yaw_deg")),
        cell(flight.get("speed_m_s")),
        cell(flight.get("mach")),
        cell(coeffs.get("Cl")),
        cell(coeffs.get("Cd")),
        cell(coeffs.get("L_over_D")),
        cell(coeffs.get("lift_N")),
        cell(coeffs.get("drag_N")),
        "yes" if quality.get("yplus_pass") else "no",
        cell(quality.get("iterations")),
        cell(quality.get("cells")),
        files.get("surface") or "",
    ]


def write_summary_files(case, out_dir, record):
    """``summary.json`` in the run, plus ``summaries.jsonl`` and ``summary.csv`` in ``out_dir``."""
    with open(os.path.join(case, "summary.json"), "w") as handle:
        json.dump(record, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "summaries.jsonl"), "a") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    append_csv(os.path.join(out_dir, "summary.csv"), _summary_csv_row(record), SUMMARY_HEADER)


def print_summary(case, record):
    """Short terminal banner. The long write-up stays in ``report.txt``."""
    coeffs = record.get("coefficients") or {}
    quality = record.get("quality") or {}

    def shown(value):
        if value is None:
            return "n/a"
        if isinstance(value, float):
            return "%.5f" % value
        return str(value)

    lines = [
        "Cl %s   Cd %s   L/D %s" % (shown(coeffs.get("Cl")), shown(coeffs.get("Cd")), shown(coeffs.get("L_over_D"))),
    ]
    avg = quality.get("yplus_avg")
    avg_txt = "%.1f" % avg if isinstance(avg, (int, float)) else "n/a"
    yp = "pass" if quality.get("yplus_pass") else "fail"
    lines.append("status %s   y+ %s (avg %s)" % (record.get("status") or "stopped", yp, avg_txt))
    rocket = record.get("rocket")
    if rocket:
        lines.append("CA %s   CN %s   x_cp %s   static margin %s" % (
            shown(rocket.get("CA")), shown(rocket.get("CN")),
            shown(rocket.get("x_cp_m")), shown(rocket.get("static_margin")),
        ))
    lines.append("summary  %s" % os.path.join(case, "summary.json"))
    lines.append("report   %s" % os.path.join(case, "report.txt"))
    lines.append("history  %s" % os.path.join(case, "history.csv"))
    print("\n".join(lines))

HISTORY_FIELDS = ("iteration", "p", "Ux", "Uy", "Uz", "k", "omega", "Cl", "Cd")


def _finite_num(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _sci(value):
    number = _finite_num(value)
    if number is None:
        return ""
    return "%.6e" % number


def _plain(value):
    number = _finite_num(value)
    if number is None:
        return ""
    return "%.6g" % number


def history_rows(log_path, coeff_path, p_tol, u_tol, k_tol):
    """One dict per iteration: residuals, worst residual ratio, and Cl/Cd when present."""
    series = residual_series(log_path)
    by_time = {}
    for iteration, vals in series:
        by_time[iteration] = vals
    cl_by_t, cd_by_t = {}, {}
    if coeff_path:
        hdr, rows, _comments = read_dat(coeff_path)
        if hdr and rows:
            col = {name: index for index, name in enumerate(hdr)}
            for row in rows:
                try:
                    iteration = int(float(row[0]))
                except (TypeError, ValueError):
                    continue
                if "Cl" in col:
                    cl_by_t[iteration] = _finite_num(row[col["Cl"]])
                if "Cd" in col:
                    cd_by_t[iteration] = _finite_num(row[col["Cd"]])
    times = set(by_time)
    times.update(cl_by_t)
    times.update(cd_by_t)
    out = []
    for iteration in sorted(times):
        vals = by_time.get(iteration, {})
        ratios = _residual_ratios(vals, p_tol, u_tol, k_tol)
        worst = max((item[3] for item in ratios), default=float("nan"))
        row = {"iteration": iteration, "residual_ratio": worst}
        for name in ("p", "Ux", "Uy", "Uz", "k", "omega"):
            row[name] = vals.get(name, float("nan"))
        row["Cl"] = cl_by_t.get(iteration, float("nan"))
        row["Cd"] = cd_by_t.get(iteration, float("nan"))
        out.append(row)
    return out


def _history_line(row):
    cells = [str(int(row["iteration"]))]
    for name in HISTORY_FIELDS[1:]:
        cells.append(_sci(row.get(name)))
    return ",".join(cells)


def write_history(case, rows):
    """Write ``history.csv`` and ``history.svg`` in the run folder."""
    lines = [",".join(HISTORY_FIELDS)]
    lines.extend(_history_line(row) for row in rows)
    csv_text = "\n".join(lines) + "\n"
    with open(os.path.join(case, "history.csv"), "w") as handle:
        handle.write(csv_text)
    ratio, cl = [], []
    for row in rows:
        ratio.append((row["iteration"], row.get("residual_ratio")))
        cl.append((row["iteration"], row.get("Cl")))
    write_panels(
        os.path.join(case, "history.svg"),
        [
            {
                "title": "Worst residual ratio",
                "xlabel": "iteration",
                "ylabel": "residual / target",
                "series": [("residual ratio", ratio)],
                "log_y": True,
            },
            {
                "title": "Lift coefficient",
                "xlabel": "iteration",
                "ylabel": "Cl",
                "series": [("Cl", cl)],
                "log_y": False,
            },
        ],
        note=csv_text,
    )
    return os.path.join(case, "history.csv")


def _summary_aoa(record):
    flight = record.get("flight") if isinstance(record.get("flight"), dict) else {}
    aoa = _finite_num(flight.get("aoa_deg")) if flight else None
    if aoa is None:
        aoa = _finite_num(record.get("AoA_deg"))
    return aoa


def _status_of(record):
    status = record.get("status") or ""
    if status:
        return status
    return {
        "yes": "converged",
        "no": "stopped",
        "partial": "partial",
    }.get(record.get("converged") or "", record.get("converged") or "")


def _yplus_text(record):
    quality = record.get("quality") if isinstance(record.get("quality"), dict) else {}
    flag = quality.get("yplus_pass") if quality else None
    if flag is None:
        flag = record.get("yplus_pass")
    if flag is True or flag == "yes":
        return "yes"
    if flag is False or flag == "no":
        return "no"
    return ""


POLAR_FIELDS = ("aoa_deg", "yaw_deg", "speed_m_s", "Cl", "Cd", "L_over_D",
                "status", "mach", "yplus_pass", "run")


def _summary_key(record):
    """(aoa, yaw, speed) for a summary. Old records without yaw count as yaw 0."""
    aoa = _summary_aoa(record)
    if aoa is None:
        return None
    flight = record.get("flight") if isinstance(record.get("flight"), dict) else {}
    yaw = _finite_num(flight.get("yaw_deg")) or 0.0
    speed = _finite_num(flight.get("speed_m_s"))
    if speed is None:
        speed = _finite_num(record.get("speed_ms"))
    return (round(aoa, 6), round(yaw, 6), None if speed is None else round(speed, 6))


def polar_rows(records, failed_aoas=None, runs=None):
    """One row per (aoa, yaw, speed). The last summary wins. Failures replace that case.

    ``failed_aoas`` items are (aoa, yaw, speed) tuples, or a bare angle for yaw 0.
    """
    chosen = {}
    runs = runs or {}
    for record in records:
        if not isinstance(record, dict):
            continue
        key = _summary_key(record)
        if key is None:
            continue
        flight = record.get("flight") if isinstance(record.get("flight"), dict) else {}
        coeffs = record.get("coefficients") if isinstance(record.get("coefficients"), dict) else {}
        mach = flight.get("mach") if flight else None
        if mach is None:
            mach = record.get("Mach")
        chosen[key] = {
            "aoa_deg": key[0], "yaw_deg": key[1], "speed_m_s": key[2],
            "Cl": coeffs.get("Cl", record.get("Cl")),
            "Cd": coeffs.get("Cd", record.get("Cd")),
            "L_over_D": coeffs.get("L_over_D", record.get("L_over_D")),
            "status": _status_of(record),
            "mach": mach,
            "yplus_pass": _yplus_text(record),
            "run": runs.get(key, ""),
        }
    for item in failed_aoas or []:
        if isinstance(item, (tuple, list)):
            aoa, yaw, speed = (float(v) for v in item)
            key = (round(aoa, 6), round(yaw, 6), round(speed, 6))
        else:
            aoa, yaw, speed = float(item), 0.0, None
            key = (round(aoa, 6), 0.0, None)
            for old in [k for k in chosen if k[0] == key[0] and k[1] == 0.0]:
                del chosen[old]          # old AoA-only behavior: failure replaces the angle
        chosen[key] = {
            "aoa_deg": aoa, "yaw_deg": yaw, "speed_m_s": speed,
            "Cl": None, "Cd": None, "L_over_D": None,
            "status": "failed", "mach": None, "yplus_pass": "", "run": "",
        }
    order = sorted(chosen, key=lambda k: (k[0], k[1], -1.0 if k[2] is None else k[2]))
    return [chosen[key] for key in order]

def _read_jsonl(path):
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path, errors="replace") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            try:
                rows.append(json.loads(text))
            except ValueError:
                continue
    return rows

def _polar_run_names(out_dir):
    names = {}
    times = {}
    if not os.path.isdir(out_dir):
        return names
    for name in os.listdir(out_dir):
        if not name.startswith("run_"):
            continue
        folder = os.path.join(out_dir, name)
        path = os.path.join(folder, "summary.json")
        if not os.path.isfile(path):
            continue
        try:
            with open(path) as handle:
                record = json.load(handle)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        key = _summary_key(record)
        if key is None:
            continue
        mtime = os.path.getmtime(folder)
        if key not in times or mtime >= times[key]:
            times[key] = mtime
            names[key] = name
    return names


def _polar_line(row):
    cells = [
        _plain(row.get("aoa_deg")),
        _plain(row.get("yaw_deg")),
        _plain(row.get("speed_m_s")),
        _sci(row.get("Cl")),
        _sci(row.get("Cd")),
        _sci(row.get("L_over_D")),
        row.get("status") or "",
        _plain(row.get("mach")),
        row.get("yplus_pass") or "",
        row.get("run") or "",
    ]
    return ",".join(cells)


def _polar_series(rows, field):
    """(x label, series list). x is AoA, or yaw when a single AoA is swept against yaw."""
    if len({r["aoa_deg"] for r in rows}) == 1 and len({r["yaw_deg"] for r in rows}) > 1:
        xkey, xlabel, group = "yaw_deg", "yaw, deg", ("aoa_deg", "speed_m_s")
    else:
        xkey, xlabel, group = "aoa_deg", "angle of attack, deg", ("yaw_deg", "speed_m_s")
    vary = [k for k in group if len({r[k] for r in rows}) > 1]
    names = {"aoa_deg": "aoa %g", "yaw_deg": "yaw %g", "speed_m_s": "%g m/s"}
    groups = {}
    for r in rows:
        gkey = tuple(r[k] for k in vary)
        groups.setdefault(gkey, []).append((r[xkey], r.get(field)))
    out = []
    for gkey in sorted(groups, key=lambda t: tuple(-1.0 if v is None else v for v in t)):
        label = ", ".join(names[k] % v for k, v in zip(vary, gkey) if v is not None) or field
        out.append((label, groups[gkey]))
    return xlabel, out


def write_polar(out_dir, failed_aoas=None):
    """Rebuild ``polar.csv`` and ``polar.svg`` from ``summaries.jsonl``."""
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    records = _read_jsonl(os.path.join(out_dir, "summaries.jsonl"))
    rows = polar_rows(records, failed_aoas=failed_aoas, runs=_polar_run_names(out_dir))
    lines = [",".join(POLAR_FIELDS)]
    lines.extend(_polar_line(row) for row in rows)
    csv_text = "\n".join(lines) + "\n"
    csv_path = os.path.join(out_dir, "polar.csv")
    with open(csv_path, "w") as handle:
        handle.write(csv_text)
    xlabel, cl = _polar_series(rows, "Cl")
    _, cd = _polar_series(rows, "Cd")
    write_panels(
        os.path.join(out_dir, "polar.svg"),
        [
            {"title": "Lift versus angle", "xlabel": xlabel, "ylabel": "Cl",
             "series": cl, "log_y": False},
            {"title": "Drag versus angle", "xlabel": xlabel, "ylabel": "Cd",
             "series": cd, "log_y": False},
        ],
        note=csv_text,
    )
    if not rows:
        warn("no finished runs in %s; wrote an empty polar" % out_dir)
    print("polar    %s" % csv_path)
    return csv_path

def g(meta, key, default="nan"):
    return meta.get(key, default)


def _iteration_cap(case, meta):
    try:
        n = int(float(g(meta, "ITERS", "0")))
        if n > 0:
            return n
    except ValueError:
        pass
    path = os.path.join(case, "system", "controlDict")
    if not os.path.isfile(path):
        return 0
    match = re.search(r"(?m)^endTime\s+(\d+)\s*;", open(path).read())
    return int(match.group(1)) if match else 0

def report(case, meta_path, master_csv):
    meta = load_meta(meta_path)
    scatter = g(meta, "REPORT_SCATTER", "1") not in ("0", "false", "no", "")
    results_only = g(meta, "RESULTS_ONLY", "0") in ("1", "true", "yes")
    p_tol = fnum(g(meta, "P_TOL", "1e-5"))
    u_tol = fnum(g(meta, "U_TOL", "1e-6"))
    k_tol = fnum(g(meta, "K_TOL", "1e-6"))
    last_res, t_from = parse_residuals(g(meta, "LOG", ""), p_tol, u_tol, k_tol)
    res_ratios, res_worst_field, res_worst_ratio, res_last_met = residual_summary(
        last_res, p_tol, u_tol, k_tol,
    )
    total_path = None
    root = os.path.join(case, "postProcessing")
    if os.path.isdir(root):
        cands = []
        for dirpath, _, files in os.walk(root):
            base = os.path.basename(dirpath)
            parent = os.path.basename(os.path.dirname(dirpath))
            if "coefficient.dat" in files and parent == "forceCoeffs1":
                cands.append(os.path.join(dirpath, "coefficient.dat"))
        if not cands:
            for dirpath, _, files in os.walk(root):
                if "coefficient.dat" in files and os.path.basename(os.path.dirname(dirpath)).startswith("forceCoeffs"):
                    cands.append(os.path.join(dirpath, "coefficient.dat"))
        cands.sort()
        # prefer the un-suffixed forceCoeffs1 file (shortest parent name)
        cands.sort(key=lambda p: (0 if "/forceCoeffs1/" in p.replace("\\", "/") else 1, p))
        total_path = cands[0] if cands else None
    total = coeff_block(total_path, t_from)
    rho = fnum(g(meta, "RHO")); U = fnum(g(meta, "SPEED")); area = fnum(g(meta, "REF_AREA"))
    chord = fnum(g(meta, "REF_CHORD"))
    q = 0.5*rho*U*U
    lift = (fnum(g(meta, "LIFT_X")), fnum(g(meta, "LIFT_Y", "0")), fnum(g(meta, "LIFT_Z")))
    drag = (fnum(g(meta, "DRAG_X")), fnum(g(meta, "DRAG_Y", "0")), fnum(g(meta, "DRAG_Z")))
    forces = force_components(find_dat(case, "force.dat"), t_from, lift, drag, q, area)
    my = moment_my(find_dat(case, "moment.dat"), t_from)
    patches = []
    if os.path.isdir(root):
        parents = []
        for dirpath, _, files in os.walk(root):
            if "coefficient.dat" in files:
                parent = os.path.basename(os.path.dirname(dirpath))
                if parent.startswith("coeff_"):
                    parents.append((parent[len("coeff_"):], os.path.join(dirpath, "coefficient.dat")))
        for name, path in sorted(parents):
            blk = coeff_block(path, t_from)
            if blk and "Cl" in blk:
                patches.append((name, blk))
    ytab = yplus_table(case)
    cells, nonortho, skew = checkmesh_stats(g(meta, "CHECKMESH", ""))
    profile = g(meta, "PROFILE", "plane")
    span, axial = [], []
    bin_path = ""
    if profile == "plane":
        span = spanwise(case, lift, drag, q, area)
        bin_path = os.path.join(case, "spanwise_cl.csv")
        with open(bin_path, "w") as f:
            f.write("y_m,Cl,Cd\n")
            for y, cl, cd in span:
                f.write("%.6f,%.6e,%.6e\n" % (y, cl, cd))
    elif profile == "rocket":
        axial = axial_loads(case, q, area)
        bin_path = os.path.join(case, "axial_load.csv")
        with open(bin_path, "w") as f:
            f.write("x_m,CA,CN\n")
            for x, ca_i, cn_i in axial:
                f.write("%.6f,%.6e,%.6e\n" % (x, ca_i, cn_i))

    def S(block, key):
        return block[key] if block and key in block else (float("nan"),)*4

    Cl, Cd = S(total, "Cl"), S(total, "Cd")
    Cs, Cm = S(total, "CmPitch"), S(total, "Cm")
    Cm = S(total, "CmPitch")
    CmR, CmY = S(total, "CmRoll"), S(total, "CmYaw")
    Clp, Clv = (forces["Cl_p"] if forces else (float("nan"),)*4), (forces["Cl_v"] if forces else (float("nan"),)*4)
    Cdp, Cdv = (forces["Cd_p"] if forces else (float("nan"),)*4), (forces["Cd_v"] if forces else (float("nan"),)*4)
    ld = Cl[0]/Cd[0] if (math.isfinite(Cl[0]) and math.isfinite(Cd[0]) and Cd[0] != 0) else float("nan")
    lift_N = Cl[0]*q*area if math.isfinite(Cl[0]) else float("nan")
    drag_N = Cd[0]*q*area if math.isfinite(Cd[0]) else float("nan")
    mom_N = Cm[0]*q*area*chord if math.isfinite(Cm[0]) else float("nan")
    if my:
        mom_N = my[0]
    aoa = fnum(g(meta, "AOA"))
    yaw = fnum(g(meta, "YAW", "0"))
    ca = cn = float("nan")
    xcp = margin = None
    if math.isfinite(Cl[0]) and math.isfinite(Cd[0]) and math.isfinite(aoa):
        xcg = fnum(g(meta, "REF_XCG"))
        diameter = fnum(g(meta, "REF_DIAMETER", "nan"))
        if math.isfinite(yaw) and yaw != 0.0 and forces and "Fz" in forces and q * area > 0:
            ca = forces["Fx"][0] / (q * area)   # axial force along body +x
            cn = forces["Fz"][0] / (q * area)   # pitch-plane normal force
        else:
            ca, cn = body_coeffs(Cd[0], Cl[0], aoa)
            diameter = fnum(g(meta, "REF_DIAMETER", "nan"))
        if math.isfinite(xcg) and math.isfinite(Cm[0]):
            xcp = center_of_pressure(xcg, Cm[0], chord, cn)
        if xcp is not None and math.isfinite(diameter) and diameter > 0:
            margin = static_margin(xcp, xcg, diameter)
    stop = g(meta, "STOP", "")
    partial = g(meta, "PARTIAL", "0") == "1"
    if partial:
        converged = "partial"
    elif stop == "residuals":
        converged = "yes"
    else:
        converged = "no"
    ypass = "yes" if g(meta, "YP_PASS", "0") == "1" else "no"
    if ytab:
        yp_min = min(a[1] for a in ytab)
        yp_max = max(a[2] for a in ytab)
        yp_avg = sum(a[3] for a in ytab)/len(ytab)
        ypass = "yes" if all(30 <= a[3] <= 300 and a[1] >= 11 for a in ytab) else "no"
    else:
        yp_min = yp_max = yp_avg = float("nan")

    history_rows_written = history_rows(g(meta, "LOG", ""), total_path, p_tol, u_tol, k_tol)
    write_history(case, history_rows_written)

    iters = total["iters"] if total else 0
    max_iters = _iteration_cap(case, meta)
    if max_iters > 0 and iters >= 0:
        iter_budget_pct = 100.0 * iters / max_iters
    else:
        iter_budget_pct = float("nan")

    lines = []
    A = lines.append
    A("================================ RESULTS ================================")
    if partial:
        A("  *** PARTIAL RESULTS - run was stopped early, not converged ***")
    A("  geometry     : %s" % g(meta, "GEOMETRY"))
    A("  profile      : %s" % profile)
    A("  solver       : %s" % g(meta, "SOLVER_NAME", g(meta, "SOLVER", "")))
    A("  AoA          : %s deg" % g(meta, "AOA"))
    A("  yaw          : %s deg" % g(meta, "YAW", "0"))
    A("  speed        : %s m/s" % g(meta, "SPEED"))
    A("  altitude     : %s m" % g(meta, "ALT_M", "0"))
    A("  Mach         : %s" % g(meta, "MACH"))
    A("  %-12s : %s" % (g(meta, "RE_LABEL", "Re"), g(meta, "RE")))
    A("  density      : %s kg/m^3     nu = %s m^2/s" % (g(meta, "RHO"), g(meta, "NU")))
    if profile == "plane":
        A("  wing area    : %s m^2        MAC = %s m" % (g(meta, "REF_AREA"), g(meta, "REF_CHORD")))
    elif profile == "rocket":
        A("  ref area     : %s m^2        Lref = %s m" % (g(meta, "REF_AREA"), g(meta, "REF_CHORD")))
        A("  diameter     : %s m" % g(meta, "REF_DIAMETER", "n/a"))
    else:
        A("  frontal area : %s m^2        length = %s m" % (g(meta, "REF_AREA"), g(meta, "REF_CHORD")))
    A("  moment center: (%s, %s, %s) m" % (g(meta, "REF_XCG"), g(meta, "REF_YCG"), g(meta, "REF_ZCG")))
    if profile == "rocket" and g(meta, "CG_DEFAULT", "0") == "1":
        A("  moment center is mid-length, not a measured CG. Set REF_X for a real static margin.")
    src = g(meta, "REF_SOURCE", "")
    if g(meta, "REF_OVERRIDE", "0") == "1":
        src += "  (command-line override on top of %s)" % g(meta, "REF_SOURCE", "computed")
    A("  reference    : %s" % src)
    if g(meta, "REF_OVERRIDE", "0") == "1":
        A("  STL estimate : area %s m^2, Lref %s m, x %s m" % (
            g(meta, "COMPUTED_AREA"), g(meta, "COMPUTED_CHORD"), g(meta, "COMPUTED_XCG")))
    A("  turbulence   : Tu = %s, k = %s, omega = %s" % (g(meta, "TURB_INT"), g(meta, "K_INF"), g(meta, "W_INF")))
    A("  mesh         : level %s, surface %s m, layers %s, estimated cells %s" % (
        g(meta, "LVL"), g(meta, "SURF_DX"), g(meta, "LAYERS"), g(meta, "CELL_EST")))
    A("  checkMesh    : cells %s, max non-ortho %s, max skew %s" % (
        ("%.0f" % cells) if math.isfinite(cells) else "n/a",
        ("%.3f" % nonortho) if math.isfinite(nonortho) else "n/a",
        ("%.3f" % skew) if math.isfinite(skew) else "n/a"))
    A("  target y+    : %s     predicted y+ : %s%s" % (
        g(meta, "TARGET_YPLUS"), g(meta, "PRED_YPLUS"),
        "   (cell cap is binding)" if g(meta, "CAP_HIT", "0") == "1" else ""))
    if g(meta, "YP_RETRIED", "0") == "1":
        A("  y+ retry     : remeshed once, level %s -> %s" % (g(meta, "LVL_FIRST"), g(meta, "LVL")))
    A("  scheme       : %s" % g(meta, "SCHEME"))
    A("  stop         : %s" % ("interrupted" if partial else stop or "unknown"))
    if max_iters > 0:
        A("  iteration cap: %d" % max_iters)
        if math.isfinite(iter_budget_pct):
            A("  progress     : %.0f / %d (%.1f%% of iteration budget)" % (iters, max_iters, iter_budget_pct))
            if partial:
                A("                 stopped early - not converged")
            elif stop == "residuals":
                A("                 converged before hitting the iteration cap")
            elif stop == "iterations":
                A("                 used the full iteration budget without residual convergence")
    if last_res and math.isfinite(res_worst_ratio):
        A("  residual targets: p < %g, U < %g, k/omega < %g" % (p_tol, u_tol, k_tol))
        if res_last_met:
            A("  residual progress: all fields met targets on the last iteration (<1.0x)")
            if stop not in ("residuals",) and not partial:
                A("                 OpenFOAM has not declared convergence yet (needs this held)")
        else:
            A("  residual progress: worst %s at %.2fx target (need <1.0x to meet criteria)" % (
                res_worst_field, res_worst_ratio,
            ))
    A("------------------------------------------------------------------------")
    if scatter:
        A("  coefficients : mean ± sample std dev over the reporting window")
        A("               (iteration scatter, not mesh or experimental uncertainty)")
    else:
        A("  coefficients : mean over the reporting window")
    if total:
        A("  window       : iterations %.0f to %.0f  (%d samples)" % (total["t0"], total["t1"], total["n"]))
        A("  iterations   : %.0f" % total["iters"])
        A("  Cl           : %s" % fmt_coeff(Cl[0], Cl[1], scatter))
        A("  Cd           : %s" % fmt_coeff(Cd[0], Cd[1], scatter))
        A("  Cs           : %s" % fmt_coeff(S(total, "Cs")[0], S(total, "Cs")[1], scatter))
        A("  CmPitch      : %s" % fmt_coeff(Cm[0], Cm[1], scatter))
        A("  CmRoll       : %s" % fmt_coeff(CmR[0], CmR[1], scatter))
        A("  CmYaw        : %s" % fmt_coeff(CmY[0], CmY[1], scatter))
        A("  Cl pressure  : %s     Cl viscous : %s" % (
            fmt_coeff(Clp[0], Clp[1], scatter), fmt_coeff(Clv[0], Clv[1], scatter),
        ))
        A("  Cd pressure  : %s     Cd viscous : %s" % (
            fmt_coeff(Cdp[0], Cdp[1], scatter), fmt_coeff(Cdv[0], Cdv[1], scatter),
        ))
        A("  L/D          : %s" % ("%.2f" % ld if math.isfinite(ld) else "n/a"))
        A("  lift         : %.4f N     drag : %.4f N" % (lift_N, drag_N) if math.isfinite(lift_N) else "  lift         : n/a")
        A("  pitch moment : %s N·m" % ("%.5f" % mom_N if math.isfinite(mom_N) else "n/a"))
        if profile == "rocket":
            A("  CA           : %s" % ("%.5f" % ca if math.isfinite(ca) else "n/a"))
            A("  CN           : %s" % ("%.5f" % cn if math.isfinite(cn) else "n/a"))
            A("  x_cp         : %s m" % ("%.4f" % xcp if xcp is not None and math.isfinite(xcp) else "n/a"))
            A("  static margin: %s calibers (positive = CP aft of the moment center)" % (
                "%.3f" % margin if margin is not None and math.isfinite(margin) else "n/a"))
            A("  CA = Cd cos(a) - Cl sin(a),  CN = Cd sin(a) + Cl cos(a),  +x is aft")
        if profile == "body" and forces and "Fx" in forces:
            A("  force        : Fx %.4f N   Fy %.4f N   Fz %.4f N" % (
                forces["Fx"][0], forces["Fy"][0], forces["Fz"][0]))
        if patches:
            A("  per patch    : (same area and moment center, so the parts add to the total)")
            sum_cl = 0.0
            for name, blk in patches:
                A("    %-16s Cl %s    Cd %s" % (
                    name,
                    fmt_coeff(blk["Cl"][0], blk["Cl"][1], scatter),
                    fmt_coeff(blk["Cd"][0], blk["Cd"][1], scatter),
                ))
                sum_cl += blk["Cl"][0]
            A("    sum of patch Cl = %.5f" % sum_cl)
        if profile == "plane":
            if span:
                A("  spanwise Cl  : %d bins -> spanwise_cl.csv (contributions to the aircraft Cl, Cd)" % len(span))
            else:
                A("  spanwise Cl  : no bin file (see postProcessing/spanLoad)")
        elif profile == "rocket":
            if axial:
                A("  axial load   : %d bins -> axial_load.csv" % len(axial))
            else:
                A("  axial load   : no bin file (see postProcessing/axialLoad)")
    else:
        A("  (no force coefficients found)")
    A("------------------------------------------------------------------------")
    if ytab:
        A("  y+           : %s   (wall functions want averages 30-300 and minima >= 11)" % ypass.upper())
        for name, a, b, c in ytab:
            A("    %-16s min %7.2f   max %7.2f   avg %7.2f" % (name, a, b, c))
    else:
        A("  y+           : not written")
    if res_ratios:
        A("  last initial residual vs target (ratio = residual/target, <1 meets SIMPLE residualControl):")
        order = ("p", "Ux", "Uy", "Uz", "h", "e", "k", "omega")
        by_name = {r[0]: r for r in res_ratios}
        for name in order:
            if name not in by_name:
                continue
            _, val, tol, ratio = by_name[name]
            mark = "ok" if ratio < 1.0 else "over"
            A("    %-8s %8.2e / %8.2e   %.2fx   %s" % (name, val, tol, ratio, mark))
    A("------------------------------------------------------------------------")
    surface = "" if results_only else find_surface_vtp(case)
    volume_vtu = "" if results_only else find_volume_vtu(case)
    if not results_only:
        if surface:
            A("  ParaView     : %s" % os.path.join(case, surface))
            A("                 Colour the wall patch by Cp.")
        else:
            A("  ParaView     : no wall VTK in this run")
        if g(meta, "COMPRESSIBLE", "0") == "1":
            A("                 p is absolute static pressure. Cp = (p - pInf) / (0.5 rho U^2).")
        else:
            A("                 p is kinematic, and Cp = p / (0.5 U^2) is already a field.")
        if volume_vtu:
            A("  slice        : %s" % os.path.join(case, volume_vtu))
            A("                 ParaView: open this file, Filters -> Slice, colour by |U| or U.")
        elif g(meta, "VOLUME", "0") == "1":
            A("  slice        : internal.vtu missing (foamToVTK failed or volume export was off)")
    else:
        A("  visualization: omitted (RESULTS_ONLY); summary.json and this report were kept")
    A("  this run     : %s" % os.path.join(case, "summary.json"))
    A("                 %s" % os.path.join(case, "report.txt"))
    if scatter:
        A("                 %s  (Cl, Cd, ... = mean; sigma_* = sample std dev)" % os.path.join(case, "results.csv"))
    else:
        A("                 %s  (Cl, Cd, ... = mean; sigma_* omitted)" % os.path.join(case, "results.csv"))
    A("                 %s" % os.path.join(case, "history.csv"))
    A("                 %s" % os.path.join(case, "history.svg"))
    if bin_path:
        A("                 %s" % bin_path)
    A("  all runs     : %s" % master_csv)
    A("=========================================================================")
    text = "\n".join(lines)
    with open(os.path.join(case, "report.txt"), "w") as f:
        f.write(text + "\n")

    rocket = None
    if profile == "rocket":
        rocket = {
            "CA": _json_num(ca),
            "CN": _json_num(cn),
            "x_cp_m": _json_num(xcp),
            "static_margin": _json_num(margin),
        }
    record = build_summary(
        g(meta, "GEOMETRY", ""),
        profile,
        _summary_status(partial, stop),
        {
            "aoa_deg": _json_num(g(meta, "AOA")),
            "yaw_deg": _json_num(g(meta, "YAW", "0")),
            "speed_m_s": _json_num(g(meta, "SPEED")),
            "alt_m": _json_num(g(meta, "ALT_M", "0")),
            "mach": _json_num(g(meta, "MACH")),
            "reynolds": _json_int(g(meta, "RE")),
        },
        {
            "Cl": _json_num(Cl[0]),
            "Cd": _json_num(Cd[0]),
            "L_over_D": _json_num(ld),
            "lift_N": _json_num(lift_N),
            "drag_N": _json_num(drag_N),
        },
        {
            "yplus_pass": ypass == "yes",
            "yplus_avg": _json_num(yp_avg, 4),
            "iterations": _json_int(iters),
            "cells": _json_int(cells),
        },
        surface,
        rocket,
        volume_vtu,
    )
    write_summary_files(case, os.path.dirname(os.path.abspath(master_csv)), record)
    print()
    print_summary(case, record)

    row_ok = total and math.isfinite(Cl[0]) and math.isfinite(Cd[0]) and iters >= 1
    values = [
        g(meta, "GEOMETRY"), g(meta, "AOA"), g(meta, "YAW", "0"), g(meta, "SPEED"), g(meta, "RE"), g(meta, "MACH"),
        g(meta, "REF_AREA"), g(meta, "REF_CHORD"),
        g(meta, "REF_XCG"), g(meta, "REF_YCG"), g(meta, "REF_ZCG"),
        "%.0f" % iters if total else "0",
        "%.0f" % max_iters if max_iters > 0 else "",
        "%.2f" % iter_budget_pct if math.isfinite(iter_budget_pct) else "",
        res_worst_field or "",
        "%.4f" % res_worst_ratio if math.isfinite(res_worst_ratio) else "",
        "yes" if res_last_met else "no",
        "%.6f" % Cl[0], _sigma_csv(Cl[1], scatter), "%.6f" % Cd[0], _sigma_csv(Cd[1], scatter),
        "%.6f" % S(total, "Cs")[0], _sigma_csv(S(total, "Cs")[1], scatter),
        "%.6f" % Cm[0], _sigma_csv(Cm[1], scatter),
        "%.6f" % CmR[0], _sigma_csv(CmR[1], scatter),
        "%.6f" % CmY[0], _sigma_csv(CmY[1], scatter),
        "%.6f" % Clp[0], "%.6f" % Clv[0], "%.6f" % Cdp[0], "%.6f" % Cdv[0],
        "%.4f" % ld if math.isfinite(ld) else "nan",
        "%.6f" % lift_N if math.isfinite(lift_N) else "nan",
        "%.6f" % drag_N if math.isfinite(drag_N) else "nan",
        "%.6f" % mom_N if math.isfinite(mom_N) else "nan",
        "%.4f" % yp_min if math.isfinite(yp_min) else "nan",
        "%.4f" % yp_max if math.isfinite(yp_max) else "nan",
        "%.4f" % yp_avg if math.isfinite(yp_avg) else "nan",
        ypass,
        "%.0f" % cells if math.isfinite(cells) else "nan",
        "%.4f" % nonortho if math.isfinite(nonortho) else "nan",
        "%.4f" % skew if math.isfinite(skew) else "nan",
        converged, g(meta, "SCHEME", ""), g(meta, "REF_SOURCE", ""),
        profile, g(meta, "SOLVER", ""), g(meta, "ALT_M", "0"),
        "%.6f" % ca if profile == "rocket" and math.isfinite(ca) else "",
        "%.6f" % cn if profile == "rocket" and math.isfinite(cn) else "",
        "%.6f" % xcp if profile == "rocket" and xcp is not None and math.isfinite(xcp) else "",
        "%.6f" % margin if profile == "rocket" and margin is not None and math.isfinite(margin) else "",
    ]
    if row_ok:
        run_csv = os.path.join(case, "results.csv")
        append_csv(run_csv, values)
        append_csv(master_csv, values)
    else:
        print("  (results.csv not updated: Cl/Cd were not finite)", file=sys.stderr)
