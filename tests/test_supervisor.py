"""Isolated supervisor tests: no subprocesses, tunnel, GitHub or server actions."""
import base64
import ctypes
import importlib.util
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

SOURCE = Path(__file__).resolve().parents[1] / "supervisor.py"
SPEC = importlib.util.spec_from_file_location("panel_supervisor_tests", SOURCE)
supervisor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(supervisor)


def record(public, sha="first-sha"):
    return {"content": base64.b64encode(json.dumps(public).encode()).decode(), "sha": sha}


class FakeProcess:
    def __init__(self, label="child", events=None):
        self.pid = 23456
        self.returncode = None
        self.label = label
        self.events = events if events is not None else []
        self.terminated = threading.Event()

    def poll(self):
        return self.returncode

    def terminate(self):
        self.events.append(self.label + ":terminate")
        self.returncode = 0
        self.terminated.set()

    def kill(self):
        self.events.append(self.label + ":kill")
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / "docs").mkdir()
        self.root_patch = patch.object(supervisor, "ROOT", self.root)
        self.root_patch.start()
        self.settings = {"github_repo": "MariusDalsgard/create-magic-lite", "gh_path": "gh.exe"}
        self.url = "https://green-small-fox.trycloudflare.com"

    def tearDown(self):
        self.root_patch.stop()
        self.folder.cleanup()

    def test_preserves_public_fields_and_updates_only_runtime(self):
        original = {"apiBase": None, "serverAddress": "example:25566", "packShareUrl": None,
                    "custom": {"caption": "Vores verden"}}
        calls = []

        def api(settings, method, path, data=None):
            calls.append((method, path, data))
            return record(original) if method == "GET" else {}

        with patch.object(supervisor, "github", side_effect=api):
            supervisor.publish_endpoint(self.settings, self.url)
        sent = json.loads(base64.b64decode(calls[1][2]["content"]))
        self.assertEqual(sent["custom"], original["custom"])
        self.assertEqual(sent["serverAddress"], original["serverAddress"])
        self.assertIsNone(sent["packShareUrl"])
        self.assertEqual(sent["apiBase"], self.url)
        self.assertEqual(calls[0][1], "repos/MariusDalsgard/create-magic-lite/contents/docs/runtime.json?ref=main")
        self.assertEqual(calls[1][1], "repos/MariusDalsgard/create-magic-lite/contents/docs/runtime.json")
        self.assertEqual(calls[1][2]["sha"], "first-sha")
        self.assertEqual(calls[1][2]["branch"], "main")
        self.assertEqual(json.loads((self.root / "docs/runtime.json").read_text()), sent)

    def test_sha_conflict_refetches_preserves_concurrent_edits(self):
        api = Mock(side_effect=[record({"apiBase": None}), supervisor.GitHubError(409),
                               record({"apiBase": None, "packShareUrl": "https://example.com/new"}, "new-sha"), {}])
        with patch.object(supervisor, "github", api), patch.object(supervisor.time, "sleep"):
            supervisor.publish_endpoint(self.settings, self.url)
        second_put = api.call_args_list[3].args[3]
        self.assertEqual(second_put["sha"], "new-sha")
        self.assertEqual(json.loads(base64.b64decode(second_put["content"]))["packShareUrl"], "https://example.com/new")

    def test_unchanged_endpoint_does_not_commit(self):
        public = {"apiBase": self.url, "githubRepoUrl": "https://github.com/" + self.settings["github_repo"],
                  "connectionType": "test-tunnel", "connectionUpdatedAt": "original-date"}
        with patch.object(supervisor, "github", return_value=record(public)) as api:
            supervisor.publish_endpoint(self.settings, self.url)
        self.assertEqual(api.call_count, 1)
        self.assertEqual(json.loads((self.root / "docs/runtime.json").read_text()), public)

    def test_auth_failure_is_not_retried_or_written_locally(self):
        api = Mock(side_effect=[record({}), supervisor.GitHubError(401)])
        with patch.object(supervisor, "github", api), self.assertRaises(supervisor.GitHubError):
            supervisor.publish_endpoint(self.settings, self.url)
        self.assertEqual(api.call_count, 2)
        self.assertFalse((self.root / "docs/runtime.json").exists())

    def test_three_conflicts_fail_without_false_local_success(self):
        api = Mock(side_effect=[record({}), supervisor.GitHubError(409)] * 3)
        with patch.object(supervisor, "github", api), patch.object(supervisor.time, "sleep"), self.assertRaises(supervisor.GitHubError):
            supervisor.publish_endpoint(self.settings, self.url)
        self.assertEqual(api.call_count, 6)
        self.assertFalse((self.root / "docs/runtime.json").exists())

    def test_rejects_malicious_hostnames_before_github(self):
        bad = ["http://green.trycloudflare.com", "https://green.trycloudflare.com.evil.test",
               "https://green.trycloudflare.com:443", "https://green.trycloudflare.com/api",
               "https://green.trycloudflare.com?token=foo", "https://x@green.trycloudflare.com",
               "https://green.trycloudflare.com\n", "https://127.0.0.1", None]
        with patch.object(supervisor, "github") as api:
            for url in bad:
                with self.subTest(url=url), self.assertRaises(ValueError):
                    supervisor.publish_endpoint(self.settings, url)
        api.assert_not_called()

    def test_log_extraction_rejects_suffix_and_path(self):
        self.assertEqual(supervisor.extract_tunnel_url("INF | " + self.url + " |"), self.url)
        for text in [self.url + ".evil.test", self.url + "/api", self.url + "?query=1", "https://evil.test"]:
            with self.subTest(text=text):
                self.assertIsNone(supervisor.extract_tunnel_url(text))

    def test_github_errors_do_not_expose_output_or_debug_credentials(self):
        result = Mock(returncode=1, stderr="Authorization secret-value HTTP 403", stdout="")
        with patch.dict(os.environ, {"GH_DEBUG": "api", "GH_TRACE": "1"}), patch.object(supervisor.subprocess, "run", return_value=result) as run:
            with self.assertRaises(supervisor.GitHubError) as error:
                supervisor.github(self.settings, "GET", "repos/example/repo")
        self.assertEqual(error.exception.status, 403)
        self.assertNotIn("secret-value", str(error.exception))
        self.assertNotIn("GH_DEBUG", run.call_args.kwargs["env"])
        self.assertNotIn("GH_TRACE", run.call_args.kwargs["env"])
        self.assertIn("github.com", run.call_args.args[0])
        self.assertFalse(run.call_args.kwargs["shell"])


