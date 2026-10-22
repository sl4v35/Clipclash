"""
Generate a Guy Harvey-inspired marine wildlife relief STL (sailfish / billfish
wall plaque) for 3D printing.

Guy Harvey is famous for billfish (sailfish, marlin, tuna) line-art marine art.
We build the side-profile silhouette by unioning simple primitive polygons
(body, tall dorsal sail, forked tail) with shapely, then extrude into a
guaranteed closed / watertight binary STL with trimesh.

Output: guy_harvey_sailfish.stl  (binary STL, mm units)
"""
import math
import numpy as np
from shapely.geometry import Polygon
from shapely.ops import unary_union
import trimesh

# ----------------------------------------------------------------------------
# Design parameters (mm)
# ----------------------------------------------------------------------------
PLATE_W   = 200.0   # back plate width   (x)
PLATE_H   = 140.0   # back plate height  (y)
PLATE_T   = 1.8     # back plate thickness (z)
RELIEF_T  = 2.2     # raised relief thickness (z)
TOTAL_T   = PLATE_T + RELIEF_T
MARGIN    = 14.0    # plate margin around fish

# ----------------------------------------------------------------------------
# Build the side-profile silhouette (relative coords x in [0,1], y in [-1,1])
# ----------------------------------------------------------------------------
def interp(xs, ys, x):
    return float(np.interp(x, xs, ys))

stations_x = [0.00, 0.08, 0.20, 0.34, 0.52, 0.70, 0.86, 1.00]
stations_t = [0.06, 0.16, 0.34, 0.62, 0.68, 0.55, 0.30, 0.12]   # top half-height
stations_b = [-0.06, -0.12, -0.26, -0.42, -0.44, -0.38, -0.24, -0.12]  # bottom

n_body = 60
top_pts = []
bottom_pts = []
for i in range(n_body + 1):
    x = i / n_body
    top_pts.append((x, interp(stations_x, stations_t, x)))
    bottom_pts.append((x, interp(stations_x, stations_b, x)))

body = Polygon(top_pts + bottom_pts[::-1])

def body_top_at(x):
    return interp(stations_x, stations_t, x)

# Dorsal sail (tall fin along the back) -> Guy Harvey signature look
sail_x0, sail_x1 = 0.28, 0.70
sail = Polygon([
    (sail_x0, body_top_at(sail_x0)),
    (sail_x0, 0.78),
    (0.42, 1.02),
    (0.60, 0.86),
    (sail_x1, body_top_at(sail_x1)),
])

# Forked tail fin extending past the peduncle
tail = Polygon([
    (0.86, body_top_at(0.86)),                  # peduncle top
    (1.02, 0.62),                               # upper lobe lead
    (1.16, 0.48),                               # upper lobe tip
    (1.10, 0.00),                               # tail notch (centre)
    (1.16, -0.48),                              # lower lobe tip
    (1.02, -0.62),                              # lower lobe lead
    (0.86, interp(stations_x, stations_b, 0.86)),  # peduncle bottom
])

silhouette = unary_union([body, sail, tail]).buffer(0)
assert silhouette.geom_type == "Polygon"
assert silhouette.is_valid and silhouette.area > 0

# Exterior ring (CCW), relative coords
ext = list(silhouette.exterior.coords[:-1])
print(f"Silhouette: {len(ext)} exterior vertices, area={silhouette.area:.3f} rel^2")

# ----------------------------------------------------------------------------
# Scale + translate to fit inside the plate with a margin (uniform scale)
# ----------------------------------------------------------------------------
rel = np.array(ext)
x_span = rel[:, 0].max() - rel[:, 0].min()
y_span = rel[:, 1].max() - rel[:, 1].min()
SCALE = min((PLATE_W - 2 * MARGIN) / x_span, (PLATE_H - 2 * MARGIN) / y_span)
rel_min = rel.min(axis=0)
rel_max = rel.max(axis=0)
off_x = (PLATE_W - (rel_max[0] - rel_min[0]) * SCALE) / 2.0 - rel_min[0] * SCALE
off_y = (PLATE_H - (rel_max[1] - rel_min[1]) * SCALE) / 2.0 - rel_min[1] * SCALE

def to_mm(p):
    return (p[0] * SCALE + off_x, p[1] * SCALE + off_y)

ring_mm = [to_mm(p) for p in ext]
xs = [p[0] for p in ring_mm]; ys = [p[1] for p in ring_mm]
print(f"Fish mm bounds: x[{min(xs):.1f},{max(xs):.1f}] y[{min(ys):.1f},{max(ys):.1f}]")
print(f"Plate: x[0,{PLATE_W}] y[0,{PLATE_H}]")
assert min(xs) >= 0 and max(xs) <= PLATE_W
assert min(ys) >= 0 and max(ys) <= PLATE_H

poly = Polygon(ring_mm)
assert poly.is_valid and poly.area > 0

# ----------------------------------------------------------------------------
# Extrude into a closed, watertight prism (trimesh guarantees manifold output)
# ----------------------------------------------------------------------------
mesh = trimesh.creation.extrude_polygon(poly, height=TOTAL_T)
print(f"Watertight: {mesh.is_watertight}  |  vertices: {len(mesh.vertices)}  |  faces: {len(mesh.faces)}")
assert mesh.is_watertight, "extruded mesh is not watertight"

mesh.export("guy_harvey_sailfish.stl")
print(f"Saved guy_harvey_sailfish.stl, thickness={TOTAL_T} mm")
print(f"STL z-range: 0 to {TOTAL_T} mm")
