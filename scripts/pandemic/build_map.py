"""Build src/pandemic/web/static/map-data.js: projected, magnified and simplified world map + city positions.

Source data: Natural Earth 1:50m via world-atlas (land, countries) and natural-earth-vector (lakes).
Run: uv run python scripts/build_map.py
"""

import itertools
import json
import math
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE / "mapsrc"

LON0, LON1 = -128.0, 162.0
LAT_TOP, LAT_BOT = 76.0, -47.0
W = 1400.0
S = W / (LON1 - LON0)


def miller(lat):
    return math.degrees(1.25 * math.log(math.tan(math.pi / 4 + 0.4 * math.radians(lat))))


Y_TOP, Y_BOT = miller(LAT_TOP), miller(LAT_BOT)
H = round((Y_TOP - Y_BOT) * S)


def base(lon, lat):
    return (lon - LON0) * S, (Y_TOP - miller(max(-80.0, min(80.0, lat)))) * S


# (lon, lat, strength, radius px). Smooth radial magnifiers; profile 1 + k / (1 + r²/σ²) is always monotonic.
LENSES = [
    (5.0, 49.0, 1.55, 58.0),  # western Europe
    (-75.5, 40.5, 1.8, 26.0),  # US east coast
    (130.0, 34.0, 1.1, 44.0),  # Korea / Japan / Shanghai
    (138.0, 35.5, 0.6, 16.0),  # Tokyo / Osaka
    (-120.0, 36.0, 0.5, 22.0),  # California
    (34.0, 37.0, 0.35, 40.0),  # eastern Mediterranean
]
LENS_PX = []


def warp(x, y):
    for cx, cy, k, s in LENS_PX:
        dx, dy = x - cx, y - cy
        f = 1 + k / (1 + (dx * dx + dy * dy) / (s * s))
        x, y = cx + dx * f, cy + dy * f
    return x, y


def proj(lon, lat):
    return warp(*base(lon, lat))


# lenses are applied in order, so each centre has to go through the lenses before it
for _lo, _la, _k, _s in LENSES:
    LENS_PX.append((*proj(_lo, _la), _k, _s))


# ------------------------------------------------------------------ topojson
def decode_arcs(topo):
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    out = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty))
        out.append(pts)
    return out


def arc_pts(arcs, i):
    return arcs[i] if i >= 0 else arcs[~i][::-1]


def ring_from(arcs, idxs):
    pts = []
    for i in idxs:
        a = arc_pts(arcs, i)
        pts.extend(a if not pts else a[1:])
    return pts


def geoms(topo, name):
    obj = topo["objects"][name]
    return obj["geometries"] if obj["type"] == "GeometryCollection" else [obj]


def polygons(g):
    if g["type"] == "Polygon":
        return [g["arcs"]]
    if g["type"] == "MultiPolygon":
        return g["arcs"]
    return []


# ------------------------------------------------------------------ geometry helpers
def densify(pts, max_deg=0.5):
    out = [pts[0]]
    for (x0, y0), (x1, y1) in itertools.pairwise(pts):
        n = int(max(abs(x1 - x0), abs(y1 - y0)) / max_deg)
        for j in range(1, n + 1):
            t = j / (n + 1)
            out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
        out.append((x1, y1))
    return out


def dp(pts, tol):
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = pts[a]
        bx, by = pts[b]
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy) or 1e-9
        best, bi = -1.0, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            d = abs(dy * (px - ax) - dx * (py - ay)) / L
            if d > best:
                best, bi = d, i
        if best > tol:
            keep[bi] = True
            stack += [(a, bi), (bi, b)]
    return [p for p, k in zip(pts, keep, strict=True) if k]


def area(pts):
    return 0.5 * sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1], strict=True))


def bbox_visible(pts, pad=40):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return max(xs) > -pad and min(xs) < W + pad and max(ys) > -pad and min(ys) < H + pad


