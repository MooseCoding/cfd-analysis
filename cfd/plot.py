"""Small SVG line charts. No third-party library."""
import math


_COLORS = (
    "#1d4e89", "#b45309", "#0f766e", "#9f1239",
    "#6d28d9", "#4d7c0f", "#be185d", "#0369a1",
)

def _esc(text):
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _finite(pairs):
    out = []
    for x, y in pairs:
        try:
            xf, yf = float(x), float(y)
        except (TypeError, ValueError):
            continue
        if math.isfinite(xf) and math.isfinite(yf):
            out.append((xf, yf))
    return out


def _bounds(values, log):
    lo, hi = min(values), max(values)
    if lo == hi:
        if log:
            lo = lo / 10.0 if lo > 0 else 1e-6
            hi = hi * 10.0 if hi > 0 else 1.0
        else:
            pad = 1.0 if lo == 0 else abs(lo) * 0.15
            lo -= pad
            hi += pad
        return lo, hi
    if log:
        return lo, hi
    pad = (hi - lo) * 0.08
    return lo - pad, hi + pad


def _map(value, lo, hi, start, length, log=False):
    if log:
        value = math.log10(value)
        lo = math.log10(lo)
        hi = math.log10(hi)
    span = hi - lo
    if span == 0:
        t = 0.5
    else:
        t = (value - lo) / span
    return start + t * length


def write_panels(path, panels, note=""):
    """Write one SVG. Each panel has title, xlabel, ylabel, series, and optional log_y.

    ``series`` is a list of ``(name, [(x, y), ...])``. ``note`` is stored in
    ``<desc>`` so the source numbers remain readable in the file.
    """
    width = 720
    left, right, title_h, axis_h = 68, 18, 26, 36
    plot_h = 150
    gap = 28
    panel_h = title_h + plot_h + axis_h
    height = 16 + len(panels) * panel_h + max(0, len(panels) - 1) * gap
    plot_w = width - left - right
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">' % (
            width, height, width, height,
        ),
        "<desc>%s</desc>" % _esc(note),
        '<rect width="100%" height="100%" fill="#ffffff"/>',
    ]
    for index, panel in enumerate(panels):
        top = 16 + index * (panel_h + gap)
        log_y = bool(panel.get("log_y"))
        series = []
        for name, pairs in panel.get("series") or []:
            pts = _finite(pairs)
            if log_y:
                pts = [(x, y) for x, y in pts if y > 0]
            series.append((name, pts))
        parts.append(
            '<text x="%d" y="%d" font-family="sans-serif" font-size="14" fill="#1a1a1a">%s</text>' % (
                left, top + 14, _esc(panel.get("title") or ""),
            )
        )
        plot_top = top + title_h
        xs, ys = [], []
        for _name, pts in series:
            for x, y in pts:
                xs.append(x)
                ys.append(y)
        parts.append(
            '<rect x="%d" y="%d" width="%d" height="%d" fill="#f6f5f2" stroke="#e3e0d8"/>' % (
                left, plot_top, plot_w, plot_h,
            )
        )
        if not xs:
            parts.append(
                '<text x="%d" y="%d" font-family="sans-serif" font-size="13" fill="#5e5a54">no samples</text>' % (
                    left + 12, plot_top + 28,
                )
            )
        else:
            x0, x1 = _bounds(xs, False)
            y0, y1 = _bounds(ys, log_y)
            for tick in range(5):
                ty = plot_top + plot_h - (tick / 4.0) * plot_h
                parts.append(
                    '<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#e3e0d8"/>' % (
                        left, ty, left + plot_w, ty,
                    )
                )
        for sindex, (name, pts) in enumerate(series):
                if not pts:
                    continue
                color = _COLORS[sindex % len(_COLORS)]
                coords = []
                for x, y in pts:
                    px = _map(x, x0, x1, left, plot_w, False)
                    py = plot_top + plot_h - _map(y, y0, y1, 0, plot_h, log_y)
                    coords.append((px, py))
                if len(coords) == 1:
                    px, py = coords[0]
                    parts.append('<circle cx="%.2f" cy="%.2f" r="3.5" fill="%s"/>' % (px, py, color))
                else:
                    points = " ".join("%.2f,%.2f" % (px, py) for px, py in coords)
                    parts.append(
                        '<polyline fill="none" stroke="%s" stroke-width="2" points="%s"/>' % (
                            color, points,
                        )
                    )
                parts.append(
                    '<text x="%d" y="%d" font-family="sans-serif" font-size="12" fill="%s">%s</text>' % (
                        left + 8 + (sindex % 3) * 170,
                        plot_top + 16 + (sindex // 3) * 14,
                        color, _esc(name),
                    )
                )
        parts.append(
            '<text x="%d" y="%d" font-family="sans-serif" font-size="12" fill="#5e5a54">%s</text>' % (
                left, top + panel_h - 8, _esc(panel.get("xlabel") or ""),
            )
        )
        ylabel = panel.get("ylabel") or ""
        y_anchor = int(plot_top + plot_h / 2)
        parts.append(
            '<text x="14" y="%d" font-family="sans-serif" font-size="12" fill="#5e5a54" transform="rotate(-90 14 %d)">%s</text>' % (
                y_anchor + 4, y_anchor, _esc(ylabel),
            )
        )
    parts.append("</svg>")
    with open(path, "w") as handle:
        handle.write("\n".join(parts) + "\n")
