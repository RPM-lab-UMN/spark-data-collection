# D405 Wrist Camera Mount

This page documents the current printable wrist mount for placing an Intel
RealSense D405 on the Robotiq 2F-85 gripper.

## Printable Part

The current printed part is tracked in the hardware CAD folder:

- [d405_wrist_mount_30deg_37mm.stl](https://github.com/RPM-lab-UMN/spark-data-collection/raw/main/Hardware/CAD/camera_mounts/d405_wrist_mount/printable/d405_wrist_mount_30deg_37mm.stl)

Repository location:

```text
Hardware/CAD/camera_mounts/d405_wrist_mount/printable/
```

## Editable Source

Editable CAD source is tracked separately from the printable mesh:

- [d405_wrist_mount_parametric.py](https://github.com/RPM-lab-UMN/spark-data-collection/blob/main/Hardware/CAD/camera_mounts/d405_wrist_mount/source/d405_wrist_mount_parametric.py)
- [d405_wrist_mount_30deg_37mm.step](https://github.com/RPM-lab-UMN/spark-data-collection/raw/main/Hardware/CAD/camera_mounts/d405_wrist_mount/source/d405_wrist_mount_30deg_37mm.step)

Repository location:

```text
Hardware/CAD/camera_mounts/d405_wrist_mount/source/
```

The parametric source uses CadQuery and Shapely. Those packages are not part of
the normal data-collection Python environment.

## Geometry

Use this geometry for the current printed mount:

```text
D405 orientation: landscape
Yaw / roll: 0 deg / 0 deg
Plate pitch: 30 deg
D405 M3 hole station: 37 mm
Acceptable station range: 36-38 mm
Flat lead-in before tilted plate: 0 mm
D405 M3 hole X centers: +/-10 mm
```

The gripper-side saddle is not the part being tuned here. The important D405
placement variables are:

- the flat lead-in before the tilted plate
- the tilted plate pitch
- the D405 hole station along the tilted plate

## Interactive Geometry Viewer

Use the standalone viewer to inspect the field-of-view and depth-margin model:

- [Open the D405 wrist camera geometry viewer](./assets/interactive/d405_wrist_camera_geometry/wrist_camera_geometry_gui.html)

The viewer shows:

- the Robotiq finger envelope
- the tilted D405 plate
- the D405 body and optical axis
- the depth/FOV frustum
- the analysis targets used for scoring

## Why 30 Deg

The D405 has an 87 x 58 deg depth FOV and a useful close-range depth envelope.
For this wrist placement, the limiting constraints are:

- vertical FOV margin around the Robotiq fingertip envelope
- minimum depth margin near the closest visible finger/object target
- keeping the object-approach region visible instead of over-focusing on the
  contact patch

The sweep result was a broad useful region around 29-31 deg. The practical
first-print choice is:

```text
30 deg pitch / 37 mm station / 0 mm flat lead-in
```

At that setting, the simplified model gives:

| Check | Result |
|---|---:|
| Important targets visible | 100% |
| Worst vertical FOV margin | 5.9 deg |
| Minimum depth margin | 24.5 mm |
| Pinch point depth | 127.4 mm |

## Landscape Orientation

Keep the D405 in landscape.

The wide 87 deg axis should span the Robotiq opening. Portrait would put the 58
deg axis across the gripper opening and leave little lateral margin.
