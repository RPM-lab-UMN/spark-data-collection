"""
Parametric CadQuery rebuild of 2f85_d405_mount_v2.stl.

This version follows the mesh-fitted feature decomposition:
  - rear cradle/body profile = central cup + half-annulus U cradle
  - front cup/body profile with sloped underside cut
  - exact front camera mounting plate profile with counterbores
  - lower tilted 48x52x6 rounded-rectangle plate with two normal through holes
    shifted down the plate to clear the attached D405 body

Units: millimetres. Coordinates match the original STL.
"""
from __future__ import annotations

import math
from pathlib import Path

import cadquery as cq
from cadquery import exporters
import shapely.geometry as sg
import shapely.ops as so

# -------------------------
# Parameters extracted from STL
# -------------------------
FN_MAIN = 96
FN_SMALL = 48

# upper cradle/cup
OUTER_R = 42.5
INNER_R = 37.5
BODY_HALF_X = 23.9276371
BODY_BOTTOM_Z = -55.0
BODY_BOTTOM_FILLET_R = 4.0
Y_REAR = -2.6
Y_CRADLE_FRONT = -20.8
Y_CUP_FRONT = -35.8

# front/camera plate
Y_FRONT = -41.8
FRONT_TOP_Z = -17.35
FRONT_SIDE_TOP_Z = -19.945
FRONT_TOP_HALF_X = 22.186
FRONT_BOTTOM_Z = -40.0
FRONT_BOTTOM_FILLET_R = 4.0
CAM_HOLE_X = 6.0
CAM_HOLE_Z = -27.0
CAM_THROUGH_D = 4.5
CAM_COUNTERBORE_D = 8.0
CAM_COUNTERBORE_Y_REAR = -37.8

# lower tilted mounting plate
LOWER_WIDTH = 48.0
LOWER_HALF_X = LOWER_WIDTH / 2.0
LOWER_LENGTH = 52.0
LOWER_CORNER_R = 5.0
LOWER_THICK = 5.9560
LOWER_REFERENCE_ANGLE_DEG = 35.058317744437524
LOWER_ANGLE_DEG = 30.0
# Physical forward lead-in before the tilted D405 plate begins.
LOWER_FLAT_LEAD_IN = 0.0
LOWER_S0 = 45.9405
LOWER_U_INNER = 25.9418
LOWER_HOLE_X = 10.0
# Local S runs from the upper/saddle end of the tilted plate toward the lower
# free end. The first-print view recommendation is 30 deg pitch, 0 mm lead-in,
# and a 37 mm D405 M3 hole station.
LOWER_HOLE_S = 37.0
LOWER_HOLE_D = 3.4

# sloped undercut under the front cup/body: plane y + z = UNDERCUT_C
UNDERCUT_C = -78.9230


