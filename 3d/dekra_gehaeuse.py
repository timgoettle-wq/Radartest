"""DEKRA-Design für das Gehäuse (einfarbig druckbar).

Deckel:    Wabenlöcher -> DEKRA-Pfeile, DEKRA-Logo in der Mitte eingraviert
Unterteil: Wabenlöcher -> DEKRA-Pfeile, Typenschild-Text eingraviert (von unten lesbar)

Aufruf:     python3 dekra_gehaeuse.py            -> Top_DEKRA.stl, Bottom_DEKRA.stl, Vorschau_DEKRA.png
Benötigt:   pip install trimesh manifold3d shapely svgpathtools networkx scipy mapbox_earcut matplotlib
Eingaben:   Top_original.stl, Bottom.stl (Originalteile) und ../web/static/images/dekra-logo.svg
"""
import os, re
import numpy as np, trimesh, manifold3d
from svgpathtools import parse_path
from shapely.geometry import Polygon, box
from shapely.ops import unary_union
from shapely import affinity
from matplotlib.textpath import TextPath
from matplotlib.font_manager import FontProperties

HERE = os.path.dirname(os.path.abspath(__file__))
SVG = os.path.join(HERE, '..', 'web', 'static', 'images', 'dekra-logo.svg')

# ---------------- Einstellungen ----------------
TEXT_ZEILEN = ['RADARTEST · GERÄT 01', 'T. Goettle · 2026']
TEXT_HOEHE = 4.2          # Versalhöhe in mm
TEXT_TIEFE = 0.6          # Gravurtiefe Text
LOGO_BREITE = 52.0        # DEKRA-Logo auf dem Deckel
LOGO_TIEFE = 0.6
PFEIL_H, PFEIL_DX, PFEIL_DY = [float(v) for v in os.environ.get("PFEIL", "8.0 7.04 8.32").split()]  # Pfeilhöhe, Abstand x, Reihenabstand
RAND = 1.6                # Mindeststeg zu Wänden, Domen, Logo, Text
# -----------------------------------------------


def svg_shapes():
    out = []
    for d in re.findall(r"d='([^']+)'", open(SVG).read()):
        geom = None
        for sub in parse_path(d).continuous_subpaths():
            pts = []
            for seg in sub:
                n = 2 if seg.__class__.__name__ == 'Line' else 24
                pts += [seg.point(t) for t in np.linspace(0, 1, n, endpoint=False)]
            poly = Polygon([(p.real, -p.imag) for p in pts]).buffer(0)
            geom = poly if geom is None else geom.symmetric_difference(poly)
        out.append(geom)
    return out


def fit(geom, width=None, height=None, cx=0.0, cy=0.0, mirror=False):
    x0, y0, x1, y1 = geom.bounds
    s = width / (x1 - x0) if width else height / (y1 - y0)
    g = affinity.translate(geom, -(x0 + x1) / 2, -(y0 + y1) / 2)
    g = affinity.scale(g, -s if mirror else s, s, origin=(0, 0))
    return affinity.translate(g, cx, cy)


def text_geom(lines, cap, line_gap=1.6):
    fp = FontProperties(fname=os.path.join(os.path.dirname(__import__('matplotlib').__file__),
                                           'mpl-data', 'fonts', 'ttf', 'DejaVuSans-Bold.ttf'))
    scale = cap / TextPath((0, 0), 'H', size=1, prop=fp).get_extents().height
    geoms, y = [], 0.0
    for line in lines:
        geom = None
        for ring in TextPath((0, 0), line, size=1, prop=fp).to_polygons():
            if len(ring) < 3:
                continue
            p = Polygon(ring).buffer(0)
            geom = p if geom is None else geom.symmetric_difference(p)
        geom = affinity.scale(geom, scale, scale, origin=(0, 0))
        x0, _, x1, _ = geom.bounds
        geoms.append(affinity.translate(geom, -(x0 + x1) / 2, y))
        y -= cap + line_gap * 1.0 + 1.0
    return unary_union(geoms)


