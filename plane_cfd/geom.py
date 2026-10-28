#!/usr/bin/env python3
"""Geometry, mesh sizing, and the force report for plane-foam.sh. Stdlib only."""
import math, os, re, struct, sys

def sub(a, b):   return (a[0]-b[0], a[1]-b[1], a[2]-b[2])
def cross(a, b): return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
def dot(a, b):   return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]
def mean(p):
    n = len(p)
    return tuple(sum(q[i] for q in p)/n for i in range(3))

def emit(k, v):
    if isinstance(v, str):
        print('%s="%s"' % (k, v.replace('"', "")))
    elif isinstance(v, int) and not isinstance(v, bool):
        print("%s=%d" % (k, v))
    else:
        print("%s=%.8g" % (k, float(v)))

def vec(p):
    return '"(%s)"' % " ".join("%.6f" % x for x in p)

# ---------------------------------------------------------------- geometry ---
def naca4(code, n=36, x_te=0.985):
    m = int(code[0])/100.0; p = int(code[1])/10.0; t = int(code[2:])/100.0
    yt = lambda x: 5*t*(0.2969*math.sqrt(x) - 0.1260*x - 0.3516*x*x + 0.2843*x**3 - 0.1015*x**4)
    def camber(x):
        if m == 0 or p == 0: return 0.0, 0.0
        if x < p: return m/p**2*(2*p*x - x*x), 2*m/p**2*(p - x)
        return m/(1-p)**2*((1-2*p) + 2*p*x - x*x), 2*m/(1-p)**2*(p - x)
    up, lo = [], []
    for i in range(n+1):
        x = x_te*0.5*(1 - math.cos(math.pi*i/n))
        y = yt(x); yc, dy = camber(x); th = math.atan(dy)
        up.append((x - y*math.sin(th), yc + y*math.cos(th)))
        lo.append((x + y*math.sin(th), yc - y*math.cos(th)))
    loop = up + lo[:0:-1]
    return [(px/x_te, pz/x_te) for px, pz in loop]

def loft(sections):
    a, b = sections[0], sections[1]
    n = cross(sub(a[1], a[0]), sub(b[0], a[0]))
    if dot(n, sub(mean([a[0], a[1], b[0]]), mean(a))) < 0:
        sections = [s[::-1] for s in sections]
    N = len(sections[0]); tris = []
    for a, b in zip(sections[:-1], sections[1:]):
        for i in range(N):
            j = (i+1) % N
            tris.append((a[i], a[j], b[j])); tris.append((a[i], b[j], b[i]))
    for sec, first in ((sections[0], True), (sections[-1], False)):
        c = mean(sec)
        for i in range(N):
            p, q = sec[i], sec[(i+1) % N]
            tris.append((c, q, p) if first else (c, p, q))
    vol = sum(dot(a, cross(b, c)) for a, b, c in tris)/6.0
    return tris if vol > 0 else [(a, c, b) for a, b, c in tris]

def write_stl(path, solids):
    with open(path, "w") as f:
        for name, tris in solids.items():
            f.write("solid %s\n" % name)
            for a, b, c in tris:
                n = cross(sub(b, a), sub(c, a)); l = math.sqrt(dot(n, n))
                if l < 1e-14: continue
                n = (n[0]/l, n[1]/l, n[2]/l)
                f.write(" facet normal %.6e %.6e %.6e\n  outer loop\n" % n)
                for v in (a, b, c): f.write("   vertex %.6e %.6e %.6e\n" % v)
                f.write("  endloop\n endfacet\n")
            f.write("endsolid %s\n" % name)

def make(path, span_ft):
    b = float(span_ft)*0.3048
    S = {}
    L, R, nose, t0, rt = 0.70, 0.045, 0.16, 0.38, 0.010
    def rf(x):
        if x < nose:  r = R*math.sqrt(max(0.0, 1-((nose-x)/nose)**2))
        elif x < t0:  r = R
        else:
            u = (x-t0)/(L-t0); r = rt + (R-rt)*0.5*(1+math.cos(math.pi*u))
        return max(r, 0.002)
    xs = [nose*(1-math.cos(0.5*math.pi*i/12)) for i in range(13)]
    xs += [nose + (L-nose)*i/24 for i in range(1, 25)]
    K = 32
    S["fuselage"] = loft([[(x, rf(x)*math.cos(2*math.pi*k/K), rf(x)*math.sin(2*math.pi*k/K))
                           for k in range(K)] for x in xs])
    cr, ct, xqc = 0.18, 0.12, 0.28
    af = naca4("2412")
    def wing(y):
        c = ct + (cr-ct)*(1-abs(y)/(b/2)); xle = xqc - 0.25*c
        return [(xle + c*px, y, c*pz) for px, pz in af]
    S["wing"] = loft([wing(-b/2 + b*i/12) for i in range(13)])
    sa = naca4("0009"); ch, bt = 0.10, 0.30
    S["htail"] = loft([[(0.56 + ch*px, y, 0.010 + ch*pz) for px, pz in sa]
                       for y in [-bt/2 + bt*i/8 for i in range(9)]])
    def fin(z):
        u = z/0.13; c = 0.12 - 0.05*u; xle = 0.56 + 0.04*u
        return [(xle + c*px, c*pz, z) for px, pz in sa]
    S["fin"] = loft([fin(0.13*i/6) for i in range(7)])
    write_stl(path, S)

