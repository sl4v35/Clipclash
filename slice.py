"""
Slice guy_harvey_sailfish.stl into Marlin-flavor G-code for a Creality Ender 3 V2.

Tuned for: PLA filament (1.75mm), 0.40mm nozzle, aluminum build plate.
Output: guy_harvey_sailfish_ender3v2_pla.gcode  (ready to print from SD card)
"""
import math
import numpy as np
from stl import Mesh
from shapely.geometry import LineString, MultiLineString, box
from shapely.ops import polygonize

# ----------------------------------------------------------------------------
# Printer / material settings (Creality Ender 3 V2, PLA, aluminum bed)
# ----------------------------------------------------------------------------
LAYER_H   = 0.20      # mm
LINE_W    = 0.40      # mm (nozzle diameter)
NUM_WALLS = 2
FIL_DIA   = 1.75      # mm
INFILL_DENSITY = 0.15 # 15%
INFILL_ANGLE   = 45.0 # degrees
SOLID_LAYERS   = 3    # solid bottom + top layers

# speeds in mm/s -> converted to mm/min for G-code F
SPEED_FIRST = 15.0      # first layer: slow for maximum bed adhesion
SPEED_WALL  = 25.0      # walls: slower for steadier extrusion
SPEED_INFILL= 30.0      # infill: was 80, now much slower for reliable flow
SPEED_SOLID = 25.0      # solid layers
SPEED_TRAVEL= 80.0      # travel: reduced to minimize vibration
SPEED_Z     = 30.0      # mm/s for Z moves

# extrusion multiplier (>1.0 pushes more filament; helps bed adhesion)
EXTRUSION_MULTIPLIER = 1.30
FIRST_LAYER_MULT     = 1.40   # extra flow on first layer for squish

# brim for bed adhesion (printed on first layer around the part)
BRIM_WIDTH  = 10.0      # mm
BRIM_LINES  = max(1, int(BRIM_WIDTH / LINE_W))

# temperatures
TEMP_NOZZLE_FIRST = 225  # hotter first layer = better flow + adhesion
TEMP_NOZZLE       = 205
TEMP_BED_FIRST    = 65   # hotter aluminum bed = better first-layer stick
TEMP_BED          = 60

# derived
LAYER_H_MM   = LAYER_H
E_PER_MM     = ((LINE_W * LAYER_H) / (math.pi * (FIL_DIA/2.0)**2)) * EXTRUSION_MULTIPLIER  # mm filament / mm travel
WALL_INSET   = LINE_W / 2.0                    # outer wall centerline inset from edge
INFILL_SPACING = LINE_W / INFILL_DENSITY       # mm
INFILL_INSET   = WALL_INSET + NUM_WALLS*LINE_W          # infill meets the walls

TOTAL_T = 4.0  # matches gen_model.py (plate 1.8 + relief 2.2)
N_LAYERS = int(round(TOTAL_T / LAYER_H))  # 20

def s(ms):  # mm/s -> mm/min
    return ms * 60.0

# ----------------------------------------------------------------------------
# Load STL
# ----------------------------------------------------------------------------
mesh = Mesh.from_file("guy_harvey_sailfish.stl")
tris = mesh.vectors  # (n,3,3)

# ----------------------------------------------------------------------------
# Compute the 2D print region by slicing the mesh at mid-height (clean plane,
# no degenerate hits on the top/bottom caps). Valid because the model is a
# vertical prism: every layer has the same XY footprint.
# ----------------------------------------------------------------------------
def segments_at_z(z):
    segs = []
    for tri in tris:
        zs = tri[:, 2]
        zmin, zmax = float(zs.min()), float(zs.max())
        if not (zmin < z < zmax):
            continue
        pts = []
        for k in range(3):
            p = tri[k]; q = tri[(k+1) % 3]
            zp, zq = float(p[2]), float(q[2])
            if (zp - z) * (zq - z) <= 0 and abs(zq - zp) > 1e-9:
                t = (z - zp) / (zq - zp)
                pts.append((float(p[0] + t*(q[0]-p[0])),
                            float(p[1] + t*(q[1]-p[1]))))
        # dedupe
        uniq = []
        for p in pts:
            if not any(abs(p[0]-u[0]) < 1e-6 and abs(p[1]-u[1]) < 1e-6 for u in uniq):
                uniq.append(p)
        if len(uniq) >= 2:
            # snap to 0.001 mm so adjacent segments share exact endpoints
            segs.append(LineString([(round(a,3), round(b,3)) for a,b in uniq[:2]]))
    return segs

