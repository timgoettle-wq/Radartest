"""DEKRA-Logo in den Gehäusedeckel setzen.
Aufruf: python3 dekra_deckel.py Top.stl
Benötigt: pip install trimesh manifold3d shapely svgpathtools networkx scipy mapbox_earcut
"""
import os, sys, re, numpy as np, trimesh, manifold3d
from svgpathtools import parse_path
from shapely.geometry import Polygon, box
from shapely.ops import unary_union
from shapely import affinity

HERE = os.path.dirname(os.path.abspath(__file__))
SVG = os.path.join(HERE, '..', 'web', 'static', 'images', 'dekra-logo.svg')
TOP = sys.argv[1] if len(sys.argv) > 1 else 'Top.stl'   # Original-Deckel (STL)
OUT = HERE + '/'

# --- logo -> shapely ---
ds = re.findall(r"d='([^']+)'", open(SVG).read())
shapes = []
for d in ds:
    geom = None
    for sub in parse_path(d).continuous_subpaths():
        pts = []
        for seg in sub:
            n = 2 if seg.__class__.__name__ == 'Line' else 24
            pts += [seg.point(t) for t in np.linspace(0, 1, n, endpoint=False)]
        poly = Polygon([(p.real, -p.imag) for p in pts]).buffer(0)
        geom = poly if geom is None else geom.symmetric_difference(poly)
    shapes.append(geom)
logo = unary_union(shapes)

LOGO_W = 52.0                      # Logo-Breite in mm
minx, miny, maxx, maxy = logo.bounds
s = LOGO_W / (maxx - minx)
CX, CY = -8.0, 28.5                # Mitte der Logo-Fläche auf dem Deckel
logo = affinity.translate(logo, -(minx+maxx)/2, -(miny+maxy)/2)
logo = affinity.scale(logo, s, s, origin=(0, 0))
logo = affinity.translate(logo, CX, CY).buffer(-0.03, join_style=2).simplify(0.02)
print('logo bounds', np.round(logo.bounds, 2))

Z_BOT, Z_TOP = 20.30, 22.48        # Deckelplatte
DEPTH = 0.6                        # Gravurtiefe

def to_manifold(mesh):
    return manifold3d.Manifold(manifold3d.Mesh(
        vert_properties=np.asarray(mesh.vertices, dtype=np.float32),
        tri_verts=np.asarray(mesh.faces, dtype=np.uint32)))
def to_trimesh(mf):
    mm = mf.to_mesh()
    return trimesh.Trimesh(mm.vert_properties[:, :3], mm.tri_verts)
def extrude(geom, z0, h):
    polys = geom.geoms if hasattr(geom, 'geoms') else [geom]
    ms = [trimesh.creation.extrude_polygon(p, h) for p in polys]
    m = trimesh.util.concatenate(ms); m.apply_translation([0, 0, z0]); return m

# --- geschlossene Fläche (abgerundetes Rechteck) ---
PW, PH, R = 58.0, 20.0, 3.0
plate2d = box(CX-PW/2+R, CY-PH/2+R, CX+PW/2-R, CY+PH/2-R).buffer(R, resolution=16)
plate = extrude(plate2d, Z_BOT, Z_TOP - Z_BOT)

top = to_manifold(trimesh.load(TOP))
lid = top + to_manifold(plate)
eps = 0.01
cut = to_manifold(extrude(logo, Z_TOP - DEPTH, DEPTH + 1.0))
lid = lid - cut
inlay = to_manifold(extrude(logo, Z_TOP - DEPTH, DEPTH))
print('lid status', lid.status(), 'inlay', inlay.status())

L = to_trimesh(lid); I = to_trimesh(inlay)
L = max(L.split(only_watertight=False), key=lambda p: len(p.faces))
trimesh.repair.fix_normals(L)
print('lid watertight', L.is_watertight, 'inlay watertight', I.is_watertight, 'vol', round(I.volume,1))
L.export(OUT + 'Top_DEKRA.stl')
I.export(OUT + 'Top_DEKRA_Logo_Inlay.stl')
# 3MF mit beiden Teilen
sc = trimesh.Scene(); sc.add_geometry(L, 'Deckel'); sc.add_geometry(I, 'DEKRA_Logo')
sc.export(OUT + 'Top_DEKRA_2farbig.3mf')