def _binary_tris(data):
    n = struct.unpack_from("<I", data, 80)[0]
    out, off = [], 84
    for _ in range(n):
        v = struct.unpack_from("<12f", data, off); off += 50
        out.append((v[3:6], v[6:9], v[9:12]))
    return out

def _ascii_solids(data):
    text = data.decode("utf-8", "replace")
    solids, name, verts = {}, None, []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("solid ") or s == "solid":
            parts = s.split(None, 1)
            name = parts[1] if len(parts) > 1 else "plane"
            solids.setdefault(name, [])
            verts = []
        elif s.startswith("endsolid"):
            name = None
            verts = []
        elif s.startswith("facet"):
            verts = []
        elif s.startswith("vertex") and name is not None:
            q = s.split()
            verts.append((float(q[1]), float(q[2]), float(q[3])))
            if len(verts) == 3:
                solids[name].append(tuple(verts))
                verts = []
    return solids

def read_solids(path):
    data = open(path, "rb").read()
    head = data.lstrip()[:2000]
    if head.startswith(b"solid") and b"facet" in head:
        solids = _ascii_solids(data)
    elif len(data) >= 84:
        n = struct.unpack_from("<I", data, 80)[0]
        if n > 0 and len(data) == 84 + 50*n:
            solids = {"plane": _binary_tris(data)}
        else:
            solids = _ascii_solids(data)
    else:
        solids = _ascii_solids(data)
    if not any(solids.values()):
        sys.exit("could not read any triangles from %s" % path)
    return solids

def all_pts(solids):
    return [p for tris in solids.values() for t in tris for p in t]

def extent_of(pts):
    return max(max(p[i] for p in pts) - min(p[i] for p in pts) for i in range(3))

def bounds(pts):
    lo = [min(p[i] for p in pts) for i in range(3)]
    hi = [max(p[i] for p in pts) for i in range(3)]
    return lo, hi

def degenerate(tri, eps):
    a, b, c = tri
    if dot(sub(b, a), sub(b, a)) < eps*eps: return True
    if dot(sub(c, b), sub(c, b)) < eps*eps: return True
    if dot(sub(a, c), sub(a, c)) < eps*eps: return True
    n = cross(sub(b, a), sub(c, a))
    return dot(n, n) < eps*eps

def scale_tri(tri, f):
    return tuple(tuple(c*f for c in v) for v in tri)

def choose_scale(extent, units):
    table = (("m", 1.0), ("mm", 0.001), ("cm", 0.01), ("in", 0.0254), ("ft", 0.3048))
    if units and units != "auto":
        for name, f in table:
            if units == name:
                return name, f
        sys.exit("unknown unit '%s' (use m, mm, cm, in or ft)" % units)
    target = 3*0.3048
    cands = []
    for name, f in table:
        L = extent * f
        if 0.2 <= L <= 5.0:
            cands.append((abs(L - target), name, f, L))
    if not cands:
        sys.exit("could not detect STL units: largest side is %.4g. Pass -u m|mm|cm|in|ft" % extent)
    cands.sort()
    _, name, f, L = cands[0]
    print("units: %s  (largest side %.4g -> %.4g m)" % (name, extent, L), file=sys.stderr)
    return name, f

def horiz(tris, nz=0.7):
    out = []
    for a, b, c in tris:
        n = cross(sub(b, a), sub(c, a))
        l2 = dot(n, n)
        if l2 < 1e-20: continue
        if abs(n[2]) / math.sqrt(l2) >= nz:
            out.append((a, b, c))
    return out

def is_wing_name(name):
    s = name.lower()
    return "wing" in s and "tail" not in s

def planform_area(tris):
    """Half the |z|-projected area of mostly-horizontal triangles (top + bottom)."""
    return 0.25 * sum(abs(cross(sub(b, a), sub(c, a))[2]) for a, b, c in tris)

TARGET_YP = 80