MID_Z = TOTAL_T / 2.0
segs = segments_at_z(MID_Z)
ml = MultiLineString(segs)
polys = list(polygonize(ml))
if not polys:
    raise SystemExit("Failed to polygonize slice at mid-height")
REGION = max(polys, key=lambda p: p.area)
REGION = REGION.buffer(0)
print(f"Slice region area: {REGION.area:.1f} mm^2  bounds: {REGION.bounds}")

# wall / infill geometry (2D, in XY)
wall_centers = []
d = WALL_INSET
for _ in range(NUM_WALLS):
    off = REGION.buffer(-d)
    if off.is_empty or off.area <= 0:
        break
    # exterior ring (CCW)
    ring = getattr(off, "exterior", None)
    if ring is not None:
        wall_centers.append([(float(a), float(b)) for a, b in ring.coords[:-1]])
    d += LINE_W

INFILL_REGION = REGION.buffer(-INFILL_INSET)
if INFILL_REGION.is_empty or INFILL_REGION.area <= 0:
    INFILL_REGION = REGION  # fallback

print(f"Wall contours: {len(wall_centers)}   infill spacing: {INFILL_SPACING:.2f} mm")

# brim contours (outward offsets from region, printed on first layer only)
brim_centers = []
d = LINE_W
for _ in range(BRIM_LINES):
    off = REGION.buffer(d)
    if off.is_empty or off.area <= 0:
        break
    ring = getattr(off, "exterior", None)
    if ring is not None:
        brim_centers.append([(float(a), float(b)) for a, b in ring.coords[:-1]])
    d += LINE_W

print(f"Brim contours: {len(brim_centers)}   brim width: {BRIM_WIDTH} mm")

# ----------------------------------------------------------------------------
# G-code writer
# ----------------------------------------------------------------------------
lines = []
cx = cy = 0.0      # current XY
ce = 0.0           # current absolute extrusion (mm)

def emit(text):
    lines.append(text)

def travel(x, y, feed):
    global cx, cy
    if abs(x-cx) > 1e-6 or abs(y-cy) > 1e-6:
        emit(f"G1 X{x:.3f} Y{y:.3f} F{feed:.1f}")
        cx, cy = x, y

def extrude_to(x, y, feed, mult=1.0):
    """Move to (x,y) extruding, advancing absolute E."""
    global cx, cy, ce
    dist = math.hypot(x-cx, y-cy)
    if dist < 1e-9:
        return
    ce += E_PER_MM * mult * dist
    emit(f"G1 X{x:.3f} Y{y:.3f} E{ce:.4f} F{feed:.1f}")
    cx, cy = x, y

def z_move(z):
    emit(f"G1 Z{z:.3f} F{s(SPEED_Z):.0f}")

def line_coords(g):
    """Return a list of coordinate lists from a shapely intersection result,
    skipping Points / empties / anything that isn't a printable line."""
    if g is None or g.is_empty:
        return []
    t = g.geom_type
    if t == "LineString":
        return [list(g.coords)]
    if t == "MultiLineString":
        return [list(c.coords) for c in g.geoms]
    return []  # Point, GeometryCollection, Polygon -> skip

def print_path(points, feed, closed=True, mult=1.0):
    """points: list of (x,y). Extrude through them; optionally close the loop."""
    if not points:
        return
    travel(points[0][0], points[0][1], s(SPEED_TRAVEL))
    for p in points[1:]:
        extrude_to(p[0], p[1], feed, mult)
    if closed and len(points) > 1:
        extrude_to(points[0][0], points[0][1], feed, mult)