def section(mesh, z):
    return mesh.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1]).to_2D(to_2D=np.eye(4))[0].polygons_full


def to_mf(mesh):
    return manifold3d.Manifold(manifold3d.Mesh(
        vert_properties=np.asarray(mesh.vertices, dtype=np.float32),
        tri_verts=np.asarray(mesh.faces, dtype=np.uint32)))


def to_tm(mf):
    mm = mf.to_mesh()
    t = trimesh.Trimesh(mm.vert_properties[:, :3], mm.tri_verts)
    t = max(t.split(only_watertight=False), key=lambda p: len(p.faces))
    trimesh.repair.fix_normals(t)
    return t


def extrude(geom, z0, h):
    polys = geom.geoms if hasattr(geom, 'geoms') else [geom]
    m = trimesh.util.concatenate([trimesh.creation.extrude_polygon(p, h) for p in polys if p.area > 1e-4])
    m.apply_translation([0, 0, z0])
    return to_mf(m)


def arrow_grid(arrow, keep, rows_y, cx):
    cells = []
    for j, y in enumerate(rows_y):
        off = (j % 2) * PFEIL_DX / 2
        for x in np.arange(cx - 12 * PFEIL_DX + off, cx + 12 * PFEIL_DX + off, PFEIL_DX):
            a = affinity.translate(arrow, x, y)
            if keep.contains(a):
                cells.append(a)
    return cells