def _strip_bins(tris, body_pts, nb=48):
    ys = [p[1] for t in tris for p in t]
    ymin, ymax = min(ys), max(ys)
    span = ymax - ymin
    if span <= 1e-9:
        return None
    bx0 = min(p[0] for p in body_pts); bx1 = max(p[0] for p in body_pts)
    body_L = max(bx1 - bx0, 1e-9)
    width = span / nb
    groups = [[] for _ in range(nb)]
    for t in tris:
        y = (t[0][1] + t[1][1] + t[2][1]) / 3.0
        i = int((y - ymin) / width)
        if i >= nb: i = nb - 1
        if i < 0: i = 0
        groups[i].append(t)
    recs = []
    for i, g in enumerate(groups):
        if not g:
            recs.append({"kind": "empty", "c": 0.0, "c_plan": 0.0, "S": 0.0,
                         "xle": 0.0, "z": 0.0, "xc": 0.0, "i": i})
            continue
        xs, zs = [], []
        S_plan = 0.25 * sum(abs(cross(sub(b, a), sub(c, a))[2]) for a, b, c in g)
        for a, b, c in g:
            xs.extend((a[0], b[0], c[0])); zs.extend((a[2], b[2], c[2]))
        c_ext = max(xs) - min(xs)
        xle = min(xs)
        c_plan = S_plan / width if width > 0 else 0.0
        recs.append({
            "kind": "occ", "c": c_ext, "c_plan": c_plan, "S": S_plan,
            "xle": xle, "z": 0.5*(min(zs)+max(zs)),
            "xc": 0.5*(min(xs)+max(xs)), "i": i,
        })
    return recs, width, body_L, bx0, ymin, ymax