def print_infill(feed, mult=1.0):
    """Parallel infill lines clipped to INFILL_REGION."""
    theta = math.radians(INFILL_ANGLE)
    u = (math.cos(theta), math.sin(theta))
    n = (-math.sin(theta), math.cos(theta))
    minx, miny, maxx, maxy = INFILL_REGION.bounds
    cx0, cy0 = (minx+maxx)/2.0, (miny+maxy)/2.0
    corners = [(minx,miny),(maxx,miny),(maxx,maxy),(minx,maxy)]
    dmin = min((p[0]-cx0)*n[0]+(p[1]-cy0)*n[1] for p in corners)
    dmax = max((p[0]-cx0)*n[0]+(p[1]-cy0)*n[1] for p in corners)
    umin = min((p[0]-cx0)*u[0]+(p[1]-cy0)*u[1] for p in corners)
    umax = max((p[0]-cx0)*u[0]+(p[1]-cy0)*u[1] for p in corners)
    d = dmin
    first = True
    while d <= dmax + 1e-9:
        p0 = (cx0 + d*n[0] + umin*u[0], cy0 + d*n[1] + umin*u[1])
        p1 = (cx0 + d*n[0] + umax*u[0], cy0 + d*n[1] + umax*u[1])
        for coords in line_coords(LineString([p0, p1]).intersection(INFILL_REGION)):
            if len(coords) < 2:
                continue
            # serpentine: alternate direction to cut travel
            if not first:
                coords = coords[::-1]
            first = False
            travel(coords[0][0], coords[0][1], s(SPEED_TRAVEL))
            for p in coords[1:]:
                extrude_to(p[0], p[1], feed, mult)
        d += INFILL_SPACING

def print_solid(feed, angle, mult=1.0):
    """Solid fill: parallel lines at `angle`, spacing = line width, over REGION."""
    theta = math.radians(angle)
    u = (math.cos(theta), math.sin(theta))
    n = (-math.sin(theta), math.cos(theta))
    minx, miny, maxx, maxy = REGION.bounds
    cx0, cy0 = (minx+maxx)/2.0, (miny+maxy)/2.0
    corners = [(minx,miny),(maxx,miny),(maxx,maxy),(minx,maxy)]
    dmin = min((p[0]-cx0)*n[0]+(p[1]-cy0)*n[1] for p in corners)
    dmax = max((p[0]-cx0)*n[0]+(p[1]-cy0)*n[1] for p in corners)
    umin = min((p[0]-cx0)*u[0]+(p[1]-cy0)*u[1] for p in corners)
    umax = max((p[0]-cx0)*u[0]+(p[1]-cy0)*u[1] for p in corners)
    spacing = LINE_W * 0.95  # slight overlap for a solid surface
    d = dmin
    while d <= dmax + 1e-9:
        p0 = (cx0 + d*n[0] + umin*u[0], cy0 + d*n[1] + umin*u[1])
        p1 = (cx0 + d*n[0] + umax*u[0], cy0 + d*n[1] + umax*u[1])
        for coords in line_coords(LineString([p0, p1]).intersection(REGION)):
            if len(coords) < 2:
                continue
            travel(coords[0][0], coords[0][1], s(SPEED_TRAVEL))
            for p in coords[1:]:
                extrude_to(p[0], p[1], feed, mult)
        d += spacing

