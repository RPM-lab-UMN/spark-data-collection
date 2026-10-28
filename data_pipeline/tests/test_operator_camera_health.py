"""Health must require configured streams and actual incoming messages."""

import unittest
from unittest.mock import Mock

from data_pipeline.operator_console_backend import ManagedProcess, OperatorConsoleBackend


class CameraHealthTests(unittest.TestCase):
    def setUp(self):
        # Avoid starting console sessions or touching real processes and ROS.
        self.backend = OperatorConsoleBackend.__new__(OperatorConsoleBackend)
        self.backend.processes = {"realsense_contract": ManagedProcess("realsense_contract", "RealSense")}
        self.backend._topic_has_message_cached = Mock(return_value=True)

    def config(self, sensor_key):
        return {"session_devices": [{"kind": "realsense", "serial_number": "130322273305",
                                     "enabled": True, "sensor_key": sensor_key}]}

    def test_unassigned_camera_does_not_report_healthy(self):
        card = self.backend._realsense_health(self.config(""), {})
        self.assertEqual(card["status"], "yellow")
        self.assertIn("Assign Sensor Keys", card["summary"])
        self.backend._topic_has_message_cached.assert_not_called()

    def test_no_selected_cameras_is_idle(self):
        card = self.backend._realsense_health({"session_devices": []}, {})
        self.assertEqual(card["status"], "off")

    def test_partial_assignment_does_not_report_all_cameras_healthy(self):
        config = self.config("/spark/cameras/world/scene_1")
        config["session_devices"].append({"kind": "realsense", "serial_number": "f1380660",
                                          "enabled": True, "sensor_key": ""})
        card = self.backend._realsense_health(config, {"/spark/cameras/world/scene_1/color/image_raw": "sensor_msgs/msg/Image"})
        self.assertEqual(card["status"], "yellow")
        self.assertIn("f1380660", card["details"][0])

    def test_empty_topic_list_is_not_healthy(self):
        card = self.backend._build_health_card(process_name="realsense_contract", live_topics={},
                                               required_topics=[], sample_topics=[])
        self.assertEqual(card["status"], "yellow")
        self.assertIn("not configured", card["summary"])

    def test_external_publisher_requires_messages_and_explains_ownership(self):
        topics = {"/spark/cameras/world/scene_1/color/image_raw": "sensor_msgs/msg/Image"}
        card = self.backend._realsense_health(self.config("/spark/cameras/world/scene_1"), topics)
        self.assertEqual(card["status"], "yellow")
        self.assertIn("publisher outside this console", card["summary"])
        self.assertIn("cannot stop", card["details"][0])
        self.backend._topic_has_message_cached.return_value = False
        self.assertEqual(self.backend._realsense_health(self.config("/spark/cameras/world/scene_1"), topics)["status"], "red")

    def test_managed_publisher_with_messages_is_healthy(self):
        self.backend.processes["realsense_contract"].state = "running"
        topics = {"/spark/cameras/world/scene_1/color/image_raw": "sensor_msgs/msg/Image"}
        self.assertEqual(self.backend._realsense_health(self.config("/spark/cameras/world/scene_1"), topics)["status"], "green")


if __name__ == "__main__":
    unittest.main()
