"""Joint-space start checks shared by the Spark display and controllers."""
from dataclasses import dataclass

import numpy as np

START_TOLERANCE_DEG = 15.0
START_TOLERANCE_RAD = np.deg2rad(START_TOLERANCE_DEG)
JOINT_LABELS = ("Base", "Shoulder", "Elbow", "Wrist 1", "Wrist 2", "Wrist 3")


def joint_alignment(target, actual):
    target, actual = np.asarray(target, dtype=float), np.asarray(actual, dtype=float)
    if target.shape != (6,) or actual.shape != (6,):
        raise ValueError("Alignment requires six joint angles")
    if not np.isfinite(target).all() or not np.isfinite(actual).all():
        raise ValueError("Alignment requires finite joint angles")
    # Compare the exact command, not angles modulo 2pi: a full turn must not
    # disappear from a joint-space engagement check as it does from the FK plot.
    error = target - actual
    return error, bool(np.all(np.abs(error) <= START_TOLERANCE_RAD))


def alignment_text(target, actual, status):
    error, _ = joint_alignment(target, actual)
    rows = [status, "Degrees " + "".join(f"{name:>9}" for name in JOINT_LABELS)]
    for label, values in (("Robot", actual), ("Spark", target), ("Error", error)):
        rows.append(f"{label:<8}" + "".join(f"{v:9.1f}" for v in np.rad2deg(values)))
    rows.append(f"Start requires every joint within {START_TOLERANCE_DEG:g} degrees, then a fresh pedal press.")
    return "\n".join(rows)


@dataclass
class SparkStartGate:
    active: bool = False
    release_seen: bool = False
    blocked_until_release: bool = False

    def update(self, enabled, aligned, valid=True):
        if not enabled:
            self.active = False
            self.release_seen = True
            self.blocked_until_release = False
        elif not valid:
            self.active = False
            self.blocked_until_release = True
        elif not self.active:
            if self.release_seen and aligned and not self.blocked_until_release:
                self.active = True
            else:
                self.blocked_until_release = True
        return self.active