def rows_between(y_lo, y_hi):
    n = int((y_hi - y_lo - PFEIL_H) // PFEIL_DY) + 1
    if n <= 0:
        return []
    mid = (y_lo + y_hi) / 2
    return [mid + (r - (n - 1) / 2) * PFEIL_DY for r in range(n)]


shapes = svg_shapes()
logo_raw = unary_union(shapes)
arrow_raw = shapes[-1]

# =============== DECKEL ===============
top = trimesh.load(os.path.join(HERE, 'Top_original.stl'))
ZT0, ZT1 = 20.30, 22.48                                   # Deckelplatte
plate = section(top, 21.4)[0]
plate_full = Polygon(plate.exterior)
plate_holes = unary_union([Polygon(i) for i in plate.interiors])
below = unary_union([Polygon(p.exterior) for p in section(top, 19.5)])  # Wände/Dome/Schienen
LCX, LCY = -8.0, 28.5
logo = fit(logo_raw, width=LOGO_BREITE, cx=LCX, cy=LCY).buffer(-0.03, join_style=2).simplify(0.02)
logo_zone = logo.envelope.buffer(RAND + 0.6, join_style=2)
keep_t = plate_full.buffer(-2.6).difference(below.buffer(RAND)).difference(logo_zone)
arrow_t = fit(arrow_raw, height=PFEIL_H).simplify(0.02)  # von oben lesbar
kb = keep_t.bounds
rows_t = rows_between(kb[1], logo_zone.bounds[1]) + rows_between(logo_zone.bounds[3], kb[3])
cells_t = arrow_grid(arrow_t, keep_t, rows_t, LCX)
cut_t = unary_union(cells_t)
lid = to_mf(top) + extrude(plate_holes.buffer(0.05).intersection(plate_full.buffer(-0.01)), ZT0, ZT1 - ZT0)
lid = lid - extrude(cut_t, ZT0 - 1, ZT1 - ZT0 + 2) - extrude(logo, ZT1 - LOGO_TIEFE, LOGO_TIEFE + 1)
L = to_tm(lid)
L.export(os.path.join(HERE, 'Top_DEKRA.stl'))
print(f'Deckel: {len(cells_t)} Pfeile, offen {cut_t.area:.0f} mm² (Waben: {plate_holes.area:.0f} mm²)')

# =============== UNTERTEIL ===============
bot = trimesh.load(os.path.join(HERE, 'Bottom.stl'))
ZB0, ZB1 = bot.bounds[0][2], 2.17                         # Boden
floor = section(bot, 1.0)
floor_full = unary_union([Polygon(p.exterior) for p in floor])
floor_holes = unary_union([Polygon(i) for p in floor for i in p.interiors])
sec2 = section(bot, 2.5)
inner = max([Polygon(i) for p in sec2 for i in p.interiors], key=lambda q: q.area)
bosses = unary_union([Polygon(p.exterior) for p in sec2 if p.area < 100])
keep_b = inner.buffer(-RAND).difference(bosses.buffer(RAND))
kb = keep_b.bounds
BCX, BCY = keep_b.centroid.x, (kb[1] + kb[3]) / 2
text = text_geom(TEXT_ZEILEN, TEXT_HOEHE)
text = fit(text, height=text.bounds[3] - text.bounds[1], cx=BCX, cy=BCY, mirror=True)  # von unten lesbar
text = text.buffer(-0.02, join_style=2).simplify(0.01)
text_zone = text.envelope.buffer(RAND + 0.6, join_style=2)
keep_b2 = keep_b.difference(text_zone)
arrow_b = fit(arrow_raw, height=PFEIL_H, mirror=True).simplify(0.02)
rows_b = rows_between(kb[1], text_zone.bounds[1]) + rows_between(text_zone.bounds[3], kb[3])
cells_b = arrow_grid(arrow_b, keep_b2, rows_b, BCX)
cut_b = unary_union(cells_b)
base = to_mf(bot) + extrude(floor_holes.buffer(0.05).intersection(floor_full.buffer(-0.01)), ZB0, ZB1 - ZB0)
base = base - extrude(cut_b, ZB0 - 1, ZB1 - ZB0 + 2) - extrude(text, ZB0 - 1, TEXT_TIEFE + 1)
B = to_tm(base)
B.export(os.path.join(HERE, 'Bottom_DEKRA.stl'))
print(f'Unterteil: {len(cells_b)} Pfeile, offen {cut_b.area:.0f} mm² (Waben: {floor_holes.area:.0f} mm²), '
      f'Text {text.bounds[2]-text.bounds[0]:.1f} x {text.bounds[3]-text.bounds[1]:.1f} mm')

# =============== Vorschau ===============
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from shapely.plotting import plot_polygon

fig, axs = plt.subplots(1, 2, figsize=(18, 7))
for ax, mesh, zs, title, flip in ((axs[0], L, (ZT1 - 0.3, ZT0 + 0.3), 'Deckel – Ansicht von oben', False),
                                  (axs[1], B, (ZB0 + 0.3, ZB1 - 0.3), 'Unterteil – Ansicht von unten', True)):
    for z, col in zip(zs, ('#d0d0d0', '#9a9a9a')):
        polys = section(mesh, z)
        if z == zs[1]:   # Gravur: tiefere Ebene dunkler unter die Oberfläche legen
            for p in polys:
                plot_polygon(p, ax=ax, add_points=False, facecolor=col, edgecolor='none')
    for p in section(mesh, zs[0]):
        plot_polygon(p, ax=ax, add_points=False, facecolor='#d9d9d9', edgecolor='#555', linewidth=0.4)
    ax.set_aspect('equal'); ax.set_axis_off(); ax.set_title(title, fontsize=14)
    if flip:
        ax.invert_xaxis()
plt.tight_layout()
plt.savefig(os.path.join(HERE, 'Vorschau_DEKRA.png'), dpi=100)

# =============== Kontrolle: schmalste Stege ===============
for name, cells in (('Deckel', cells_t), ('Unterteil', cells_b)):
    d = min(a.distance(b) for i, a in enumerate(cells) for b in cells[i + 1:]
            if a.centroid.distance(b.centroid) < 2 * PFEIL_DX)
    print(f'{name}: schmalster Steg zwischen Pfeilen {d:.2f} mm')
