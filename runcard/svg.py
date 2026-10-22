"""Pure-Python inline SVG line chart (metric vs varied input).

No external assets, no fonts beyond the system stack, dark ink on white.
Y switches to a log10 scale when positive values span more than two decades.
"""

from __future__ import annotations

import math
from typing import Sequence
from xml.sax.saxutils import escape

W, H = 640, 400
ML, MR, MT, MB = 80, 24, 24, 64  # margins


def _nice_step(span: float, target: int = 6) -> float:
    if span <= 0:
        return 1.0
    raw = span / target
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def linear_ticks(lo: float, hi: float, target: int = 6) -> list[float]:
    if hi == lo:
        pad = abs(lo) * 0.1 or 1.0
        lo, hi = lo - pad, hi + pad
    step = _nice_step(hi - lo, target)
    start = math.floor(lo / step) * step
    ticks = []
    t = start
    while t <= hi + step * 1e-9:
        if t >= lo - step * 1e-9:
            ticks.append(round(t, 12))
        t += step
    return ticks


def log_ticks(lo: float, hi: float) -> list[float]:
    a, b = math.floor(math.log10(lo)), math.ceil(math.log10(hi))
    return [10.0 ** e for e in range(a, b + 1)]


def fmt_tick(v: float, log: bool = False) -> str:
    if log:
        e = round(math.log10(v))
        return f"1e{e}"
    if v == 0:
        return "0"
    if abs(v) >= 1e5 or abs(v) < 1e-3:
        return f"{v:.1e}"
    if float(v).is_integer():
        return str(int(v))
    return f"{v:.4g}"


def should_log(values: Sequence[float]) -> bool:
    pos = [v for v in values if v is not None and v > 0]
    if len(pos) < 2 or len(pos) != len([v for v in values if v is not None]):
        return False
    return max(pos) / min(pos) > 100.0


def line_chart(xs: Sequence[float], ys: Sequence[float], *, x_label: str, y_label: str,
               title: str = "", filled: Sequence[bool] | None = None,
               legend: bool = True) -> str:
    """Return an SVG string. ``filled[i]`` draws point i as a filled circle
    (served from cache) versus hollow (computed in this session)."""
    pts = [(float(x), float(y)) for x, y in zip(xs, ys) if x is not None and y is not None]
    if filled is None:
        filled = [True] * len(xs)
    order = sorted(range(len(pts)), key=lambda i: pts[i][0])
    pts = [pts[i] for i in order]
    filled = [filled[i] for i in order]
    log_y = should_log([p[1] for p in pts]) if pts else False

    pw, ph = W - ML - MR, H - MT - MB
    if pts:
        xlo, xhi = min(p[0] for p in pts), max(p[0] for p in pts)
        yv = [math.log10(p[1]) if log_y else p[1] for p in pts]
        ylo, yhi = min(yv), max(yv)
    else:
        xlo, xhi, ylo, yhi = 0.0, 1.0, 0.0, 1.0
    xt = linear_ticks(xlo, xhi)
    if xt:
        xlo, xhi = min(xlo, xt[0]), max(xhi, xt[-1])
    if xhi == xlo:
        xhi = xlo + 1
    if log_y:
        yt = log_ticks(10 ** ylo, 10 ** yhi)
        ylo, yhi = math.log10(yt[0]), math.log10(yt[-1])
    else:
        yt = linear_ticks(ylo, yhi)
        if yt:
            ylo, yhi = min(ylo, yt[0]), max(yhi, yt[-1])
    if yhi == ylo:
        yhi = ylo + 1

    def sx(x: float) -> float:
        return ML + (x - xlo) / (xhi - xlo) * pw

    def sy(y: float) -> float:
        yy = math.log10(y) if log_y else y
        return MT + ph - (yy - ylo) / (yhi - ylo) * ph

    o: list[str] = []
    o.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
             f'role="img" aria-label="{escape(title or y_label)}" '
             'font-family="-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif" font-size="12">')
    o.append(f'<rect x="0" y="0" width="{W}" height="{H}" fill="#ffffff"/>')
    if title:
        o.append(f'<text x="{ML + pw / 2:.1f}" y="{MT - 8}" text-anchor="middle" font-size="13" fill="#111">{escape(title)}</text>')
    # grid + ticks
    for t in xt:
        if t < xlo - 1e-9 or t > xhi + 1e-9:
            continue
        X = sx(t)
        o.append(f'<line x1="{X:.1f}" y1="{MT}" x2="{X:.1f}" y2="{MT + ph}" stroke="#e6e6e6" stroke-width="1"/>')
        o.append(f'<line x1="{X:.1f}" y1="{MT + ph}" x2="{X:.1f}" y2="{MT + ph + 5}" stroke="#111"/>')
        o.append(f'<text x="{X:.1f}" y="{MT + ph + 18}" text-anchor="middle" fill="#111">{escape(fmt_tick(t))}</text>')
    for t in yt:
        Y = sy(t)
        if Y < MT - 1 or Y > MT + ph + 1:
            continue
        o.append(f'<line x1="{ML}" y1="{Y:.1f}" x2="{ML + pw}" y2="{Y:.1f}" stroke="#e6e6e6" stroke-width="1"/>')
        o.append(f'<line x1="{ML - 5}" y1="{Y:.1f}" x2="{ML}" y2="{Y:.1f}" stroke="#111"/>')
        o.append(f'<text x="{ML - 8}" y="{Y + 4:.1f}" text-anchor="end" fill="#111">{escape(fmt_tick(t, log_y))}</text>')
    # axes
    o.append(f'<line x1="{ML}" y1="{MT}" x2="{ML}" y2="{MT + ph}" stroke="#111" stroke-width="1.2"/>')
    o.append(f'<line x1="{ML}" y1="{MT + ph}" x2="{ML + pw}" y2="{MT + ph}" stroke="#111" stroke-width="1.2"/>')
    # axis labels
    o.append(f'<text class="axis-label" x="{ML + pw / 2:.1f}" y="{H - 24}" text-anchor="middle" fill="#111">{escape(x_label)}</text>')
    yl = y_label + (" (log scale)" if log_y else "")
    o.append(f'<text class="axis-label" x="16" y="{MT + ph / 2:.1f}" text-anchor="middle" fill="#111" '
             f'transform="rotate(-90 16 {MT + ph / 2:.1f})">{escape(yl)}</text>')
    # series
    if pts:
        coords = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in pts)
        o.append(f'<polyline points="{coords}" fill="none" stroke="#1a1a1a" stroke-width="1.6"/>')
        for (x, y), f in zip(pts, filled):
            fill = "#1a1a1a" if f else "#ffffff"
            o.append(f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="4" fill="{fill}" stroke="#1a1a1a" stroke-width="1.4">'
                     f'<title>{escape(x_label)} = {fmt_tick(x)}; {escape(y_label)} = {y:.4g}</title></circle>')
    if legend and pts:
        lx, ly = ML + pw - 230, MT + ph - 12  # bottom right: curves usually rise to the right
        o.append(f'<circle cx="{lx}" cy="{ly}" r="4" fill="#1a1a1a" stroke="#1a1a1a"/>')
        o.append(f'<text x="{lx + 10}" y="{ly + 4}" fill="#111">served from cache</text>')
        o.append(f'<circle cx="{lx + 125}" cy="{ly}" r="4" fill="#fff" stroke="#1a1a1a" stroke-width="1.4"/>')
        o.append(f'<text x="{lx + 135}" y="{ly + 4}" fill="#111">computed now</text>')
    o.append("</svg>")
    return "\n".join(o)