def _span_bins_wing(recs, width, body_L, bx0):
    """Wing strips: short-chord span, forward fuse root, no fuse bridging."""
    cut = 0.45 * body_L
    shorts = []
    for r in recs:
        if r["kind"] != "occ":
            continue
        if r["c"] <= 0.01 * body_L:
            r["kind"] = "empty"
        elif r["c"] >= cut:
            r["kind"] = "fuse"
        else:
            r["kind"] = "short"
            shorts.append(r)
    split = None
    if len(shorts) >= 2:
        shorts_xc = sorted(shorts, key=lambda r: r["xc"])
        best = 0.0
        for a, b in zip(shorts_xc, shorts_xc[1:]):
            gap = b["xc"] - a["xc"]
            if gap > best:
                best, split = gap, 0.5 * (a["xc"] + b["xc"])
        if best < 0.04 * body_L:
            split = None
    if split is not None:
        for r in shorts:
            r["kind"] = "wing" if r["xc"] < split else "tail"
    else:
        xles = sorted(r["xle"] for r in shorts)
        thr = xles[int(0.70 * len(xles))] if xles else 0.0
        for r in shorts:
            r["kind"] = "tail" if r["xle"] > thr else "wing"
    wing_short = [r for r in recs if r["kind"] == "wing"]
    c_ref = 0.0
    if wing_short:
        c_ref = sorted(r["c_plan"] for r in wing_short)[len(wing_short) // 2]
    x_root = bx0 + 0.22 * body_L
    x_wfuse = bx0 + 0.42 * body_L
    strips = []
    for r in wing_short:
        strips.append({
            "c": r["c"], "xle": r["xle"], "z": r["z"],
            "S": r["c"] * width, "role": "short",
        })
    for r in recs:
        if r["kind"] != "fuse":
            continue
        if r["xle"] <= x_root:
            c = min(r["c_plan"], c_ref) if c_ref > 0 else r["c_plan"]
            strips.append({
                "c": c, "xle": r["xle"], "z": r["z"],
                "S": c * width, "role": "root",
            })
        elif r["c_plan"] > 0 and r["c"] > 0 and r["c_plan"] / r["c"] < 0.65 and r["xle"] < x_wfuse:
            c = r["c_plan"]
            strips.append({
                "c": c, "xle": r["xle"], "z": r["z"],
                "S": c * width, "role": "side",
            })
    if not strips:
        return None
    S = sum(s["S"] for s in strips)
    if S <= 1e-8:
        return None
    mac = sum(s["c"]**2 * width for s in strips) / S
    xqc = sum((s["xle"] + 0.25 * s["c"]) * s["S"] for s in strips) / S
    zc = sum(s["z"] * s["S"] for s in strips) / S
    return S, mac, xqc, zc, strips

def bin_reference(tris, body_pts, mode):
    """Planform from spanwise strips. mode named-wing keeps every occupied strip.
    mode span-bins splits fuselage (long chord) from wing and tail (short chord)."""
    if len(tris) < 4:
        return None
    packed = _strip_bins(tris, body_pts)
    if packed is None:
        return None
    recs, width, body_L, bx0, ymin, ymax = packed
    if mode == "named-wing":
        for r in recs:
            if r["kind"] == "occ" and r["c"] > 0:
                r["kind"] = "wing"
        wing = [r for r in recs if r["kind"] == "wing" and r["c"] > 0]
        if not wing:
            return None
        S = planform_area(tris)
        if S <= 1e-8:
            return None
        mac = sum(r["c"]**2 * width for r in wing) / sum(r["c"] * width for r in wing)
        xqc = sum((r["xle"] + 0.25*r["c"]) * r["c"] * width for r in wing) / sum(r["c"] * width for r in wing)
        zc = sum(r["z"] * r["c"] * width for r in wing) / sum(r["c"] * width for r in wing)
        yref = 0.0 if ymin < 0.0 < ymax else sum((ymin + (r["i"]+0.5)*width) * r["c"] * width for r in wing) / sum(r["c"] * width for r in wing)
    else:
        wing_data = _span_bins_wing(recs, width, body_L, bx0)
        if wing_data is None:
            return None
        S, mac, xqc, zc, _ = wing_data
        yref = 0.0 if ymin < 0.0 < ymax else 0.5 * (ymin + ymax)
    def nkind(k):
        return sum(1 for r in recs if r["kind"] == k)
    return {
        "area": S, "chord": mac, "x": xqc, "y": yref, "z": zc,
        "wing": nkind("wing"), "fuse": nkind("fuse"), "tail": nkind("tail"),
        "source": "named-wing" if mode == "named-wing" else "span-bins",
    }

def fallback_reference(tris):
    if not tris:
        return None
    area = sum(abs(cross(sub(b, a), sub(c, a))[2]) * 0.5 for a, b, c in tris) / 2.0
    pts = [p for t in tris for p in t]
    lo, hi = bounds(pts)
    span = hi[1] - lo[1]
    if area <= 1e-8 or span <= 1e-8:
        return None
    print("wing/tail split failed; using the whole-body planform projection", file=sys.stderr)
    return {
        "area": area, "chord": area/span, "x": 0.5*(lo[0]+hi[0]), "y": 0.0 if lo[1] < 0 < hi[1] else 0.5*(lo[1]+hi[1]),
        "z": 0.5*(lo[2]+hi[2]), "wing": 0, "fuse": 0, "tail": 0, "source": "fallback-projection",
    }

def reference(solids):
    all_tris = [t for tris in solids.values() for t in tris]
    pts = [p for t in all_tris for p in t]
    wing_tris = [t for name, tris in solids.items() if is_wing_name(name) for t in tris]
    if wing_tris:
        wh = horiz(wing_tris)
        ref = bin_reference(wh if wh else wing_tris, pts, "named-wing")
    else:
        ref = None
    if ref is None:
        ref = bin_reference(horiz(all_tris), pts, "span-bins")
    if ref is None:
        ref = fallback_reference(horiz(all_tris) or all_tris)
    if ref is None:
        sys.exit("could not compute a wing reference from the STL")
    print("reference: %(source)s  area=%(area).4f m^2  MAC=%(chord).4f m  x_qc=%(x).4f  bins wing/fuse/tail=%(wing)d/%(fuse)d/%(tail)d" % ref, file=sys.stderr)
    return ref

def ray_inside(pt, tris):
    """Odd crossings of a +x ray. Triangles that miss the (y,z) are skipped."""
    x, y, z = pt
    hits = 0
    for a, b, c in tris:
        y0, y1, y2 = a[1], b[1], c[1]
        z0, z1, z2 = a[2], b[2], c[2]
        if y < min(y0, y1, y2) or y > max(y0, y1, y2): continue
        if z < min(z0, z1, z2) or z > max(z0, z1, z2): continue
        e1 = sub(b, a); e2 = sub(c, a)
        pvec = (0.0, -e2[2], e2[1])          # dir x e2, dir = (1,0,0)
        det = e1[0]*pvec[0] + e1[1]*pvec[1] + e1[2]*pvec[2]
        if abs(det) < 1e-14: continue
        inv = 1.0/det
        tvec = sub(pt, a)
        u = (tvec[0]*pvec[0] + tvec[1]*pvec[1] + tvec[2]*pvec[2]) * inv
        if u < 0.0 or u > 1.0: continue
        qvec = cross(tvec, e1)
        v = qvec[0] * inv                      # dir · qvec
        if v < 0.0 or u+v > 1.0: continue
        t = (e2[0]*qvec[0] + e2[1]*qvec[1] + e2[2]*qvec[2]) * inv
        if t > 1e-8: hits += 1
    return (hits % 2) == 1

def locate(tris, lo, hi):
    xmin, ymin, zmin = lo; xmax, ymax, zmax = hi
    D = max(xmax-xmin, ymax-ymin, zmax-zmin, 1e-6)
    ymid, zmid = 0.5*(ymin+ymax), 0.5*(zmin+zmax)
    # Upstream of the bounding box is outside the solid. The ray test confirms
    # a watertight body; a dirty STL can disagree, and the box still wins.
    cands = [
        (xmin - 1.5*D, ymid, zmid),
        (xmin - 1.5*D, ymid + 0.02*D, zmid + 0.02*D),
        (xmin - 2.0*D, ymid, zmid),
    ]
    outside_box = None
    for p in cands:
        if p[0] < xmin:
            outside_box = p
            if not ray_inside(p, tris):
                return p
    return outside_box or cands[0]

def estimate_cells(nx, ny, nz, level):
    n0 = nx * ny * nz
    extra = max(int(level) - 2, 0)
    return int(n0 * (1.0 + 0.15 * (4 ** extra)))

def prepare(src, dst, units, quality, speed, nu, layers, cellcap, chord_override):
    solids = read_solids(src)
    pts = all_pts(solids)
    ext = extent_of(pts)
    scale_name, factor = choose_scale(ext, units)
    eps = 1e-8 * max(ext, 1e-9)
    cleaned, dropped = {}, 0
    for name, tris in solids.items():
        keep = []
        for t in tris:
            if degenerate(t, eps):
                dropped += 1
                continue
            keep.append(scale_tri(t, factor))
        if keep:
            cleaned[name] = keep
    if not cleaned:
        sys.exit("every triangle in the STL was degenerate")
    write_stl(dst, cleaned)
    ref = reference(cleaned)
    pts = all_pts(cleaned)
    lo, hi = bounds(pts)
    xmin, ymin, zmin = lo; xmax, ymax, zmax = hi
    D = max(xmax-xmin, ymax-ymin, zmax-zmin)
    chord = float(chord_override) if chord_override else ref["chord"]
    speed, nu = float(speed), float(nu)
    layers, cellcap = int(float(layers)), float(cellcap)
    Re = speed * chord / nu
    Cf = 0.026 / (Re ** (1.0/7.0))
    utau = speed * math.sqrt(Cf/2.0)
    dy80 = TARGET_YP * nu / utau
    surf_target = 2.0 * dy80
    dx = D / 8.0
    x0, x1 = xmin - 3*D, xmax + 6*D
    y0, y1 = ymin - 3*D, ymax + 3*D
    z0, z1 = zmin - 3*D, zmax + 3*D
    nx, ny, nz = [int(math.ceil((b-a)/dx)) for a, b in ((x0, x1), (y0, y1), (z0, z1))]
    x1, y1, z1 = x0 + nx*dx, y0 + ny*dx, z0 + nz*dx
    levels = {"coarse": 3, "medium": 4, "fine": 5, "vfine": 6}
    cap_hit = 0
    if quality in levels:
        lvl = levels[quality]
        max_lvl = lvl
        quality_used = quality
    elif quality in ("", "auto"):
        ratio = dx / surf_target if surf_target > 0 else 1.0
        lvl = max(3, int(math.ceil(math.log(max(ratio, 1.0)) / math.log(2.0) - 1e-12)))
        max_lvl = 3
        for m in range(3, 9):
            if estimate_cells(nx, ny, nz, m) <= cellcap:
                max_lvl = m
            else:
                break
        if lvl > max_lvl:
            lvl = max_lvl
            cap_hit = 1
        quality_used = "auto"
    else:
        sys.exit("unknown quality '%s' (coarse|medium|fine|vfine)" % quality)
    lvl = max(1, min(8, int(lvl)))
    surf = dx / (2 ** lvl)
    pred = 80.0 if layers > 0 else (surf/2.0) * utau / nu
    loc = locate([t for tris in cleaned.values() for t in tris], lo, hi)
    print("cleaned STL: dropped %d degenerate triangles, wrote %s" % (dropped, dst), file=sys.stderr)
    emit("SCALE_NAME", scale_name); emit("SCALE_FACTOR", factor); emit("DROPPED", dropped)
    emit("REF_AREA", ref["area"]); emit("REF_CHORD", chord)
    emit("REF_XCG", ref["x"]); emit("REF_YCG", ref["y"]); emit("REF_ZCG", ref["z"])
    emit("COMPUTED_AREA", ref["area"]); emit("COMPUTED_CHORD", ref["chord"])
    emit("COMPUTED_XCG", ref["x"]); emit("COMPUTED_YCG", ref["y"]); emit("COMPUTED_ZCG", ref["z"])
    emit("REF_SOURCE", ref["source"])
    emit("WING_BINS", ref["wing"]); emit("FUSE_BINS", ref["fuse"]); emit("TAIL_BINS", ref["tail"])
    emit("XMIN", xmin); emit("XMAX", xmax); emit("YMIN", ymin); emit("YMAX", ymax)
    emit("ZMIN", zmin); emit("ZMAX", zmax)
    emit("X0", x0); emit("X1", x1); emit("Y0", y0); emit("Y1", y1); emit("Z0", z0); emit("Z1", z1)
    emit("DX", dx); emit("NX", nx); emit("NY", ny); emit("NZ", nz)
    emit("LVL", lvl); emit("L1", max(lvl-1, 1)); emit("L2", max(lvl-2, 1)); emit("MAX_LVL", max_lvl)
    emit("SURF_DX", surf); emit("DY1", dy80); emit("UTAU", utau); emit("CF_EST", Cf); emit("RE_C", Re)
    emit("TARGET_YPLUS", TARGET_YP); emit("PRED_YPLUS", pred)
    emit("CELL_EST", estimate_cells(nx, ny, nz, lvl)); emit("CAP_HIT", cap_hit); emit("CELLCAP", cellcap)
    emit("QUALITY_USED", quality_used)
    print("NEAR_MIN=" + vec((xmin-0.1*D, ymin-0.1*D, zmin-0.23*D)))
    print("NEAR_MAX=" + vec((xmax+0.3*D, ymax+0.1*D, zmax+0.23*D)))
    print("WAKE_MIN=" + vec((xmin-0.3*D, ymin-0.25*D, zmin-0.4*D)))
    print("WAKE_MAX=" + vec((xmax+1.5*D, ymax+0.25*D, zmax+0.4*D)))
    print("LOC=" + vec(loc))

# ------------------------------------------------------------------- patches ---
def patches(path):
    for line in open(path, errors="replace"):
        s = line.strip()
        if re.match(r"plane[A-Za-z0-9_]*$", s):
            print(s)

# ----------------------------------------------------------------------- y+ ---
def read_yplus(case):
    rows = []
    root = os.path.join(case, "postProcessing")
    if not os.path.isdir(root):
        return rows
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
    emit_yp = lambda **kw: [print("%s=%s" % (k, v)) for k, v in kw.items()]
    if not rows or not hdr:
        print("YP_PASS=0"); print("YP_AVG=nan"); print("YP_MIN=nan"); print("YP_MAX=nan")
        print("NEW_LVL=%d" % lvl); print("YP_REASON=no-data")
        return
    col = {n: i for i, n in enumerate(hdr)}
    # header is Time patch min max average, but patch is a word so rows were split
    # re-read raw so the patch name stays one token
    mins, maxs, avgs = [], [], []
    for r in rows:
        # r may be [time, patch, min, max, avg] if patch has no space
        nums = []
        for tok in r[1:]:
            try: nums.append(float(tok))
            except ValueError: pass
        if len(nums) >= 3:
            mins.append(nums[-3]); maxs.append(nums[-2]); avgs.append(nums[-1])
    if not avgs:
        print("YP_PASS=0"); print("YP_AVG=nan"); print("YP_MIN=nan"); print("YP_MAX=nan")
        print("NEW_LVL=%d" % lvl); print("YP_REASON=no-data")
        return
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
    print("YP_PASS=%d" % (1 if passed else 0))
    print("YP_AVG=%.8g" % avg); print("YP_MIN=%.8g" % ymin); print("YP_MAX=%.8g" % ymax)
    print("NEW_LVL=%d" % new); print("YP_REASON=%s" % reason)

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

def parse_residuals(path, p_tol, u_tol, k_tol):
    blocks = {}
    cur = None
    if not os.path.isfile(path):
        return {}, None
    rx = re.compile(r"Solving for (\w+), Initial residual = ([+\-0-9.eE]+)")
    tm = re.compile(r"^Time = (\d+)")
    for line in open(path, errors="replace"):
        m = tm.match(line)
        if m:
            cur = int(m.group(1))
            blocks[cur] = {}
            continue
        m = rx.search(line)
        if m and cur is not None and m.group(1) not in blocks[cur]:
            blocks[cur][m.group(1)] = float(m.group(2))
    def ok(vals):
        need = ("Ux", "Uy", "Uz", "p", "k", "omega")
        if any(n not in vals for n in need):
            return False
        if vals["p"] >= p_tol: return False
        if any(vals[n] >= u_tol for n in ("Ux", "Uy", "Uz")): return False
        if any(vals[n] >= k_tol for n in ("k", "omega")): return False
        return True
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

def spanwise(case, lift, drag, q, area):
    path = None
    root = os.path.join(case, "postProcessing")
    if os.path.isdir(root):
        cands = []
        for dirpath, _, files in os.walk(root):
            if "spanLoad" not in dirpath:
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
    # bin end coordinates along y, from the header comment
    ends = []
    for c in comments:
        if "y co-ords" in c:
            for tok in c.split():
                try: ends.append(float(tok))
                except ValueError: pass
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
        y = centers[i] if i < len(centers) else float("nan")
        cl = dot(F, lift)/(q*area) if area else float("nan")
        cd = dot(F, drag)/(q*area) if area else float("nan")
        out.append((y, cl, cd))
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
    "geometry","AoA_deg","speed_ms","Re","Mach","area_m2","MAC_m",
    "CofR_x_m","CofR_y_m","CofR_z_m","iterations",
    "Cl","sigma_Cl","Cd","sigma_Cd","Cs","sigma_Cs",
    "CmPitch","sigma_Cm","CmRoll","sigma_CmRoll","CmYaw","sigma_CmYaw",
    "Cl_p","Cl_v","Cd_p","Cd_v","L_over_D","lift_N","drag_N","moment_pitch_Nm",
    "yplus_min","yplus_max","yplus_avg","yplus_pass",
    "cells","nonortho_max","skew_max","converged","scheme","refs",
])

