"""Own the panel API and its temporary tunnel; never control Minecraft directly.

Private settings/logs stay outside the repository. GitHub CLI supplies its own
stored credentials; only the public docs/runtime.json is published.
"""
from __future__ import annotations
import argparse
import base64
import ctypes
import json
import logging
import os
from pathlib import Path
import re
import socket
import subprocess
import threading
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
TUNNEL = re.compile(r"https://[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com\Z")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class GitHubError(RuntimeError):
    def __init__(self, status=None, returncode=None, category=None):
        self.status = status if isinstance(status, int) else None
        self.returncode = returncode if isinstance(returncode, int) else None
        self.category = category or (
            "authentication" if self.status == 401 or self.returncode == 4 else
            "permission_or_rate_limit" if self.status == 403 else
            "not_found" if self.status == 404 else
            "conflict" if self.status == 409 else
            "rate_limit" if self.status == 429 else
            "github_unavailable" if self.status is not None and self.status >= 500 else
            "http_error" if self.status is not None else "cli_error")
        # Never include gh stderr: debug output can contain authentication data.
        super().__init__("GitHub request failed: " + self.category +
                         (f" (HTTP {self.status})" if self.status else ""))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


def healthy(url):
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        request = urllib.request.Request(url + "/health", headers={"User-Agent": "CreateMagicLite-Panel/1"})
        with opener.open(request, timeout=8) as response:
            payload = response.read(4097)
            return response.status == 200 and len(payload) <= 4096 and json.loads(payload) == {"ok": True}
    except Exception:
        return False


def github_environment(settings):
    """Use one durable local profile, independent of the launching application's env."""
    configured = settings.get("gh_config_dir")
    if not isinstance(configured, str) or not configured.strip():
        raise GitHubError(category="config_missing")
    try:
        directory = Path(configured)
        if not directory.is_absolute():
            raise GitHubError(category="config_invalid")
        if not directory.is_dir():
            raise GitHubError(category="config_missing")
        directory = directory.resolve(strict=True)
    except (OSError, ValueError):
        raise GitHubError(category="config_invalid") from None
    environment = os.environ.copy()
    for name in ("GH_DEBUG", "GH_TRACE", "DEBUG", "GH_TOKEN", "GITHUB_TOKEN",
                 "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN", "GH_HOST"):
        environment.pop(name, None)
    environment["GH_CONFIG_DIR"] = str(directory)
    environment["GH_PROMPT_DISABLED"] = "1"
    environment["GH_NO_UPDATE_NOTIFIER"] = "1"
    return environment


def github(settings, method, endpoint, data=None):
    environment = github_environment(settings)
    command = [settings["gh_path"], "api", "--hostname", "github.com", "--method", method, endpoint]
    if data is not None:
        command += ["--input", "-"]
    try:
        result = subprocess.run(command, input=None if data is None else json.dumps(data),
                                text=True, encoding="utf-8", capture_output=True, timeout=40,
                                creationflags=NO_WINDOW, env=environment, shell=False)
    except subprocess.TimeoutExpired:
        raise GitHubError(category="timeout") from None
    except OSError:
        raise GitHubError(category="cli_launch_failed") from None
    if result.returncode:
        status = re.search(r"\bHTTP\s+(\d{3})\b", result.stderr)
        raise GitHubError(int(status.group(1)) if status else None, result.returncode)
    try:
        return json.loads(result.stdout) if result.stdout.strip() else None
    except ValueError:
        raise GitHubError(category="invalid_response") from None


