"""Conversion and both viewer services must share the selected dataset path."""

import json
import shlex
import threading
import unittest
import urllib.parse
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from data_pipeline import operator_console_backend as console
from data_pipeline.local_dataset_server import ReusableThreadingHTTPServer, _build_handler


class PublishedLocationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        self.external = Path(self.temp.name) / "SSD data" / "demo"
        self.root_patch = patch.object(console, "REPO_ROOT", self.repo)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.backend = console.OperatorConsoleBackend.__new__(console.OperatorConsoleBackend)
        self.backend.local_settings = {}
        self.backend.latest_dataset_id = None
        self.backend.latest_dataset_path = None
        self.backend._save_local_settings = Mock()
        self.backend._viewer_base_url = Mock(return_value="http://127.0.0.1:8000")
        self.backend._dataset_base_url = Mock(return_value="http://127.0.0.1:8001")

    def dataset(self, path, episodes=3):
        (path / "meta").mkdir(parents=True)
        (path / "meta" / "info.json").write_text(json.dumps({"total_episodes": episodes}))
        return path

    def test_legacy_names_and_nested_paths(self):
        normalize = self.backend._normalize_published_dataset_target
        self.assertEqual(normalize("demo"), self.repo / "published" / "demo")
        self.assertEqual(normalize("published/demo"), self.repo / "published" / "demo")
        self.assertEqual(normalize("published/group/demo"), self.repo / "published" / "group" / "demo")

    def test_external_path_is_saved_without_rebasing(self):
        stored = self.backend.set_published_dataset_target(str(self.external))
        self.assertEqual(stored, str(self.external))
        self.assertEqual(self.backend._published_dataset_target_path(), self.external)
        self.assertEqual(self.backend._published_root(), self.external.parent)
        self.backend._save_local_settings.assert_called_once()

    def test_repo_path_remains_relative_when_saved(self):
        self.assertEqual(self.backend.set_published_dataset_target("demo"), "published/demo")

    def test_symlink_to_external_drive_is_supported(self):
        self.external.parent.mkdir(parents=True)
        (self.repo / "published").mkdir()
        (self.repo / "published" / "ssd").symlink_to(self.external.parent, target_is_directory=True)
        self.assertEqual(self.backend.set_published_dataset_target("published/ssd/demo"), str(self.external))

    def test_invalid_targets_are_rejected(self):
        regular_file = self.repo / "file.txt"
        regular_file.write_text("not a dataset")
        for target in ("", "/", "published/", str(self.repo), str(regular_file)):
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.backend._normalize_published_dataset_target(target)

    def test_selected_external_dataset_wins_over_same_name_in_repo(self):
        self.dataset(self.repo / "published" / "demo", episodes=1)
        self.dataset(self.external, episodes=5)
        self.backend.set_published_dataset_target(str(self.external))
        self.backend.latest_dataset_id = "demo"
        path, episode, url = self.backend._resolve_viewer_target({})
        self.assertEqual(path, self.external)
        self.assertEqual(episode, 4)
        self.assertEqual(url, "http://127.0.0.1:8000/local/demo/episode_4")

    def test_latest_conversion_fallback_keeps_its_original_drive(self):
        self.dataset(self.external)
        self.backend.latest_dataset_id = self.external.name
        self.backend.latest_dataset_path = self.external
        self.backend.set_published_dataset_target("not_converted_yet")
        self.assertEqual(self.backend._resolve_viewer_target({})[0], self.external)

    def test_conversion_command_preserves_external_path_with_spaces(self):
        profile = self.repo / "profile.yaml"
        profile.write_text("{}")
        args = shlex.split(self.backend._build_convert_command(
            {"conversion_profile": str(profile)}, "episode_1", target_path=self.external))
        self.assertEqual(args[args.index("--published-root") + 1], str(self.external.parent))
        self.assertEqual(args[args.index("--published-dataset-id") + 1], "demo")

    def test_viewer_services_receive_the_resolved_dataset_parent(self):
        self.backend._ensure_managed_http_server = Mock()
        self.backend._url_reachable = Mock(return_value=True)
        self.backend._build_dataset_server_command = Mock(return_value="dataset-server")
        self.backend._build_viewer_server_command = Mock(return_value="viewer-server")
        self.backend._build_viewer_video_command = Mock(return_value="video-server")
        self.backend._ensure_viewer_server(self.external)
        calls = {call.kwargs["process_name"]: call.kwargs
                 for call in self.backend._ensure_managed_http_server.call_args_list}
        self.assertEqual(calls["dataset_server"]["published_root"], self.external.parent)
        self.assertEqual(calls["viewer_server"]["published_root"], self.external.parent)
        self.backend._build_dataset_server_command.assert_called_once_with(self.external.parent)
        self.backend._build_viewer_server_command.assert_called_once_with(self.external.parent)

    def test_server_commands_use_selected_external_root(self):
        self.backend.set_published_dataset_target(str(self.external))
        bun = Path(self.temp.name) / "bun"
        build = Path(self.temp.name) / "BUILD_ID"
        bun.touch()
        build.touch()
        with patch.object(console, "VIEWER_REPO", self.repo), \
             patch.object(console, "VIEWER_BUN", bun), patch.object(console, "VIEWER_BUILD_ID", build):
            viewer_args = shlex.split(self.backend._build_viewer_server_command())
        self.assertIn(f"LOCAL_DATASET_ROOT={self.external.parent}", viewer_args)
        args = shlex.split(self.backend._build_dataset_server_command())
        self.assertEqual(args[args.index("--root") + 1], str(self.external.parent))

    def test_existing_server_on_other_drive_is_restarted(self):
        self.backend.processes = {"dataset_server": console.ManagedProcess("dataset_server", "Dataset Server")}
        self.backend._url_reachable = Mock(return_value=True)
        self.backend._listener_pid = Mock(return_value=123)
        self.backend._listener_dataset_root = Mock(return_value=self.repo / "published")
        self.backend._stop_existing_listener = Mock()
        self.backend._start_process = Mock()
        self.backend._ensure_managed_http_server(
            process_name="dataset_server", command="new-root", url="http://127.0.0.1:8001/healthz",
            port=8001, cwd_hint=self.repo, timeout_s=1.0, published_root=self.external.parent)
        self.backend._stop_existing_listener.assert_called_once_with(8001, self.repo)
        self.backend._start_process.assert_called_once_with("dataset_server", "new-root")

    def test_existing_server_on_same_drive_is_reused(self):
        self.backend.processes = {"dataset_server": console.ManagedProcess("dataset_server", "Dataset Server")}
        self.backend._url_reachable = Mock(return_value=True)
        self.backend._listener_pid = Mock(return_value=123)
        self.backend._listener_dataset_root = Mock(return_value=self.external.parent)
        self.backend._start_process = Mock()
        self.backend._ensure_managed_http_server(
            process_name="dataset_server", command="same-root", url="http://127.0.0.1:8001/healthz",
            port=8001, cwd_hint=self.repo, timeout_s=1.0, published_root=self.external.parent)
        self.backend._start_process.assert_not_called()

    def test_completed_conversion_keeps_its_destination_after_selection_changes(self):
        self.backend.latest_episode_id = "episode_1"
        self.backend.pending_conversion_dataset_id = "demo"
        self.backend.pending_conversion_dataset_path = self.external
        self.backend._record_event = Mock()
        self.backend.processes = {"converter": console.ManagedProcess("converter", "Converter")}
        self.backend.set_published_dataset_target("different_dataset")
        completed = Mock(stdout=[], wait=Mock(return_value=0))
        self.backend._drain_logs("converter", completed)
        self.assertEqual(self.backend.latest_dataset_path, self.external)
        self.assertIsNone(self.backend.pending_conversion_dataset_path)

    def test_read_only_destination_blocks_conversion_with_clear_error(self):
        self.backend.latest_episode_id = "episode_1"
        self.backend.set_published_dataset_target(str(self.external))
        self.backend._start_process = Mock()
        with patch.object(console.os, "access", return_value=False):
            self.backend.start_conversion({})
        self.assertIn("not writable", self.backend.last_action_error)
        self.assertIn(str(self.external), self.backend.last_action_error)
        self.backend._start_process.assert_not_called()

    def test_http_server_reads_external_dataset_with_spaces(self):
        path = self.dataset(self.external.parent / "demo with spaces", episodes=7)
        server = ReusableThreadingHTTPServer(("127.0.0.1", 0), _build_handler(path.parent))
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/datasets/local/{urllib.parse.quote(path.name)}/resolve/main/meta/info.json"
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(url, timeout=2) as response:
                self.assertEqual(json.load(response)["total_episodes"], 7)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
