"""Discovery must keep legacy cameras when the SDK sees only newer models."""

import unittest
from unittest.mock import patch

from data_pipeline import device_discovery as discovery


class DeviceDiscoveryTests(unittest.TestCase):
    def discover(self, sdk, v4l, config=None):
        with patch.object(discovery, "_discover_realsense_sdk", return_value=sdk), \
             patch.object(discovery, "_discover_realsense_v4l", return_value=v4l), \
             patch.object(discovery, "_discover_gelsight_v4l", return_value=[]):
            return discovery.discover_session_devices(config or {})

    def test_l515_is_not_hidden_when_sdk_finds_d405(self):
        devices = self.discover(
            [{"serial_number": "405"}],
            [{"serial_number": "405"}, {"serial_number": "515"}],
        )
        self.assertEqual([d["serial_number"] for d in devices], ["405", "515"])

    def test_normalized_duplicates_preserve_sdk_serial_and_selection(self):
        devices = self.discover(
            [{"serial_number": "000515"}],
            [{"serial_number": "515"}, {"serial_number": "00515"}],
            {"session_devices": [{"kind": "realsense", "serial_number": "515",
                                  "sensor_key": "scene_camera_1", "enabled": True}]},
        )
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["serial_number"], "000515")
        self.assertEqual(devices[0]["sensor_key"], "scene_camera_1")
        self.assertTrue(devices[0]["enabled"])

    def test_v4l_discovery_survives_sdk_error(self):
        with patch.object(discovery, "_discover_realsense_sdk", side_effect=RuntimeError("USB unavailable")), \
             patch.object(discovery, "_discover_realsense_v4l", return_value=[{"serial_number": "515"}]), \
             patch.object(discovery, "_discover_gelsight_v4l", return_value=[]), \
             self.assertLogs(discovery.__name__, level="WARNING"):
            devices = discovery.discover_session_devices({})
        self.assertEqual([d["serial_number"] for d in devices], ["515"])

    def test_sdk_only_camera_is_retained(self):
        devices = self.discover([{"serial_number": "515"}], [])
        self.assertEqual([d["serial_number"] for d in devices], ["515"])


if __name__ == "__main__":
    unittest.main()