def write_local_runtime(public):
    path = ROOT / "docs" / "runtime.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(public, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def publish_endpoint(settings, endpoint):
    if not isinstance(endpoint, str) or not TUNNEL.fullmatch(endpoint):
        raise ValueError("Unexpected tunnel hostname")
    repo = settings["github_repo"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("Invalid repository name")
    path = f"repos/{repo}/contents/docs/runtime.json"
    for attempt in range(3):
        # Read the same branch that is written, including after a concurrent edit.
        record = github(settings, "GET", path + "?ref=main")
        public = json.loads(base64.b64decode(record["content"]))
        if not isinstance(public, dict):
            raise ValueError("Public runtime must be a JSON object")
        desired = dict(public)
        desired.update(apiBase=endpoint, githubRepoUrl="https://github.com/" + repo,
                       connectionType="test-tunnel")
        if desired == public:
            write_local_runtime(public)
            return
        desired["connectionUpdatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        content = json.dumps(desired, ensure_ascii=False, indent=2) + "\n"
        try:
            github(settings, "PUT", path, {"message": "Update active panel test connection",
                   "sha": record["sha"], "content": base64.b64encode(content.encode()).decode(), "branch": "main"})
        except GitHubError as error:
            if error.status != 409 or attempt == 2:
                raise
            time.sleep(2)
            continue
        write_local_runtime(desired)
        return


def extract_tunnel_url(line):
    for candidate in re.findall(r"https://[^\s\"'<>]+", line):
        candidate = candidate.rstrip(".,);]}")
        if TUNNEL.fullmatch(candidate):
            return candidate
    return None


def read_tunnel(process, log_path, discovered):
    try:
        with log_path.open("a", encoding="utf-8") as output:
            for line in process.stdout:
                output.write(line)
                output.flush()
                endpoint = extract_tunnel_url(line)
                if endpoint and "url" not in discovered:
                    discovered["url"] = endpoint
    finally:
        process.stdout.close()


def stop_owned(process):
    """Popen's owned process handle, never a PID lookup or process-name kill."""
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        # Only this supervisor's API/tunnel child is eligible, never Minecraft.
        process.kill()
        process.wait(timeout=10)


def owns_listener(process, port):
    """Fail closed unless Windows reports this child's IPv4 loopback listener."""
    if os.name != "nt" or process.poll() is not None:
        return False
    from ctypes import wintypes

    class Row(ctypes.Structure):
        _fields_ = [(field, wintypes.DWORD) for field in
                    ("state", "local_addr", "local_port", "remote_addr", "remote_port", "pid")]

    table = ctypes.WinDLL("iphlpapi", use_last_error=True).GetExtendedTcpTable
    table.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), wintypes.BOOL,
                      wintypes.ULONG, ctypes.c_int, wintypes.ULONG]
    table.restype = wintypes.DWORD
    size = wintypes.DWORD()
    if table(None, ctypes.byref(size), False, socket.AF_INET, 3, 0) != 122:
        return False
    for _ in range(3):
        buffer = ctypes.create_string_buffer(size.value)
        result = table(buffer, ctypes.byref(size), False, socket.AF_INET, 3, 0)
        if result == 122:
            continue
        if result:
            return False
        count = wintypes.DWORD.from_buffer_copy(buffer.raw[:4]).value
        if 4 + count * ctypes.sizeof(Row) > len(buffer):
            return False
        loopback = int.from_bytes(socket.inet_aton("127.0.0.1"), "little")
        owned = False
        for index in range(count):
            row = Row.from_buffer_copy(buffer.raw, 4 + index * ctypes.sizeof(Row))
            if row.state != 2 or socket.ntohs(row.local_port & 0xFFFF) != port or row.local_addr not in (0, loopback):
                continue
            if row.pid != process.pid or row.local_addr != loopback:
                return False
            owned = True
        return owned and process.poll() is None
    return False


class BackendGuard:
    """Close the tunnel promptly on API death, even while GitHub requests block."""
    def __init__(self, backend):
        self.backend = backend
        self.tunnel = None
        self.lock = threading.RLock()
        self.closed = threading.Event()
        self.watcher = threading.Thread(target=self._watch, daemon=True)
        self.watcher.start()

    def _watch(self):
        while not self.closed.wait(0.25):
            if self.backend.poll() is not None:
                self.close_tunnel()
                return

    def attach_tunnel(self, factory, port):
        with self.lock:
            if self.closed.is_set() or not owns_listener(self.backend, port):
                raise RuntimeError("API no longer owns its loopback listener; tunnel refused")
            self.close_tunnel()
            self.tunnel = factory()
            if self.backend.poll() is not None:
                self.close_tunnel()
                raise RuntimeError("API exited while its tunnel was starting")
            return self.tunnel

    def close_tunnel(self):
        with self.lock:
            stop_owned(self.tunnel)
            self.tunnel = None

    def current_tunnel(self):
        with self.lock:
            return self.tunnel

    def close(self):
        self.closed.set()
        try:
            self.close_tunnel()
        finally:
            stop_owned(self.backend)
        if threading.current_thread() is not self.watcher:
            self.watcher.join(timeout=12)