def circle_poly(r: float, fn: int = FN_MAIN) -> sg.Polygon:
    return sg.Point(0, 0).buffer(r, resolution=max(4, fn // 4))


def rounded_rect_poly(x0: float, z0: float, x1: float, z1: float, r: float, resolution: int = 12) -> sg.Polygon:
    core = sg.box(x0 + r, z0 + r, x1 - r, z1 - r)
    return core.buffer(r, resolution=resolution, join_style=1)


def bottom_rounded_rect_profile(
    half_x: float,
    z_bottom: float,
    z_top: float,
    r: float,
    top_half_x: float | None = None,
    side_top_z: float | None = None,
    fn: int = FN_SMALL,
) -> sg.Polygon:
    if top_half_x is None:
        top_half_x = half_x
    if side_top_z is None:
        side_top_z = z_top
    pts: list[tuple[float, float]] = []
    pts.append((-top_half_x, z_top))
    pts.append((top_half_x, z_top))
    pts.append((half_x, side_top_z))
    pts.append((half_x, z_bottom + r))
    steps = max(6, fn // 4)
    cx, cz = half_x - r, z_bottom + r
    for i in range(1, steps + 1):
        a = math.radians(0 - 90 * i / steps)
        pts.append((cx + r * math.cos(a), cz + r * math.sin(a)))
    pts.append((-half_x + r, z_bottom))
    cx, cz = -half_x + r, z_bottom + r
    for i in range(1, steps + 1):
        a = math.radians(-90 - 90 * i / steps)
        pts.append((cx + r * math.cos(a), cz + r * math.sin(a)))
    pts.append((-half_x, side_top_z))
    pts.append((-top_half_x, z_top))
    return sg.Polygon(pts).buffer(0)


def half_annulus_profile() -> sg.Polygon:
    outer = circle_poly(OUTER_R, FN_MAIN)
    inner = circle_poly(INNER_R, FN_MAIN)
    annulus = outer.difference(inner)
    clip = sg.box(-OUTER_R - 1, -OUTER_R - 10, OUTER_R + 1, 0.0)
    return annulus.intersection(clip).buffer(0)


def central_cup_profile() -> sg.Polygon:
    body = bottom_rounded_rect_profile(
        half_x=BODY_HALF_X,
        z_bottom=BODY_BOTTOM_Z,
        z_top=0.5,
        r=BODY_BOTTOM_FILLET_R,
        fn=FN_SMALL,
    )
    inner = circle_poly(INNER_R, FN_MAIN)
    prof = body.difference(inner)
    prof = prof.intersection(sg.box(-100, -100, 100, 0.0)).buffer(0)
    return prof


def _poly_points(poly: sg.Polygon) -> list[tuple[float, float]]:
    coords = list(poly.exterior.coords)
    # Remove the duplicate last coordinate for CadQuery's polyline().close().
    if len(coords) > 1 and coords[0] == coords[-1]:
        coords = coords[:-1]
    return [(float(x), float(z)) for x, z in coords]


def extrude_xz(poly: sg.Polygon, y_min: float, y_max: float) -> cq.Workplane:
    return (
        cq.Workplane("XZ", origin=(0, y_max, 0))
        .polyline(_poly_points(poly))
        .close()
        .extrude(y_max - y_min)
    )


def sloped_undercut_cutter(x_half: float = 80.0, y0: float = -60.0, y1: float = 5.0, z_bottom: float = -160.0) -> cq.Workplane:
    c = UNDERCUT_C
    profile = [
        (y0, z_bottom),
        (y1, z_bottom),
        (y1, c - y1),
        (y0, c - y0),
    ]
    return cq.Workplane("YZ", origin=(-x_half, 0, 0)).polyline(profile).close().extrude(2 * x_half)


def make_rear_body() -> cq.Workplane:
    rear_profile = so.unary_union([central_cup_profile(), half_annulus_profile()]).buffer(0)
    return extrude_xz(rear_profile, Y_CRADLE_FRONT, Y_REAR)


def make_front_cup() -> cq.Workplane:
    cup = extrude_xz(central_cup_profile(), Y_CUP_FRONT, Y_CRADLE_FRONT)
    return cup.cut(sloped_undercut_cutter())


def make_front_plate() -> cq.Workplane:
    prof = bottom_rounded_rect_profile(
        half_x=BODY_HALF_X,
        z_bottom=FRONT_BOTTOM_Z,
        z_top=FRONT_TOP_Z,
        r=FRONT_BOTTOM_FILLET_R,
        top_half_x=FRONT_TOP_HALF_X,
        side_top_z=FRONT_SIDE_TOP_Z,
        fn=FN_SMALL,
    )
    plate = extrude_xz(prof, Y_FRONT, Y_CUP_FRONT)
    for sx in (-CAM_HOLE_X, CAM_HOLE_X):
        through = (
            cq.Workplane("XZ", origin=(0, Y_CUP_FRONT + 0.1, 0))
            .center(sx, CAM_HOLE_Z)
            .circle(CAM_THROUGH_D / 2.0)
            .extrude((Y_CUP_FRONT - Y_FRONT) + 0.4)
        )
        plate = plate.cut(through)
        counter = (
            cq.Workplane("XZ", origin=(0, CAM_COUNTERBORE_Y_REAR + 0.1, 0))
            .center(sx, CAM_HOLE_Z)
            .circle(CAM_COUNTERBORE_D / 2.0)
            .extrude((CAM_COUNTERBORE_Y_REAR - Y_FRONT) + 0.2)
        )
        plate = plate.cut(counter)
    return plate


def make_lower_plate() -> cq.Workplane:
    # Build local plate in XY, with local s/Y running from 0 at the top end
    # to LOWER_LENGTH at the bottom end, and local Z running through thickness.
    tilted = (
        cq.Workplane("XY", origin=(0, LOWER_LENGTH / 2.0, 0))
        .rect(LOWER_WIDTH, LOWER_LENGTH)
        .extrude(LOWER_THICK)
    )
    tilted = tilted.edges("|Z").fillet(LOWER_CORNER_R)
    for sx in (-LOWER_HOLE_X, LOWER_HOLE_X):
        hole = (
            cq.Workplane("XY", origin=(0, LOWER_HOLE_S, -0.05))
            .center(sx, 0)
            .circle(LOWER_HOLE_D / 2.0)
            .extrude(LOWER_THICK + 0.1)
        )
        tilted = tilted.cut(hole)
    theta = math.radians(LOWER_ANGLE_DEG)
    ref_theta = math.radians(LOWER_REFERENCE_ANGLE_DEG)
    ref_t = cq.Vector(0.0, -math.sin(ref_theta), -math.cos(ref_theta))
    ref_n = cq.Vector(0.0, math.cos(ref_theta), -math.sin(ref_theta))
    # p0 is the local origin at top/inner face. Keep this saddle anchor fixed
    # while sweeping angle; otherwise shallower plates detach from the mount.
    p0 = ref_t.multiply(LOWER_S0).add(ref_n.multiply(LOWER_U_INNER))
    tilted_p0 = p0.add(cq.Vector(0.0, -LOWER_FLAT_LEAD_IN, 0.0))
    # Rotate local +Y/+Z into global t/n. Rotation about X by -(90+angle).
    tilted = tilted.rotate((0, 0, 0), (1, 0, 0), -(90.0 + LOWER_ANGLE_DEG))
    tilted = tilted.translate((tilted_p0.x, tilted_p0.y, tilted_p0.z))

    if LOWER_FLAT_LEAD_IN <= 0.0:
        return tilted

    # The lead-in is a real flat shelf extending forward in -Y from the saddle
    # to the start of the tilted plate. A triangular filler at the kink turns
    # the corner contact into a continuous printable bracket transition.
    lead_in = (
        cq.Workplane("XY", origin=(0, p0.y - LOWER_FLAT_LEAD_IN / 2.0, p0.z - LOWER_THICK))
        .rect(LOWER_WIDTH, LOWER_FLAT_LEAD_IN)
        .extrude(LOWER_THICK)
    )
    try:
        lead_in = lead_in.edges("|Z").fillet(min(LOWER_CORNER_R, LOWER_FLAT_LEAD_IN / 2.0 - 0.05))
    except Exception:
        pass

    n = cq.Vector(0.0, math.cos(theta), -math.sin(theta))
    plate_outer = tilted_p0.add(n.multiply(LOWER_THICK))
    shelf_bottom = tilted_p0.add(cq.Vector(0.0, 0.0, -LOWER_THICK))
    kink_filler = (
        cq.Workplane("YZ", origin=(-LOWER_WIDTH / 2.0, 0.0, 0.0))
        .polyline([
            (tilted_p0.y, tilted_p0.z),
            (plate_outer.y, plate_outer.z),
            (shelf_bottom.y, shelf_bottom.z),
        ])
        .close()
        .extrude(LOWER_WIDTH)
    )

    return lead_in.union(kink_filler).union(tilted)


def build_model() -> cq.Workplane:
    model = make_rear_body().union(make_front_cup()).union(make_front_plate()).union(make_lower_plate())
    try:
        model = model.clean()
    except Exception:
        pass
    return model


result = build_model()


def export(out_dir: str | Path = "/mnt/data") -> None:
    out = Path(out_dir)
    exporters.export(result, str(out / "d405_mount_parametric.step"))
    exporters.export(result, str(out / "d405_mount_parametric.stl"), tolerance=0.05, angularTolerance=0.05)
    exporters.export(result, str(out / "d405_mount_parametric.brep"))
    bb = result.val().BoundingBox()
    print(f"bounds: x[{bb.xmin:.3f},{bb.xmax:.3f}] y[{bb.ymin:.3f},{bb.ymax:.3f}] z[{bb.zmin:.3f},{bb.zmax:.3f}]")
    print(f"extents: {bb.xlen:.3f} x {bb.ylen:.3f} x {bb.zlen:.3f} mm")


if __name__ == "__main__":
    export(Path(__file__).resolve().parent)
