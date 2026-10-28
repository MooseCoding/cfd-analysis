"""STL cleanup, built-in shapes, reference quantities, and mesh sizing. Stdlib only."""
import math, struct, sys

def sub(a, b):   return (a[0]-b[0], a[1]-b[1], a[2]-b[2])
def cross(a, b): return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
def dot(a, b):   return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]
def mean(p):
    n = len(p)
    return tuple(sum(q[i] for q in p)/n for i in range(3))

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

def make_plane(path, span_ft):
    make(path, span_ft)

def _ring(x, radius, k=32):
    return [(x, radius*math.cos(2*math.pi*i/k), radius*math.sin(2*math.pi*i/k)) for i in range(k)]

def _nose_radius(kind, x, length, radius):
    if kind == "cone":
        r = radius * (x/length)
    elif kind == "elliptical":
        u = 1.0 - x/length
        r = radius * math.sqrt(max(0.0, 1.0 - u*u))
    elif kind == "ogive":
        rho = (radius*radius + length*length) / (2.0*radius)
        r = math.sqrt(max(0.0, rho*rho - (length - x)**2)) - (rho - radius)
    else:
        sys.exit("unknown nose '%s' (ogive|cone|elliptical)" % kind)
    # A small blunt tip keeps the nose cap from collapsing into zero-area triangles.
    return max(r, 0.02*radius)

def make_rocket(path, diameter, body_l, nose_l, nose="ogive", fin_count=4,
                fin_root=0.12, fin_tip=0.06, fin_span=0.10, fin_sweep=0.04, fin_x=None):
    """Closed nose, tube, and fins. x = 0 at the nose tip, +x toward the base."""
    radius = float(diameter)/2.0
    nose_l, body_l = float(nose_l), float(body_l)
    if radius <= 0 or nose_l <= 0 or body_l <= 0:
        sys.exit("rocket diameter, nose length, and body length must be positive")
    nfin = int(fin_count)
    if nfin < 2:
        sys.exit("fin count must be at least 2")
    total = nose_l + body_l
    nose_xs = [nose_l*(1 - math.cos(0.5*math.pi*i/16)) for i in range(17)]
    tube0 = nose_l - 0.02*diameter
    tube_xs = [tube0 + (total - tube0)*i/8.0 for i in range(9)]
    solids = {
        "nose": loft([_ring(x, _nose_radius(nose, x, nose_l, radius)) for x in nose_xs]),
        "tube": loft([_ring(x, radius) for x in tube_xs]),
    }
    root, tip = float(fin_root), float(fin_tip)
    span, sweep = float(fin_span), float(fin_sweep)
    xle0 = total - root if fin_x is None or fin_x == "" else float(fin_x)
    af = naca4("0006")
    fins = []
    for i in range(nfin):
        theta = 2*math.pi*i/nfin
        radial = (0.0, math.sin(theta), math.cos(theta))
        lateral = (0.0, math.cos(theta), -math.sin(theta))
        sections = []
        for j in range(9):
            u = j/8.0
            s = radius*0.98 + span*u
            chord = root + (tip - root)*u
            xle = xle0 + sweep*u
            sections.append([
                (xle + chord*px,
                 radial[1]*s + lateral[1]*chord*pz,
                 radial[2]*s + lateral[2]*chord*pz)
                for px, pz in af
            ])
        fins.extend(loft(sections))
    solids["fin"] = fins
    write_stl(path, solids)
    return {"diameter": diameter, "length": total, "fin_x": xle0, "nose": nose}

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
    with open(path, "rb") as handle:
        data = handle.read()
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

_UNITS = (("m", 1.0), ("mm", 0.001), ("cm", 0.01), ("in", 0.0254), ("ft", 0.3048))

