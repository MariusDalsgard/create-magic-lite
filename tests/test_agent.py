"""Offline security/behavior checks. Never starts Minecraft or calls metadata hosts."""
from __future__ import annotations

import http.client
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "agent" / "panel_agent.py"
spec = importlib.util.spec_from_file_location("panel_agent", SOURCE)
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


class PanelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="friends-panel-test-")
        self.root = Path(self.temp.name)
        agent.initialize(self.root / "private", self.root / "minecraft", ["https://friends.example", "http://127.0.0.1:8765"])
        self.panel = agent.Panel(self.root / "private")
        self.code = (self.root / "private" / "friend-access-code.txt").read_text().strip()
        self.session = {"name": "Test Friend", "expires_at": time.time() + 600}

    def tearDown(self):
        self.temp.cleanup()

    def test_initialization_does_not_overwrite_code(self):
        with self.assertRaises(FileExistsError):
            agent.initialize(self.root / "private", self.root / "minecraft", ["https://friends.example"])
        self.assertEqual((self.root / "private" / "friend-access-code.txt").read_text().strip(), self.code)
        self.assertNotIn(self.code, (self.root / "private" / "config.json").read_text())

    def test_private_state_rejected_inside_repository(self):
        with self.assertRaises(ValueError):
            agent.initialize(SOURCE.parent / "private-not-created", self.root, ["https://friends.example"])

    def test_origins_require_https_and_no_path(self):
        for origin in ["https://friends.example/path", "http://friends.example", "https://user@friends.example", "https://friends.example/"]:
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                agent.checked_origin(origin)

    def test_login_returns_expiring_token_without_code(self):
        reply = self.panel.login({"name": "Test Friend", "code": self.code}, "127.0.0.1")
        self.assertNotIn(self.code, json.dumps(reply))
        self.assertGreater(len(reply["token"]), 40)
        self.assertEqual(self.panel.authenticate("Bearer " + reply["token"])["name"], "Test Friend")
        key = agent.hashlib.sha256(reply["token"].encode()).hexdigest()
        self.panel.sessions[key]["expires_at"] = time.time() - 1
        with self.assertRaises(agent.ApiError) as error:
            self.panel.authenticate("Bearer " + reply["token"])
        self.assertEqual(error.exception.status, 401)

    def test_wrong_code_rate_limited(self):
        for _ in range(8):
            with self.assertRaises(agent.ApiError) as error:
                self.panel.login({"name": "Friend", "code": "wrong"}, "198.51.100.3")
            self.assertEqual(error.exception.status, 401)
        with self.assertRaises(agent.ApiError) as error:
            self.panel.login({"name": "Friend", "code": self.code}, "198.51.100.3")
        self.assertEqual(error.exception.status, 429)

    def test_mod_urls_cannot_target_private_network_or_escape_hosts(self):
        urls = ["http://modrinth.com/mod/create", "https://127.0.0.1/mod/create", "https://modrinth.com.evil.test/mod/create",
                "https://modrinth.com@localhost/mod/create", "https://modrinth.com:8443/mod/create", "https://modrinth.com/mod/../x",
                "https://modrinth.com/mod/%2e%2e", "https://modrinth.com/mod/create/files", "https://www.curseforge.com/other/create",
                "file:///C:/private", "https://modrinth.com/mod/create\n", "https://modrinth.com/mod/create%00"]
        for url in urls:
            with self.subTest(url=url), self.assertRaises(agent.ApiError):
                agent.canonical_mod_url(url)
        self.assertEqual(agent.canonical_mod_url("https://www.modrinth.com/mod/create/?utm_source=test#body")[0], "https://modrinth.com/mod/create")
        self.assertEqual(agent.canonical_mod_url("https://modrinth.com/mod/uCdwusMi")[0], "https://modrinth.com/mod/uCdwusMi")

    def test_redirects_and_unsafe_images_are_rejected(self):
        self.assertIsNone(agent.NoRedirect().redirect_request(None, None, 302, "", {}, "http://127.0.0.1/private"))
        for image in ["javascript:alert(1)", "https://evil.test/a.png", "https://cdn.modrinth.com@localhost/a", "http://cdn.modrinth.com/a"]:
            self.assertIsNone(agent.safe_image(image))
        self.assertEqual(agent.safe_image("https://cdn.modrinth.com/data/test/icon.png"), "https://cdn.modrinth.com/data/test/icon.png")

    def test_unavailable_metadata_keeps_valid_suggestion_possible(self):
        with patch.object(agent, "fetch_bytes", side_effect=OSError("offline")):
            result = agent.mod_metadata("https://www.curseforge.com/minecraft/mc-mods/example-mod")
        self.assertEqual(result["title"], "Example Mod")
        self.assertFalse(result["preview_available"])

    def test_preview_fetches_only_fixed_api_host(self):
        data = {"project_type": "mod", "title": "Create", "description": "A mod", "icon_url": "https://cdn.modrinth.com/data/x/icon.png"}
        with patch.object(agent, "fetch_bytes", return_value=json.dumps(data).encode()) as fetch:
            result = agent.mod_metadata("https://modrinth.com/mod/create?ignored=yes")
        fetch.assert_called_once_with("https://api.modrinth.com/v2/project/create")
        self.assertEqual(result["title"], "Create")

    def test_no_duplicate_start_when_running(self):
        with patch.object(self.panel, "manager_state", return_value="starting"), patch.object(agent, "minecraft_ping", side_effect=OSError), patch.object(self.panel, "launch_fixed_start") as launch:
            result = self.panel.start(self.session)
        self.assertFalse(result["started"])
        launch.assert_not_called()

    def test_start_cooldown_persists_after_backend_restart(self):
        with patch.object(self.panel, "manager_state", return_value="offline"), patch.object(agent, "minecraft_ping", side_effect=OSError), patch.object(self.panel, "launch_fixed_start") as launch:
            self.assertTrue(self.panel.start(self.session)["started"])
            self.assertFalse(self.panel.start(self.session)["started"])
        launch.assert_called_once()
        restarted = agent.Panel(self.root / "private")
        with restarted.connect() as db:
            db.execute("UPDATE settings SET value=? WHERE key='last_start'", (str(time.time() - 20),))
        with patch.object(restarted, "manager_state", return_value="offline"), patch.object(agent, "minecraft_ping", side_effect=OSError), patch.object(restarted, "launch_fixed_start") as launch:
            with self.assertRaises(agent.ApiError) as error:
                restarted.start(self.session)
        self.assertEqual(error.exception.code, "start_cooldown")
        launch.assert_not_called()

    def test_simultaneous_starts_launch_once(self):
        outcomes = []
        with patch.object(self.panel, "manager_state", return_value="offline"), patch.object(agent, "minecraft_ping", side_effect=OSError), patch.object(self.panel, "launch_fixed_start") as launch:
            threads = [threading.Thread(target=lambda: outcomes.append(self.panel.start(self.session))) for _ in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        launch.assert_called_once()
        self.assertEqual(sum(result["started"] for result in outcomes), 1)

    def test_dedup_optional_reason_and_vote_toggle(self):
        with patch.object(agent, "mod_metadata", return_value={"url": "https://modrinth.com/mod/create", "title": "Create", "description": "A mod", "image_url": None, "source": "Modrinth", "preview_available": False}):
            first = self.panel.add_suggestion({"url": "https://modrinth.com/mod/create"}, self.session)
            second = self.panel.add_suggestion({"url": "https://modrinth.com/mod/create?utm_test=1", "reason": "Good"}, self.session)
        self.assertEqual(first["suggestion"]["reason"], "")
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        suggestion_id = first["suggestion"]["id"]
        self.assertEqual(second["suggestion"]["id"], suggestion_id)
        self.assertEqual(self.panel.vote(suggestion_id, self.session)["suggestion"]["votes"], 1)
        self.assertEqual(self.panel.vote(suggestion_id, self.session)["suggestion"]["votes"], 0)
        with self.assertRaises(agent.ApiError) as error:
            self.panel.vote(123456, self.session)
        self.assertEqual(error.exception.status, 404)


class HttpSecurityTests(unittest.TestCase):
    def setUp(self):
        PanelTests.setUp(self)
        self.server = agent.PanelServer(("127.0.0.1", 0), self.panel)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        PanelTests.tearDown(self)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        headers = dict(headers or {})
        if body is not None:
            body = json.dumps(body)
            headers.setdefault("Content-Type", "application/json")
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        status, response_headers, data = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return status, response_headers, json.loads(data) if data else None

    def test_http_unauthorized_start_and_missing_origin_are_denied(self):
        with patch.object(self.panel, "launch_fixed_start") as launch:
            self.assertEqual(self.request("POST", "/api/start", {}, {"Origin": "https://friends.example"})[0], 401)
            self.assertEqual(self.request("POST", "/api/login", {"name": "Friend", "code": self.code})[0], 403)
            self.assertEqual(self.request("POST", "/api/login", {"name": "Friend", "code": self.code}, {"Origin": "https://evil.test"})[0], 403)
        launch.assert_not_called()

    def test_http_control_surface_and_command_injection_rejected(self):
        token = self.panel.login({"name": "Friend", "code": self.code}, "127.0.0.1")["token"]
        headers = {"Origin": "https://friends.example", "Authorization": "Bearer " + token}
        with patch.object(self.panel, "launch_fixed_start") as launch:
            for route in ["/api/stop", "/api/restart", "/api/console", "/api/command"]:
                self.assertEqual(self.request("POST", route, {}, headers)[0], 404)
            self.assertEqual(self.request("POST", "/api/start", {"command": "stop"}, headers)[0], 400)
            self.assertEqual(self.request("GET", "/api/start", headers=headers)[0], 404)
        launch.assert_not_called()

    def test_cors_and_health_disclose_no_secrets(self):
        status, headers, value = self.request("GET", "/health")
        self.assertEqual((status, value), (200, {"ok": True}))
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        status, headers, _ = self.request("OPTIONS", "/api/status", headers={"Origin": "https://friends.example", "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"})
        self.assertEqual(status, 204)
        self.assertEqual(headers["Access-Control-Allow-Origin"], "https://friends.example")
        self.assertEqual(self.request("OPTIONS", "/api/status", headers={"Origin": "https://evil.test", "Access-Control-Request-Method": "GET"})[0], 403)

    def test_wrong_content_type_and_large_body_rejected(self):
        headers = {"Origin": "https://friends.example", "Content-Type": "text/plain"}
        self.assertEqual(self.request("POST", "/api/login", {}, headers)[0], 415)
        self.assertEqual(self.request("POST", "/api/login", {"blob": "a" * 9000}, {"Origin": "https://friends.example"})[0], 413)


if __name__ == "__main__":
    unittest.main(verbosity=2)
