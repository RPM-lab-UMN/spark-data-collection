from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "TeleopSoftware"))

from teleop_runtime_core import (  # noqa: E402
    LIGHTNING_OFFSET,
    THUNDER_OFFSET,
    SparkServoConfig,
    TeleopRuntimeState,
    process_spark_mode,
)


class SparkBaseWindingTest(unittest.TestCase):
    def test_equivalent_windings_preserve_calibration_and_commands(self) -> None:
        actual = np.asarray([0.2, -1.2, 1.4, -1.3, -1.0, 0.3])
        for arm, offset in (("Thunder", THUNDER_OFFSET), ("Lightning", LIGHTNING_OFFSET)):
            for turns in (-3, -1, 0, 1, 4):
                with self.subTest(arm=arm, turns=turns):
                    robot = Mock()
                    robot.has_receive.return_value = True
                    robot.getActualQ.return_value = actual.tolist()
                    robot.gripper_enabled.return_value = False
                    fields = {
                        arm: dict(
                            hwc=(600, 600, (300, 300)),
                            Spark_plot=Mock(), point=1,
                            Spark_meter=Mock(), Spark_z_meter=2,
                        )
                    }
                    pubs = {key: Mock() for key in (
                        arm.lower() + "_spark_command_angles",
                        arm.lower() + "_spark_command_gripper",
                        arm + "_teleop_cmd_joint_state",
                        arm + "_teleop_cmd_gripper_state",
                    )}
                    clock = Mock()
                    clock.now.return_value.to_msg.return_value = types.SimpleNamespace(sec=42, nanosec=123)
                    leader = np.r_[actual, 0.0] - offset
                    leader[0] += turns * 2 * np.pi
                    state = TeleopRuntimeState()
                    data = {
                        arm.lower() + "_spark_angle": leader.tolist(),
                        arm.lower() + "_change_mode": True,
                        "lightning_spark_enable": False,
                    }

                    def update() -> None:
                        process_spark_mode(
                            arm=arm, fields=fields, ros_data=data,
                            control_modes={arm: "Spark"}, runtime_state=state,
                            URs=robot, pubs=pubs, optimize=Mock(), clock=clock,
                            servo=SparkServoConfig(0.001, 0.05, 200),
                        )

                    update()
                    np.testing.assert_allclose(leader[:6] + state.homes[arm][:6], actual, atol=1e-12)
                    np.testing.assert_array_equal(state.homes[arm][1:], offset[1:])
                    robot.servoJ.assert_not_called()

                    leader[0] += 0.03
                    data[arm.lower() + "_spark_angle"] = leader.tolist()
                    data["lightning_spark_enable"] = True
                    update()
                    expected = actual + [0.03, 0, 0, 0, 0, 0]
                    robot.servoJ.assert_called_once()
                    self.assertEqual(robot.servoJ.call_args.args[0], arm)
                    np.testing.assert_allclose(robot.servoJ.call_args.args[1][0], expected, atol=1e-12)
                    recorded = pubs[arm + "_teleop_cmd_joint_state"].publish.call_args.args[0]
                    np.testing.assert_allclose(recorded.position, expected, atol=1e-12)


if __name__ == "__main__":
    unittest.main()