def append_csv(path, values):
    """Append one row. Rotate the file when an older header is in the way."""
    line = ",".join(csv_escape(v) for v in values)
    if os.path.exists(path):
        with open(path) as f:
            first = f.readline().strip()
        if first and first != CSV_HEADER:
            bak = path + ".bak"
            if os.path.exists(bak):
                bak = path + ".bak." + str(int(os.path.getmtime(path)))
            os.rename(path, bak)
            print("rotated %s -> %s (header changed)" % (path, bak), file=sys.stderr)
    new = not os.path.exists(path)
    with open(path, "a") as f:
        if new:
            f.write(CSV_HEADER + "\n")
        f.write(line + "\n")

def g(meta, key, default="nan"):
    return meta.get(key, default)

def report(case, meta_path, master_csv):
    meta = load_meta(meta_path)
    p_tol = fnum(g(meta, "P_TOL", "1e-5"))
    u_tol = fnum(g(meta, "U_TOL", "1e-6"))
    k_tol = fnum(g(meta, "K_TOL", "1e-6"))
    last_res, t_from = parse_residuals(g(meta, "LOG", ""), p_tol, u_tol, k_tol)
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
    lift = (fnum(g(meta, "LIFT_X")), 0.0, fnum(g(meta, "LIFT_Z")))
    drag = (fnum(g(meta, "DRAG_X")), 0.0, fnum(g(meta, "DRAG_Z")))
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
    span = spanwise(case, lift, drag, q, area)
    span_path = os.path.join(case, "spanwise_cl.csv")
    with open(span_path, "w") as f:
        f.write("y_m,Cl,Cd\n")
        for y, cl, cd in span:
            f.write("%.6f,%.6e,%.6e\n" % (y, cl, cd))

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

    lines = []
    A = lines.append
    A("================================ RESULTS ================================")
    if partial:
        A("  *** PARTIAL RESULTS - run was stopped early, not converged ***")
    A("  geometry     : %s" % g(meta, "GEOMETRY"))
    A("  AoA          : %s deg" % g(meta, "AOA"))
    A("  speed        : %s m/s" % g(meta, "SPEED"))
    A("  Mach         : %s" % g(meta, "MACH"))
    A("  Re_MAC       : %s" % g(meta, "RE"))
    A("  density      : %s kg/m^3     nu = %s m^2/s" % (g(meta, "RHO"), g(meta, "NU")))
    A("  wing area    : %s m^2        MAC = %s m" % (g(meta, "REF_AREA"), g(meta, "REF_CHORD")))
    A("  moment center: (%s, %s, %s) m" % (g(meta, "REF_XCG"), g(meta, "REF_YCG"), g(meta, "REF_ZCG")))
    src = g(meta, "REF_SOURCE", "")
    if g(meta, "REF_OVERRIDE", "0") == "1":
        src += "  (command-line override on top of %s)" % g(meta, "REF_SOURCE", "computed")
    A("  reference    : %s" % src)
    if g(meta, "REF_OVERRIDE", "0") == "1":
        A("  STL estimate : area %s m^2, MAC %s m, x %s m" % (
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
    A("------------------------------------------------------------------------")
    A("  sigma is the sample standard deviation on the converged window.")
    A("  It is iteration scatter, not the error from the mesh.")
    if total:
        A("  window       : iterations %.0f to %.0f  (%d samples)" % (total["t0"], total["t1"], total["n"]))
        A("  iterations   : %.0f" % total["iters"])
        A("  Cl           : %s" % fmt_pm(*Cl[:2]))
        A("  Cd           : %s" % fmt_pm(*Cd[:2]))
        A("  Cs           : %s" % fmt_pm(*S(total, "Cs")[:2]))
        A("  CmPitch      : %s" % fmt_pm(*Cm[:2]))
        A("  CmRoll       : %s" % fmt_pm(*CmR[:2]))
        A("  CmYaw        : %s" % fmt_pm(*CmY[:2]))
        A("  Cl pressure  : %s     Cl viscous : %s" % (fmt_pm(*Clp[:2]), fmt_pm(*Clv[:2])))
        A("  Cd pressure  : %s     Cd viscous : %s" % (fmt_pm(*Cdp[:2]), fmt_pm(*Cdv[:2])))
        A("  L/D          : %s" % ("%.2f" % ld if math.isfinite(ld) else "n/a"))
        A("  lift         : %.4f N     drag : %.4f N" % (lift_N, drag_N) if math.isfinite(lift_N) else "  lift         : n/a")
        A("  pitch moment : %s N·m" % ("%.5f" % mom_N if math.isfinite(mom_N) else "n/a"))
        if patches:
            A("  per patch    : (same area and moment center, so the parts add to the total)")
            sum_cl = 0.0
            for name, blk in patches:
                A("    %-16s Cl %s    Cd %s" % (name, fmt_pm(*blk["Cl"][:2]), fmt_pm(*blk["Cd"][:2])))
                sum_cl += blk["Cl"][0]
            A("    sum of patch Cl = %.5f" % sum_cl)
        if span:
            A("  spanwise Cl  : %d bins -> spanwise_cl.csv (contributions to the aircraft Cl, Cd)" % len(span))
        else:
            A("  spanwise Cl  : no bin file (see postProcessing/spanLoad)")
    else:
        A("  (no force coefficients found)")
    A("------------------------------------------------------------------------")
    if ytab:
        A("  y+           : %s   (wall functions want averages 30-300 and minima >= 11)" % ypass.upper())
        for name, a, b, c in ytab:
            A("    %-16s min %7.2f   max %7.2f   avg %7.2f" % (name, a, b, c))
    else:
        A("  y+           : not written")
    if last_res:
        bits = "  ".join("%s %.2e" % (k, last_res[k]) for k in ("p", "Ux", "Uy", "Uz", "k", "omega") if k in last_res)
        A("  last initial residual : %s" % bits)
    A("------------------------------------------------------------------------")
    A("  ParaView     : %s" % os.path.join(case, "case.foam"))
    A("                 Colour the plane patches by Cp. Cut the volume on U.")
    A("                 yPlus and wallShearStress are on the patches.")
    A("                 p is kinematic, and Cp = p / (0.5 U^2) is already a field.")
    A("  VTK          : %s" % os.path.join(case, "VTK"))
    A("  this run     : %s" % os.path.join(case, "report.txt"))
    A("                 %s" % os.path.join(case, "results.csv"))
    A("                 %s" % span_path)
    A("  all runs     : %s" % master_csv)
    A("=========================================================================")
    text = "\n".join(lines)
    print(text)
    with open(os.path.join(case, "report.txt"), "w") as f:
        f.write(text + "\n")

    iters = total["iters"] if total else 0
    row_ok = total and math.isfinite(Cl[0]) and math.isfinite(Cd[0]) and iters >= 1
    values = [
        g(meta, "GEOMETRY"), g(meta, "AOA"), g(meta, "SPEED"), g(meta, "RE"), g(meta, "MACH"),
        g(meta, "REF_AREA"), g(meta, "REF_CHORD"),
        g(meta, "REF_XCG"), g(meta, "REF_YCG"), g(meta, "REF_ZCG"),
        "%.0f" % iters if total else "0",
        "%.6f" % Cl[0], "%.6e" % Cl[1], "%.6f" % Cd[0], "%.6e" % Cd[1],
        "%.6f" % S(total, "Cs")[0], "%.6e" % S(total, "Cs")[1],
        "%.6f" % Cm[0], "%.6e" % Cm[1],
        "%.6f" % CmR[0], "%.6e" % CmR[1],
        "%.6f" % CmY[0], "%.6e" % CmY[1],
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
    ]
    if row_ok:
        run_csv = os.path.join(case, "results.csv")
        append_csv(run_csv, values)
        append_csv(master_csv, values)
    else:
        print("  (results.csv not updated: Cl/Cd were not finite)", file=sys.stderr)

if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "make":      make(sys.argv[2], sys.argv[3])
    elif cmd == "prepare": prepare(*sys.argv[2:11])
    elif cmd == "patches": patches(sys.argv[2])
    elif cmd == "yplus":   yplus_cmd(*sys.argv[2:6])
    elif cmd == "report":  report(*sys.argv[2:5])
    else: sys.exit("unknown helper command %s" % cmd)
PYEOF