def choose_scale(extent, units, target=None, mode="target"):
    """Return (unit name, metres per file unit).

    mode "target" picks the unit whose scaled size is closest to target
    inside 0.2-5 m. mode "body" accepts a unit only when exactly one of
    m/mm/cm/in/ft lands in 0.05-20 m.
    """
    if units and units != "auto":
        for name, f in _UNITS:
            if units == name:
                return name, f
        sys.exit("unknown unit '%s' (use m, mm, cm, in or ft)" % units)
    if mode == "body" and not target:
        plausible = []
        for name, f in _UNITS:
            length = extent * f
            if 0.05 <= length <= 20.0:
                plausible.append((name, f, length))
        if len(plausible) != 1:
            sys.exit(
                "could not detect STL units: largest side is %.4g. "
                "Pass -u m|mm|cm|in|ft" % extent
            )
        name, f, length = plausible[0]
        print("units: %s  (largest side %.4g -> %.4g m)" % (name, extent, length), file=sys.stderr)
        return name, f
    if not target:
        target = 3*0.3048
    cands = []
    for name, f in _UNITS:
        length = extent * f
        if 0.2 <= length <= 5.0:
            cands.append((abs(length - target), name, f, length))
    if not cands:
        sys.exit("could not detect STL units: largest side is %.4g. Pass -u m|mm|cm|in|ft" % extent)
    cands.sort()
    _, name, f, length = cands[0]
    print("units: %s  (largest side %.4g -> %.4g m)" % (name, extent, length), file=sys.stderr)
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

def frontal_area(tris):
    """Silhouette area looking along +x. Exact for a closed convex body."""
    projected = 0.0
    for a, b, c in tris:
        projected += abs(cross(sub(b, a), sub(c, a))[0])
    return 0.25 * projected

