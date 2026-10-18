"""Offline checks: every robot interface is a mock; no hardware connections."""
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'TeleopSoftware'))
from spark_alignment import alignment_text, joint_alignment
from teleop_runtime_core import (LIGHTNING_OFFSET, THUNDER_OFFSET, SparkServoConfig,
    TeleopRuntimeState, process_spark_mode)
from UR.fk import forward_6


class SparkAlignmentChecks:
    def setUp(self):
        self.prefix = self.arm.lower()
        self.offset = THUNDER_OFFSET if self.arm == "Thunder" else LIGHTNING_OFFSET
        self.q = np.array([.2, -1.2, 1.4, -1.3, -1., .3])
        self.robot = Mock()
        self.robot.spark_osc = None
        self.robot.has_receive.return_value = True
        self.robot.getActualQ.return_value = self.q.tolist()
        self.robot.gripper_enabled.return_value = False
        self.fields = {self.arm: dict(hwc=(600, 600, (300, 300)),
            Spark_plot=Mock(), point=1, Spark_meter=Mock(), Spark_z_meter=2,
            Spark_alignment=Mock())}
        self.pubs = {key: Mock() for key in (self.prefix+'_spark_command_angles',
            self.prefix+'_spark_command_gripper', self.arm+'_teleop_cmd_joint_state',
            self.arm+'_teleop_cmd_gripper_state')}
        self.state = TeleopRuntimeState()
        self.data = {self.prefix+"_change_mode": True, "lightning_spark_enable": False}
        self.clock = Mock()
        self.clock.now.return_value.to_msg.return_value = types.SimpleNamespace(sec=1, nanosec=0)

    def update(self, target=None, enabled=False):
        if target is None:
            target = self.q
        self.data[self.prefix+"_spark_angle"] = (np.r_[target, 0.]-self.offset).tolist()
        self.data["lightning_spark_enable"] = enabled
        process_spark_mode(arm=self.arm, fields=self.fields, ros_data=self.data,
            control_modes={self.arm:'Spark'}, runtime_state=self.state, URs=self.robot,
            pubs=self.pubs, optimize=Mock(), clock=self.clock,
            servo=SparkServoConfig(.001, .05, 200))

    def test_equal_position_with_full_turn_is_not_joint_aligned(self):
        for joint in range(6):
            target = self.q.copy(); target[joint] += 2*np.pi
            np.testing.assert_allclose(forward_6(target)[0], forward_6(self.q)[0], atol=1e-12)
            error, aligned = joint_alignment(target, self.q)
            self.assertFalse(aligned)
            self.assertAlmostEqual(np.rad2deg(error[joint]), 360.)
        self.assertIn('360.0', alignment_text(target, self.q, 'BLOCKED'))

    def test_base_mismatch_blocks_command_and_published_command(self):
        target = self.q.copy(); target[0] += np.deg2rad(30)
        self.update(target)
        self.update(target, enabled=True)
        self.robot.servoJ.assert_not_called()
        self.robot.zeroFtSensor.assert_not_called()
        self.pubs[self.prefix+'_spark_command_angles'].publish.assert_not_called()
        self.assertIn('BLOCKED', self.fields[self.arm]['Spark_alignment'].config.call_args.kwargs['text'])

    def test_recorded_robot_and_spark_joint_mismatch_cannot_engage(self):
        if self.arm == 'Thunder':
            actual = [13.75,-129.54,-38.47,-153.52,-75.91,102.61]
            wanted = [187.17,1.65,-24.46,-70.11,-15.13,-170.27]
        else:
            actual = [-185.10,-175.90,-68.94,-132.41,-20.83,102.48]
            wanted = [-164.16,-167.19,-28.14,-201.59,16.67,82.91]
        self.q = np.deg2rad(actual)
        self.robot.getActualQ.return_value = self.q.tolist()
        target = np.deg2rad(wanted)
        self.update(target)
        self.update(target, enabled=True)
        self.robot.servoJ.assert_not_called()
        text = self.fields[self.arm]['Spark_alignment'].config.call_args.kwargs['text']
        self.assertIn('BLOCKED', text)
        self.assertIn('Robot', text)
        self.assertIn('Spark', text)

    def test_each_other_joint_mismatch_blocks_start(self):
        for joint in range(1, 6):
            self.setUp()
            target = self.q.copy(); target[joint] += np.deg2rad(20)
            self.update(target)
            self.update(target, enabled=True)
            self.robot.servoJ.assert_not_called()

    def test_full_base_turn_after_preview_blocks_even_when_plot_identical(self):
        self.update()
        target = self.q.copy(); target[0] += 2*np.pi
        self.update(target, enabled=True)
        self.robot.servoJ.assert_not_called()

    def test_correction_while_pedal_held_requires_release_and_repress(self):
        target = self.q.copy(); target[0] += .5
        self.update(target)
        self.update(target, enabled=True)
        self.update(enabled=True)
        self.robot.servoJ.assert_not_called()
        self.update(enabled=False)
        self.update(enabled=True)
        self.robot.servoJ.assert_called_once()
        np.testing.assert_allclose(self.robot.servoJ.call_args.args[1][0], self.q)

    def test_held_pedal_on_mode_entry_cannot_engage(self):
        self.update(enabled=True)
        self.robot.servoJ.assert_not_called()
        self.update(enabled=False)
        self.update(enabled=True)
        self.robot.servoJ.assert_called_once()

    def test_nonfinite_target_does_not_reach_robot(self):
        for joint in range(6):
            self.setUp()
            target = self.q.copy(); target[joint] = float('nan')
            self.update(target, enabled=True)
            self.robot.servoJ.assert_not_called()

    def test_nonfinite_robot_base_stops_existing_command(self):
        self.update()
        self.update(enabled=True)
        self.robot.getActualQ.return_value = [float('nan'), *self.q[1:]]
        self.update(enabled=True)
        self.robot.stop.assert_called_once_with(self.arm)
        self.assertEqual(self.robot.servoJ.call_count, 1)



    def test_reengagement_with_changed_target_is_blocked(self):
        self.update()
        self.update(enabled=True)
        self.update(enabled=False)
        target = self.q.copy(); target[0] += np.deg2rad(20)
        self.update(target, enabled=True)
        self.assertEqual(self.robot.servoJ.call_count, 1)
        self.robot.stop.assert_called_once_with(self.arm)

    def test_start_check_does_not_change_tracking_targets_after_engagement(self):
        self.update()
        self.update(enabled=True)
        target = self.q.copy(); target[0] += np.deg2rad(20)
        self.update(target, enabled=True)
        self.assertEqual(self.robot.servoJ.call_count, 2)
        np.testing.assert_allclose(self.robot.servoJ.call_args.args[1][0], target)

    def test_all_joints_must_meet_start_tolerance(self):
        for joint in range(6):
            for sign in (-1, 1):
                target = self.q.copy(); target[joint] += sign*np.deg2rad(14.9)
                self.assertTrue(joint_alignment(target, self.q)[1])
                target[joint] = self.q[joint]+sign*np.deg2rad(15.1)
                self.assertFalse(joint_alignment(target, self.q)[1])

    def test_start_with_all_joints_just_inside_fifteen_degrees(self):
        target = self.q + np.deg2rad([14.9, -14.9, 14.9, -14.9, 14.9, -14.9])
        self.update(target)
        self.update(target, enabled=True)
        self.robot.servoJ.assert_called_once()
        np.testing.assert_allclose(self.robot.servoJ.call_args.args[1][0], target)
        text = self.fields[self.arm]['Spark_alignment'].config.call_args.kwargs['text']
        self.assertIn('within 15 degrees', text)


class ThunderAlignmentTest(SparkAlignmentChecks, unittest.TestCase):
    arm = 'Thunder'


class LightningAlignmentTest(SparkAlignmentChecks, unittest.TestCase):
    arm = 'Lightning'


if __name__ == '__main__':
    unittest.main()