def unwrap(lonlat):
    out = [lonlat[0]]
    for lo, la in lonlat[1:]:
        prev = out[-1][0]
        while lo - prev > 180:
            lo -= 360
        while lo - prev < -180:
            lo += 360
        out.append((lo, la))
    # a ring may start on the far side of the antimeridian (Chukotka): shift it so most of it is in range
    mid = sorted(lo for lo, _ in out)[len(out) // 2]
    shift = -360 * round(mid / 360)
    return [(lo + shift, la) for lo, la in out]


def project_line(lonlat, tol, closed):
    pts = [proj(lo, la) for lo, la in densify(unwrap(lonlat))]
    if not bbox_visible(pts):
        return None
    if not closed:
        return dp(pts, tol)
    if pts[0] == pts[-1]:
        pts = pts[:-1]
    x0, y0 = pts[0]
    m = max(range(len(pts)), key=lambda i: (pts[i][0] - x0) ** 2 + (pts[i][1] - y0) ** 2)
    return dp(pts[: m + 1], tol) + dp([*pts[m:], pts[0]], tol)[1:-1]


def to_d(rings, closed):
    parts = []
    for r in rings:
        s = "M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in r)
        parts.append(s + ("Z" if closed else ""))
    return "".join(parts)


def point_in(rings, x, y):
    inside = False
    for r in rings:
        for (x0, y0), (x1, y1) in zip(r, r[1:] + r[:1], strict=True):
            if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
                inside = not inside
    return inside


# ------------------------------------------------------------------ build
land_topo = json.loads((SRC / "land-50m.json").read_text())
land_arcs = decode_arcs(land_topo)
land_rings = []
for g in geoms(land_topo, "land"):
    for poly in polygons(g):
        for ring in poly:
            r = project_line(ring_from(land_arcs, ring), 0.3, True)
            if r and len(r) > 3 and abs(area(r)) > 2.0:
                land_rings.append(r)

ctry = json.loads((SRC / "countries-50m.json").read_text())
c_arcs = decode_arcs(ctry)
use = {}
for g in geoms(ctry, "countries"):
    for poly in polygons(g):
        for ring in poly:
            for i in ring:
                j = i if i >= 0 else ~i
                use[j] = use.get(j, 0) + 1
borders = []
for j, n in use.items():
    if n >= 2:
        r = project_line(c_arcs[j], 0.35, False)
        if r and len(r) >= 2:
            borders.append(r)

lakes_src = json.loads((SRC / "lakes-50m.geojson").read_text())
lakes = []
for f in lakes_src["features"]:
    gm = f["geometry"]
    polys = gm["coordinates"] if gm["type"] == "MultiPolygon" else [gm["coordinates"]]
    for poly in polys:
        r = project_line([tuple(p) for p in poly[0]], 0.3, True)
        if r and len(r) > 3 and abs(area(r)) > 6.0:
            lakes.append(r)


CITY_LL = {
    "sf": (-122.42, 37.77),
    "chi": (-87.63, 41.88),
    "mon": (-73.57, 45.50),
    "ny": (-74.00, 40.71),
    "was": (-77.04, 38.91),
    "atl": (-84.39, 33.75),
    "lon": (-0.13, 51.51),
    "mad": (-3.70, 40.42),
    "par": (2.35, 48.86),
    "ess": (7.01, 51.46),
    "mil": (9.19, 45.46),
    "stp": (30.31, 59.94),
    "la": (-118.24, 34.05),
    "mex": (-99.13, 19.43),
    "mia": (-80.19, 25.76),
    "bog": (-74.07, 4.71),
    "lim": (-77.04, -12.05),
    "san": (-70.67, -33.45),
    "bue": (-58.38, -34.60),
    "sao": (-46.63, -23.55),
    "lag": (3.38, 6.52),
    "kin": (15.27, -4.44),
    "joh": (28.05, -26.20),
    "kha": (32.56, 15.50),
    "alg": (3.06, 36.75),
    "cai": (31.24, 30.04),
    "ist": (28.98, 41.01),
    "mos": (37.62, 55.76),
    "bag": (44.37, 33.31),
    "riy": (46.68, 24.71),
    "teh": (51.39, 35.69),
    "kar": (67.01, 24.86),
    "del": (77.21, 28.61),
    "mum": (72.88, 19.08),
    "che": (80.27, 13.08),
    "kol": (88.36, 22.57),
    "bei": (116.41, 39.90),
    "seo": (126.98, 37.57),
    "tok": (139.69, 35.69),
    "sha": (121.47, 31.23),
    "osa": (135.50, 34.69),
    "tai": (121.57, 25.03),
    "hk": (114.17, 22.32),
    "bkk": (100.50, 13.76),
    "man": (120.98, 14.60),
    "hcm": (106.63, 10.82),
    "jak": (106.85, -6.21),
    "syd": (151.21, -33.87),
}
# a few coastal cities sit a hair offshore at this resolution; nudge them inland (lon, lat)
NUDGE = {
    "ist": (28.85, 41.06),
    "ny": (-74.25, 40.85),
    "syd": (150.9, -33.8),
    "lag": (3.5, 6.75),
    "mum": (73.1, 19.15),
    "che": (80.0, 13.1),
    "hk": (114.1, 22.55),
    "tok": (139.5, 35.8),
    "osa": (135.6, 34.8),
    "man": (121.05, 14.75),
    "jak": (106.85, -6.4),
    "lon": (-0.4, 51.5),
    "mia": (-80.4, 25.9),
    "lim": (-76.95, -12.0),
    "sf": (-122.2, 37.75),
}
cities = {}
for cid, (lo, la) in CITY_LL.items():
    lo, la = NUDGE.get(cid, (lo, la))
    x, y = proj(lo, la)
    cities[cid] = [round(x, 1), round(y, 1)]

off = [c for c, (x, y) in cities.items() if not point_in(land_rings, x, y)]
print("cities offshore:", off)

near = []
ids = list(cities)
for i, a in enumerate(ids):
    for b in ids[i + 1 :]:
        d = math.dist(cities[a], cities[b])
        if d < 34:
            near.append((round(d, 1), a, b))
print("closest pairs:", sorted(near)[:12])

OCEANS = [
    ("NORTH ATLANTIC OCEAN", -45, 33, 0),
    ("SOUTH ATLANTIC OCEAN", -18, -28, 0),
    ("PACIFIC OCEAN", -104, -8, 0),
    ("PACIFIC OCEAN", 139, 19, 0),
    ("INDIAN OCEAN", 78, -24, 0),
    ("ARCTIC OCEAN", 0, 75, 0),
    ("Mediterranean Sea", 18, 35.2, 1),
    ("Arabian Sea", 63, 15, 1),
    ("Bay of Bengal", 88.5, 15, 1),
    ("South China Sea", 114, 14.5, 1),
    ("Gulf of Mexico", -90, 25.2, 1),
    ("Caribbean Sea", -75, 15, 1),
    ("Tasman Sea", 155, -41, 1),
    ("Sea of Japan", 135, 40, 1),
    ("Coral Sea", 155, -18, 1),
]
oceans = [[n, *(round(v, 1) for v in proj(lo, la)), small] for n, lo, la, small in OCEANS]

data = {
    "W": W,
    "H": H,
    "land": to_d(land_rings, True),
    "borders": to_d(borders, False),
    "lakes": to_d(lakes, True),
    "cities": cities,
    "oceans": oceans,
}
out = HERE.parent / "src" / "pandemic" / "web" / "static" / "map-data.js"
out.write_text(
    "// generated by build_map.py from Natural Earth 1:50m data\nwindow.MAP = "
    + json.dumps(data, separators=(",", ":"))
    + ";\n"
)
print(
    f"W={W} H={H} land={len(data['land']) // 1024}KB borders={len(data['borders']) // 1024}KB lakes={len(data['lakes']) // 1024}KB -> {out.stat().st_size // 1024}KB"
)
