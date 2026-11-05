"""Unterteil: Wabenlöcher im Boden durch DEKRA-Pfeile ersetzen.
Aufruf: python3 dekra_boden_pfeile.py [Pfeilhöhe Abstand_x Abstand_y] [--build]
  ohne --build nur Layout-Vorschau (Layout_Boden_Pfeile.png), mit --build -> Bottom_DEKRA_Pfeile.stl
Benötigt: pip install trimesh manifold3d shapely svgpathtools networkx scipy mapbox_earcut matplotlib
"""
import os, sys, re, numpy as np, trimesh, manifold3d
from svgpathtools import parse_path
from shapely.geometry import Polygon, Point, box
from shapely.ops import unary_union
from shapely import affinity
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
from shapely.plotting import plot_polygon

HERE = os.path.dirname(os.path.abspath(__file__))
SVG = os.path.join(HERE, '..', 'web', 'static', 'images', 'dekra-logo.svg')
BOT = HERE + '/Bottom.stl'
ARGS = [a for a in sys.argv[1:] if not a.startswith('--')]
H = float(ARGS[0]) if len(ARGS) > 0 else 10.0      # Pfeilhöhe mm
DX = float(ARGS[1]) if len(ARGS) > 1 else 8.8     # Abstand x
DY = float(ARGS[2]) if len(ARGS) > 2 else 10.4    # Abstand y (Zeilen)

d = re.findall(r"d='([^']+)'", open(SVG).read())[-1]       # letzter Pfad = Pfeil
pts = []
for seg in parse_path(d):
    n = 2 if seg.__class__.__name__ == 'Line' else 16
    pts += [seg.point(t) for t in np.linspace(0, 1, n, endpoint=False)]
arrow = Polygon([(p.real, -p.imag) for p in pts]).buffer(0)
a0 = arrow
minx, miny, maxx, maxy = arrow.bounds
arrow = affinity.translate(arrow, -(minx+maxx)/2, -(miny+maxy)/2)
arrow = affinity.scale(arrow, -H/(maxy-miny), H/(maxy-miny), origin=(0,0))  # x gespiegelt: von unten lesbar
arrow = arrow.simplify(0.02)

m = trimesh.load(BOT)
Z0, Z1 = m.bounds[0][2], 2.17
sec = m.section(plane_origin=[0,0,1.0], plane_normal=[0,0,1]).to_2D(to_2D=np.eye(4))[0]
floor_full = unary_union([Polygon(p.exterior) for p in sec.polygons_full])
holes = unary_union([Polygon(i) for p in sec.polygons_full for i in p.interiors])
sec2 = m.section(plane_origin=[0,0,2.5], plane_normal=[0,0,1]).to_2D(to_2D=np.eye(4))[0]
# Innenraum = Fläche innerhalb der Innenwand
inner = max([Polygon(i) for p in sec2.polygons_full for i in p.interiors], key=lambda q: q.area)
bosses = [c for c in [Polygon(i) for p in sec2.polygons_full for i in p.interiors] if c.area < 100]
boss_disks = [Polygon(p.exterior) for p in sec2.polygons_full if p.area < 100]
keep = inner.buffer(-1.6)
for b in boss_disks: keep = keep.difference(b.buffer(1.6))
print('bosses', [np.round(b.centroid.coords[0],1) for b in boss_disks])

cx, cy = keep.centroid.x, keep.centroid.y
ib = inner.bounds
cells = []
j = 0
kb = keep.bounds
nrows = int((kb[3]-kb[1]-H)//DY)+1
y0 = (kb[1]+kb[3])/2 - (nrows-1)*DY/2
for y in [y0 + r*DY for r in range(nrows)]:
    off = (j % 2) * DX/2; j += 1
    for x in np.arange(cx - 12*DX + off, cx + 12*DX + off, DX):
        a = affinity.translate(arrow, x, y)
        if keep.contains(a): cells.append(a)
cut2d = unary_union(cells)
# minimale Stegbreite
mind = min(cells[i].distance(cells[k]) for i in range(len(cells)) for k in range(i+1, len(cells)) if cells[i].centroid.distance(cells[k].centroid) < 2*DX)
open_old = holes.area; open_new = cut2d.area
print(f'Pfeile {len(cells)}, min Steg {mind:.2f} mm, offene Fläche alt {open_old:.0f} mm² neu {open_new:.0f} mm² ({open_new/open_old*100:.0f}%)')

fig, ax = plt.subplots(figsize=(12,8))
plot_polygon(floor_full.difference(cut2d), ax=ax, add_points=False, facecolor='#d9d9d9', edgecolor='#555', linewidth=0.5)
for b in boss_disks: plot_polygon(b, ax=ax, add_points=False, facecolor='none', edgecolor='#aaa', linestyle='--')
ax.set_aspect('equal'); ax.invert_xaxis(); ax.set_axis_off(); ax.set_title('Ansicht von unten')
plt.savefig(os.path.join(HERE, 'Layout_Boden_Pfeile.png'), dpi=80, bbox_inches='tight')

if '--build' in sys.argv:
    def to_mf(mesh): return manifold3d.Manifold(manifold3d.Mesh(vert_properties=np.asarray(mesh.vertices,dtype=np.float32), tri_verts=np.asarray(mesh.faces,dtype=np.uint32)))
    def ext(g, z0, h):
        ps = g.geoms if hasattr(g,'geoms') else [g]
        mm = trimesh.util.concatenate([trimesh.creation.extrude_polygon(p, h) for p in ps]); mm.apply_translation([0,0,z0]); return mm
    fill = ext(holes.buffer(0.05).intersection(floor_full.buffer(-0.01)), Z0, Z1-Z0)
    res = to_mf(m) + to_mf(fill) - to_mf(ext(cut2d, Z0-1, Z1-Z0+2))
    mm = res.to_mesh(); R = trimesh.Trimesh(mm.vert_properties[:,:3], mm.tri_verts)
    R = max(R.split(only_watertight=False), key=lambda p: len(p.faces))
    print('status', res.status(), 'watertight', R.is_watertight, 'broken', len(trimesh.repair.broken_faces(R)))
    R.export(HERE + '/Bottom_DEKRA_Pfeile.stl')