# ============================================================================
# START G-CODE
# ============================================================================
emit("; Guy Harvey-inspired Sailfish wall plaque")
emit("; Sliced for: Creality Ender 3 V2  |  PLA 1.75mm  |  0.40mm nozzle")
emit(f"; Layer height: {LAYER_H} mm  |  Walls: {NUM_WALLS}  |  Infill: {int(INFILL_DENSITY*100)}%")
emit(f"; Bed: aluminum  |  First layer: {TEMP_NOZZLE_FIRST}C/{TEMP_BED_FIRST}C  |  Thereafter: {TEMP_NOZZLE}C/{TEMP_BED}C")
emit("; ============================================================")
emit(f"M140 S{TEMP_BED_FIRST}            ; set bed temperature")
emit("M105")
emit(f"M190 S{TEMP_BED_FIRST}            ; wait for bed temperature")
emit(f"M104 S{TEMP_NOZZLE_FIRST}         ; set nozzle temperature (first layer)")
emit(f"M109 S{TEMP_NOZZLE_FIRST}         ; wait for nozzle temperature")
emit("G28                             ; home all axes")
emit("G90                             ; absolute positioning")
emit("M82                             ; absolute extrusion mode")
emit("G92 E0                          ; reset extruder")
emit(f"G1 Z{LAYER_H:.3f} F{s(SPEED_Z):.0f}")
emit("; prime nozzle")
emit("G1 X20 Y120 F3000")
emit(f"G1 X20 Y200 E6.0 F{s(SPEED_FIRST):.0f}")
emit(f"G1 X22 Y200 E6.3 F{s(SPEED_FIRST):.0f}")
emit(f"G1 X22 Y120 E12.6 F{s(SPEED_FIRST):.0f}")
emit("G92 E0")
emit("G1 X150 Y20 F6000")
emit("M107                            ; part cooling fan off (first layer)")
emit("; ============================================================")

total_extrude_mm = 0.0
total_time_s = 0.0

# ============================================================================
# LAYERS
# ============================================================================
for i in range(N_LAYERS):
    z = i * LAYER_H
    solid = (i < SOLID_LAYERS) or (i >= N_LAYERS - SOLID_LAYERS)
    emit(f"; LAYER {i:02d}  Z={z:.3f}  {'SOLID' if solid else 'WALLS+INFILL'}")
    z_move(z)  # layer 0 at Z=0 (first-layer squish on the aluminum bed)
    # temperature / fan after first layer
    if i == 1:
        emit(f"M104 S{TEMP_NOZZLE}          ; nozzle temp for subsequent layers")
        emit(f"M140 S{TEMP_BED}           ; bed temp for subsequent layers")
    if i >= 1:
        emit(f"M106 S255                ; part cooling fan on")

    if solid:
        feed = s(SPEED_FIRST if i == 0 else SPEED_SOLID)
        mult = FIRST_LAYER_MULT if i == 0 else 1.0
        # cross-hatch solid fill (bottom layer 0 = bed adhesion)
        print_solid(feed, 0, mult=mult)
        if i > 0 or N_LAYERS > 1:
            print_solid(feed, 90, mult=mult)
    else:
        wall_feed = s(SPEED_FIRST if i == 0 else SPEED_WALL)
        infill_feed = s(SPEED_FIRST if i == 0 else SPEED_INFILL)
        mult = FIRST_LAYER_MULT if i == 0 else 1.0
        # print brim first on layer 0 for bed adhesion
        if i == 0:
            for contour in brim_centers:
                print_path(contour, wall_feed, closed=True, mult=mult)
        for contour in wall_centers:
            print_path(contour, wall_feed, closed=True, mult=mult)
        print_infill(infill_feed, mult=mult)

# ============================================================================
# END G-CODE
# ============================================================================
emit("; ============================================================")
emit("; End of print")
emit("M107                            ; fan off")
emit("G91                             ; relative positioning")
emit("G1 E-2.0 F2400                  ; retract filament")
emit("G1 Z10 F3000                    ; lift Z")
emit("G90                             ; absolute positioning")
emit("G1 X200 Y200 F6000              ; park head")
emit(f"M104 S0                         ; nozzle off")
emit(f"M140 S0                         ; bed off")
emit("M84                             ; disable motors")

gcode = "\n".join(lines) + "\n"
with open("guy_harvey_sailfish_ender3v2_pla.gcode", "w") as f:
    f.write(gcode)

# estimates
tot_len = 0.0
# rough: re-derive filament from ce at end
print(f"Layers: {N_LAYERS}  |  Final extrusion: {ce:.2f} mm filament  "
      f"|  approx volume: {ce*math.pi*(FIL_DIA/2.0)**2:.1f} mm^3")
print(f"G-code lines: {len(lines)}")
print("Saved guy_harvey_sailfish_ender3v2_pla.gcode")