class LifecycleTests(unittest.TestCase):
    def test_backend_death_closes_tunnel_while_main_thread_is_busy(self):
        backend, tunnel = FakeProcess("api"), FakeProcess("tunnel")
        guard = supervisor.BackendGuard(backend)
        try:
            with patch.object(supervisor, "owns_listener", return_value=True):
                guard.attach_tunnel(lambda: tunnel, 8766)
            backend.returncode = 1
            self.assertTrue(tunnel.terminated.wait(2), "watchdog did not close owned tunnel")
            self.assertIsNone(guard.current_tunnel())
        finally:
            guard.close()

    def test_teardown_closes_tunnel_before_api_and_ignores_unowned_process(self):
        events = []
        backend, tunnel, unrelated = FakeProcess("api", events), FakeProcess("tunnel", events), FakeProcess("unrelated", events)
        guard = supervisor.BackendGuard(backend)
        with patch.object(supervisor, "owns_listener", return_value=True):
            guard.attach_tunnel(lambda: tunnel, 8766)
        guard.close()
        self.assertEqual(events, ["tunnel:terminate", "api:terminate"])
        self.assertIsNone(unrelated.poll())

    def test_unknown_listener_cannot_start_a_tunnel(self):
        backend, factory = FakeProcess("api"), Mock()
        guard = supervisor.BackendGuard(backend)
        try:
            with patch.object(supervisor, "owns_listener", return_value=False), self.assertRaises(RuntimeError):
                guard.attach_tunnel(factory, 8766)
            factory.assert_not_called()
        finally:
            guard.close()

    def test_api_exit_during_tunnel_creation_closes_new_tunnel(self):
        backend, tunnel = FakeProcess("api"), FakeProcess("tunnel")
        guard = supervisor.BackendGuard(backend)

        def factory():
            backend.returncode = 1
            return tunnel

        try:
            with patch.object(supervisor, "owns_listener", return_value=True), self.assertRaises(RuntimeError):
                guard.attach_tunnel(factory, 8766)
            self.assertTrue(tunnel.terminated.is_set())
            self.assertIsNone(guard.current_tunnel())
        finally:
            guard.close()

    @unittest.skipUnless(os.name == "nt", "Windows listener ownership")
    def test_listener_table_rejects_foreign_and_wildcard_listener(self):
        backend = FakeProcess()
        port = 8766
        loopback = int.from_bytes(socket.inet_aton("127.0.0.1"), "little")

        def check(rows):
            payload = struct.pack("<I", len(rows)) + b"".join(struct.pack("<IIIIII", *row) for row in rows)

            def get_table(buffer, size, ordered, family, table_class, reserved):
                self.assertEqual(table_class, 3)
                size._obj.value = len(payload)
                if buffer is None:
                    return 122
                ctypes.memmove(buffer, payload, len(payload))
                return 0

            library = Mock()
            library.GetExtendedTcpTable = get_table
            with patch.object(supervisor.ctypes, "WinDLL", return_value=library):
                return supervisor.owns_listener(backend, port)

        own = (2, loopback, socket.htons(port), 0, 0, backend.pid)
        foreign = (2, loopback, socket.htons(port), 0, 0, backend.pid + 1)
        wildcard = (2, 0, socket.htons(port), 0, 0, backend.pid + 1)
        self.assertTrue(check([own]))
        self.assertFalse(check([foreign]))
        self.assertFalse(check([own, foreign]))
        self.assertFalse(check([own, wildcard]))
        self.assertFalse(check([]))


if __name__ == "__main__":
    unittest.main()