def write_status(private, state):
    path = private / "supervisor-status.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def publish_with_status(private, state, settings, endpoint):
    state["last_publish_attempt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    state["published"] = False
    state.pop("last_publish_error", None)
    write_status(private, state)
    try:
        publish_endpoint(settings, endpoint)
    except Exception as error:
        diagnostic = {"category": "unexpected_error", "http_status": None, "returncode": None}
        if isinstance(error, GitHubError):
            diagnostic.update(category=error.category, http_status=error.status, returncode=error.returncode)
        state["last_publish_error"] = diagnostic
        write_status(private, state)
        logging.warning("Publication pending: category=%s HTTP=%s exit=%s",
                        diagnostic["category"], diagnostic["http_status"], diagnostic["returncode"])
        return False
    state["published"] = True
    state["last_publish_success"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    write_status(private, state)
    logging.info("Healthy test connection published: %s", endpoint)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-dir", type=Path, required=True)
    private = parser.parse_args().private_dir.resolve()
    if private == ROOT or ROOT in private.parents:
        raise ValueError("Private directory must be outside this repository")
    settings = json.loads((private / "supervisor.json").read_text(encoding="utf-8-sig"))
    config = json.loads((private / "config.json").read_text(encoding="utf-8-sig"))
    port = int(config.get("port", 8766))
    if not 1024 <= port <= 65535:
        raise ValueError("Invalid loopback port")
    local_url = f"http://127.0.0.1:{port}"
    logging.basicConfig(filename=str(private / "supervisor.log"), level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    lock = (private / "supervisor.lock").open("a+b")
    lock.seek(0)
    if os.name == "nt":
        import msvcrt
        if lock.read(1) == b"":
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            lock.close()
            return
    else:
        lock.close()
        raise RuntimeError("This supervisor requires Windows listener ownership checks")
    guard = None
    api_log = (private / "api.log").open("a", encoding="utf-8")
    backoff = 3
    published = False
    state = {"pid": os.getpid(), "published": False, "state": "starting"}
    try:
        while True:
            if guard is None or guard.backend.poll() is not None:
                if guard is not None:
                    # Tunnel is closed before any replacement backend is launched.
                    guard.close()
                    guard = None
                    published = False
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 60)
                with socket.socket() as check:
                    try:
                        check.bind(("127.0.0.1", port))
                    except OSError:
                        raise RuntimeError("Panel port is already in use; refusing to expose an unknown service")
                backend = subprocess.Popen([settings["python_path"], str(ROOT / "agent" / "panel_agent.py"),
                           "--private-dir", str(private)], cwd=ROOT, stdout=api_log, stderr=api_log,
                           stdin=subprocess.DEVNULL, creationflags=NO_WINDOW, shell=False)
                guard = BackendGuard(backend)
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline and backend.poll() is None:
                    if healthy(local_url) and owns_listener(backend, port):
                        break
                    time.sleep(1)
                else:
                    logging.warning("Panel API did not become healthy; restarting its owned child")
                    guard.close()
                    continue
            current_tunnel = guard.current_tunnel()
            if current_tunnel is None or current_tunnel.poll() is not None:
                guard.close_tunnel()
                published = False
                found = {}
                tunnel = guard.attach_tunnel(lambda: subprocess.Popen(
                    [settings["cloudflared_path"], "tunnel", "--no-autoupdate", "--url", local_url],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                    text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW,
                    shell=False), port)
                threading.Thread(target=read_tunnel, args=(tunnel, private / "tunnel.log", found), daemon=True).start()
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline and tunnel.poll() is None and guard.backend.poll() is None:
                    if found.get("url") and healthy(found["url"]) and guard.backend.poll() is None:
                        break
                    time.sleep(2)
                else:
                    guard.close_tunnel()
                    logging.warning("Tunnel not healthy; retrying")
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 60)
                    continue
                endpoint = found["url"]
                state = {"pid": os.getpid(), "api_pid": guard.backend.pid, "tunnel_pid": tunnel.pid,
                         "api_base": endpoint, "published": False, "state": "connected"}
                write_status(private, state)
                backoff = 3
            current_tunnel = guard.current_tunnel()
            if not published and guard.backend.poll() is None and current_tunnel is not None and current_tunnel.poll() is None:
                published = publish_with_status(private, state, settings, endpoint)
                if not published:
                    time.sleep(25)
            time.sleep(5)
    except KeyboardInterrupt:
        pass
    except Exception:
        logging.exception("Panel supervisor stopped")
        raise
    finally:
        if guard is not None:
            guard.close()
        state.update(published=False, state="stopped")
        write_status(private, state)
        api_log.close()
        lock.close()


if __name__ == "__main__":
    main()
