"""DEKRA-Pfeile statt Waben – Deckel und Unterteil (einfarbig druckbar).

Die Wabenlöcher in Deckelplatte und Boden werden geschlossen und durch ein
Raster aus DEKRA-Pfeilen ersetzt. Wände, Schraubdome und Schienen bleiben unverändert.

Aufruf:     python3 dekra_gehaeuse.py            -> Top_DEKRA.stl, Bottom_DEKRA.stl, Vorschau_DEKRA.png
            PFEIL="10 8.8 10.4" python3 dekra_gehaeuse.py   (Pfeilhöhe, Abstand x, Reihenabstand)
Benötigt:   pip install trimesh manifold3d shapely svgpathtools networkx scipy mapbox_earcut matplotlib
Eingaben:   Top_original.stl, Bottom.stl (Originalteile) und ../web/static/images/dekra-logo.svg
"""
import os, re
import numpy as np, trimesh, manifold3d
from svgpathtools import parse_path
from shapely.geometry import Polygon
from shapely.ops import unary_union
from shapely import affinity

HERE = os.path.dirname(os.path.abspath(__file__))
SVG = os.path.join(HERE, '..', 'web', 'static', 'images', 'dekra-logo.svg')

# ---------------- Einstellungen ----------------
PFEIL_H, PFEIL_DX, PFEIL_DY = [float(v) for v in os.environ.get('PFEIL', '8.0 7.04 8.32').split()]
RAND = 1.6                # Mindeststeg zu Wänden und Schraubdomen
# -----------------------------------------------


def dekra_arrow(height, mirror=False):
    """Letzter Pfad im Logo-SVG = DEKRA-Pfeil, zentriert und auf `height` skaliert."""
    d = re.findall(r"d='([^']+)'", open(SVG).read())[-1]
    pts = []
    for seg in parse_path(d):
        n = 2 if seg.__class__.__name__ == 'Line' else 16
        pts += [seg.point(t) for t in np.linspace(0, 1, n, endpoint=False)]
    a = Polygon([(p.real, -p.imag) for p in pts]).buffer(0)
    x0, y0, x1, y1 = a.bounds
    s = height / (y1 - y0)
    a = affinity.translate(a, -(x0 + x1) / 2, -(y0 + y1) / 2)
    return affinity.scale(a, -s if mirror else s, s, origin=(0, 0)).simplify(0.02)


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


def arrow_grid(arrow, keep):
    """Versetzte Pfeilreihen, gleichmäßig in der Höhe verteilt; nur Pfeile, die ganz in `keep` liegen."""
    x0, y0, x1, y1 = keep.bounds
    n = int((y1 - y0 - PFEIL_H) // PFEIL_DY) + 1
    cx, cy = keep.centroid.x, (y0 + y1) / 2
    cells = []
    for j in range(n):
        y = cy + (j - (n - 1) / 2) * PFEIL_DY
        off = (j % 2) * PFEIL_DX / 2
        for x in np.arange(cx - 12 * PFEIL_DX + off, cx + 12 * PFEIL_DX + off, PFEIL_DX):
            a = affinity.translate(arrow, x, y)
            if keep.contains(a):
                cells.append(a)
    return cells


def replace_holes(mesh, z_floor, z_below, z0, z1, arrow):
    """Wabenlöcher der Platte z0..z1 schließen und Pfeile hineinschneiden.
    z_floor: Schnitthöhe in der Platte, z_below: Schnitthöhe direkt dahinter (Wände/Dome)."""
    plate = section(mesh, z_floor)
    full = unary_union([Polygon(p.exterior) for p in plate])
    holes = unary_union([Polygon(i) for p in plate for i in p.interiors])
    behind = section(mesh, z_below)
    walls = unary_union([Polygon(p.exterior) for p in behind if p.area < 100])  # Dome, Schienen, Laschen
    inner = [Polygon(i) for p in behind for i in p.interiors if Polygon(i).area > 1000]
    keep = (inner[0].buffer(-RAND) if inner else full.buffer(-2.6))
    keep = keep.intersection(full.buffer(-2.6)).difference(walls.buffer(RAND))
    if not inner:   # Deckel: auch die langen Randschienen samt Domen aussparen
        keep = keep.difference(unary_union([Polygon(p.exterior) for p in behind if p.area >= 100]).buffer(RAND))
    cells = arrow_grid(arrow, keep)
    cut = unary_union(cells)
    res = to_mf(mesh) + extrude(holes.buffer(0.05).intersection(full.buffer(-0.01)), z0, z1 - z0)
    res = res - extrude(cut, z0 - 1, z1 - z0 + 2)
    d = min(a.distance(b) for i, a in enumerate(cells) for b in cells[i + 1:]
            if a.centroid.distance(b.centroid) < 2 * PFEIL_DX)
    return to_tm(res), cells, cut.area, holes.area, d


# Deckel: von oben gesehen; Unterteil: von unten gesehen (Pfeil gespiegelt, damit er richtig zeigt)
top = trimesh.load(os.path.join(HERE, 'Top_original.stl'))
L, cells_t, open_t, old_t, d_t = replace_holes(top, 21.4, 19.5, 20.30, 22.48, dekra_arrow(PFEIL_H))
L.export(os.path.join(HERE, 'Top_DEKRA.stl'))

bot = trimesh.load(os.path.join(HERE, 'Bottom.stl'))
B, cells_b, open_b, old_b, d_b = replace_holes(bot, 1.0, 2.5, bot.bounds[0][2], 2.17, dekra_arrow(PFEIL_H, mirror=True))
B.export(os.path.join(HERE, 'Bottom_DEKRA.stl'))

for name, cells, o, old, d in (('Deckel', cells_t, open_t, old_t, d_t), ('Unterteil', cells_b, open_b, old_b, d_b)):
    print(f'{name}: {len(cells)} Pfeile, offen {o:.0f} mm² = {o/old*100:.0f}% der Waben, schmalster Steg {d:.2f} mm')

# =============== Vorschau ===============
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from shapely.plotting import plot_polygon

fig, axs = plt.subplots(1, 2, figsize=(18, 7))
for ax, mesh, z, title, flip in ((axs[0], L, 21.4, 'Deckel – Ansicht von oben', False),
                                 (axs[1], B, 1.0, 'Unterteil – Ansicht von unten', True)):
    for p in section(mesh, z):
        plot_polygon(p, ax=ax, add_points=False, facecolor='#d9d9d9', edgecolor='#555', linewidth=0.4)
    ax.set_aspect('equal'); ax.set_axis_off(); ax.set_title(title, fontsize=14)
    if flip:
        ax.invert_xaxis()
plt.tight_layout()
plt.savefig(os.path.join(HERE, 'Vorschau_DEKRA.png'), dpi=100)