def _median(xs):
    ys = sorted(xs)
    return ys[len(ys)//2]

def rocket_body_points(solids):
    named, other = [], []
    for name, tris in solids.items():
        low = name.lower()
        pts = [p for t in tris for p in t]
        if any(k in low for k in ("fin", "wing", "tail")):
            continue
        if any(k in low for k in ("nose", "tube", "body", "fuselage")):
            named.extend(pts)
        else:
            other.extend(pts)
    if named:
        return named, "named-body"
    if other:
        return other, "radius-run"
    return [p for tris in solids.values() for t in tris for p in t], "radius-run"

def diameter_from_points(pts, nb=48):
    """Diameter of the longest nearly constant-radius stretch along x."""
    if len(pts) < 12:
        return None
    cy = _median([p[1] for p in pts])
    cz = _median([p[2] for p in pts])
    xs = [p[0] for p in pts]
    x0, x1 = min(xs), max(xs)
    span = x1 - x0
    if span <= 1e-9:
        return None
    width = span / float(nb)
    groups = [[] for _ in range(nb)]
    for p in pts:
        i = int((p[0] - x0) / width)
        if i >= nb:
            i = nb - 1
        if i < 0:
            i = 0
        groups[i].append(math.hypot(p[1] - cy, p[2] - cz))
    radii = [_median(g) if len(g) >= 3 else None for g in groups]
    occupied = [(i, radii[i]) for i in range(nb) if radii[i]]
    if not occupied:
        return None
    # Gaps are allowed: a cylinder often has vertices only on a few stations.
    best_len, best_r = -1.0, None
    for _, seed in occupied:
        group = [r for _, r in occupied if abs(r - seed) <= 0.05*max(seed, 1e-9)]
        idxs = [i for i, r in occupied if abs(r - seed) <= 0.05*max(seed, 1e-9)]
        length = (idxs[-1] - idxs[0] + 1) * width
        if length > best_len:
            best_len = length
            best_r = _median(group)
    if best_r is None or best_len < 0.15*span:
        best_r = max(r for _, r in occupied)
    def snap(value):
        return 0.0 if abs(value) < 1e-9 else value
    return {"diameter": 2.0*best_r, "y": snap(cy), "z": snap(cz), "length": span, "x0": x0, "x1": x1}

def rocket_reference(solids):
    pts, how = rocket_body_points(solids)
    info = diameter_from_points(pts)
    if info is None:
        sys.exit("could not find a body diameter in the STL. Set REF_AREA and REF_LENGTH")
    diameter = info["diameter"]
    ref = {
        "area": math.pi * (diameter/2.0)**2,
        "chord": diameter,
        "x": info["x0"] + 0.5*info["length"],
        "y": info["y"],
        "z": info["z"],
        "diameter": diameter,
        "length": info["length"],
        "cg_default": True,
        "wing": 0, "fuse": 0, "tail": 0,
        "source": "rocket-" + how,
    }
    print(
        "reference: %(source)s  Aref=%(area).6f m^2  D=%(diameter).4f m  L=%(length).4f m  x_mid=%(x).4f" % ref,
        file=sys.stderr,
    )
    return ref

def body_reference(solids):
    tris = [t for group in solids.values() for t in group]
    pts = [p for t in tris for p in t]
    if not pts:
        sys.exit("could not compute a body reference from the STL")
    lo, hi = bounds(pts)
    area = frontal_area(tris)
    length = hi[0] - lo[0]
    if area <= 1e-12:
        area = max((hi[1] - lo[1]) * (hi[2] - lo[2]), 1e-12)
        source = "bbox-frontal"
    else:
        source = "frontal-projection"
    ref = {
        "area": area,
        "chord": max(length, 1e-8),
        "x": 0.5*(lo[0] + hi[0]),
        "y": 0.5*(lo[1] + hi[1]),
        "z": 0.5*(lo[2] + hi[2]),
        "diameter": None,
        "length": length,
        "cg_default": True,
        "wing": 0, "fuse": 0, "tail": 0,
        "source": source,
    }
    print("reference: %(source)s  Aref=%(area).6f m^2  L=%(length).4f m" % ref, file=sys.stderr)
    return ref

def prepare(src, dst, units, quality, speed, nu, layers, cellcap, chord_override,
            profile="plane", target_size_m=None, target_yplus=80):
    solids = read_solids(src)
    pts = all_pts(solids)
    ext = extent_of(pts)
    if profile == "rocket":
        scale_name, factor = choose_scale(ext, units, target=target_size_m or 1.0, mode="target")
    elif profile == "body":
        if target_size_m:
            scale_name, factor = choose_scale(ext, units, target=float(target_size_m), mode="target")
        else:
            scale_name, factor = choose_scale(ext, units, mode="body")
    else:
        scale_name, factor = choose_scale(ext, units, target=3*0.3048, mode="target")
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
    if profile == "rocket":
        ref = rocket_reference(cleaned)
    elif profile == "body":
        ref = body_reference(cleaned)
    else:
        ref = reference(cleaned)
        ref.setdefault("diameter", None)
        ref.setdefault("length", ref["chord"])
        ref.setdefault("cg_default", False)
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
    yp_target = float(target_yplus)
    dy80 = yp_target * nu / utau
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
    return {
        "scale_name": scale_name, "scale_factor": factor, "dropped": dropped,
        "ref_area": ref["area"], "ref_chord": chord,
        "ref_x": ref["x"], "ref_y": ref["y"], "ref_z": ref["z"],
        "computed_area": ref["area"], "computed_chord": ref["chord"],
        "computed_x": ref["x"], "computed_y": ref["y"], "computed_z": ref["z"],
        "ref_source": ref["source"],
        "diameter": ref.get("diameter"), "body_length": ref.get("length"),
        "cg_default": bool(ref.get("cg_default")),
        "wing_bins": ref.get("wing", 0), "fuse_bins": ref.get("fuse", 0), "tail_bins": ref.get("tail", 0),
        "xmin": xmin, "xmax": xmax, "ymin": ymin, "ymax": ymax, "zmin": zmin, "zmax": zmax,
        "x0": x0, "x1": x1, "y0": y0, "y1": y1, "z0": z0, "z1": z1,
        "dx": dx, "nx": nx, "ny": ny, "nz": nz,
        "lvl": lvl, "l1": max(lvl-1, 1), "l2": max(lvl-2, 1), "max_lvl": max_lvl,
        "surf_dx": surf, "dy1": dy80, "utau": utau, "cf_est": Cf, "re_c": Re,
        "target_yplus": yp_target, "pred_yplus": pred,
        "cell_est": estimate_cells(nx, ny, nz, lvl), "cap_hit": cap_hit, "cellcap": cellcap,
        "quality_used": quality_used,
        "near_min": (xmin-0.1*D, ymin-0.1*D, zmin-0.23*D),
        "near_max": (xmax+0.3*D, ymax+0.1*D, zmax+0.23*D),
        "wake_min": (xmin-0.3*D, ymin-0.25*D, zmin-0.4*D),
        "wake_max": (xmax+1.5*D, ymax+0.25*D, zmax+0.4*D),
        "loc": loc,
    }
