"""Discovery must keep legacy cameras when the SDK sees only newer models."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
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
                                  "sensor_key": "/spark/cameras/world/scene_1", "enabled": True}]},
        )
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["serial_number"], "000515")
        self.assertEqual(devices[0]["sensor_key"], "/spark/cameras/world/scene_1")
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

    def test_d405_usb_identity_is_not_an_extra_camera(self):
        devices = self.discover(
            [{"serial_number": "130322273305", "usb_serial_number": "128223071470"},
             {"serial_number": "f1380660", "usb_serial_number": "00000000F1380660"}],
            [{"serial_number": "128223071470"}, {"serial_number": "00000000F1380660"}],
        )
        self.assertEqual([d["serial_number"] for d in devices], ["130322273305", "f1380660"])

    def test_usb_alias_selection_moves_to_sdk_serial(self):
        devices = self.discover(
            [{"serial_number": "130322273305", "usb_serial_number": "128223071470"}],
            [{"serial_number": "128223071470"}],
            {"session_devices": [{"kind": "realsense", "serial_number": "128223071470",
                                  "sensor_key": "/spark/cameras/world/scene_1", "enabled": True}]},
        )
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["serial_number"], "130322273305")
        self.assertEqual(devices[0]["sensor_key"], "/spark/cameras/world/scene_1")
        self.assertTrue(devices[0]["enabled"])

    def test_rsusb_port_resolves_usb_descriptor_serial(self):
        with TemporaryDirectory() as tmp:
            usb_device = Path(tmp) / "2-1.3"
            usb_device.mkdir()
            (usb_device / "idVendor").write_text("8086\n")
            (usb_device / "serial").write_text("128223071470\n")
            with patch.object(discovery, "_USB_DEVICES_DIR", Path(tmp)):
                self.assertEqual(discovery._usb_serial_for_physical_port("2-1.3-5"), "128223071470")

    def test_kernel_uvc_port_resolves_usb_parent(self):
        with TemporaryDirectory() as tmp:
            usb_device = Path(tmp) / "usb2" / "2-1"
            interface = usb_device / "2-1:1.0" / "video4linux" / "video0"
            interface.mkdir(parents=True)
            (usb_device / "idVendor").write_text("8086\n")
            (usb_device / "serial").write_text("128223071470\n")
            self.assertEqual(discovery._usb_serial_for_physical_port(str(interface)), "128223071470")

    def test_sdk_discovery_adds_usb_serial_alias(self):
        device = SimpleNamespace(get_info=lambda key: {"serial": "130322273305", "port": "2-1-5"}[key])
        sdk = SimpleNamespace(camera_info=SimpleNamespace(serial_number="serial", physical_port="port"),
                              context=lambda: SimpleNamespace(query_devices=lambda: [device]))
        with patch.object(discovery, "rs", sdk), \
             patch.object(discovery, "_usb_serial_for_physical_port", return_value="128223071470"):
            self.assertEqual(discovery._discover_realsense_sdk(), [
                {"kind": "realsense", "serial_number": "130322273305", "usb_serial_number": "128223071470"}
            ])


if __name__ == "__main__":
    unittest.main()
