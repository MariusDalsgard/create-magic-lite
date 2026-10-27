"""Start-only Minecraft panel. Standard-library HTTP service, bound to loopback.

Private configuration and SQLite data MUST live outside the public repository.
The public API deliberately has no stop, restart, console or file operations.
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import ctypes
import hashlib
import hmac
import html.parser
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_SERVER = Path(r"C:\Users\Marius\MinecraftServers\Create-Magic-Lite")
SESSION_SECONDS = 86400
START_COOLDOWN = 120
USER_AGENT = "CreateMagicLite-FriendsPanel/1.0 (private Minecraft community)"


class ApiError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message
        super().__init__(message)


def utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def checked_origin(value):
    parsed = urllib.parse.urlsplit(value)
    if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise ValueError("Origins must contain only scheme, host and optional port")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}):
        raise ValueError("Production origins require HTTPS")
    if not parsed.hostname:
        raise ValueError("Origin host missing")
    return value


def initialize(private_dir, server_dir, origins):
    """Create private state once. Never return or print the access code."""
    private_dir, server_dir = private_dir.resolve(), server_dir.resolve()
    repository = Path(__file__).resolve().parents[1]
    if private_dir == repository or repository in private_dir.parents:
        raise ValueError("Private state must be outside the Git repository")
    private_dir.mkdir(parents=True, exist_ok=True)
    config_path = private_dir / "config.json"
    if config_path.exists():
        raise FileExistsError("Configuration already exists; it was not replaced")
    code, salt = secrets.token_urlsafe(24), secrets.token_hex(16)
    config = {
        "server_directory": str(server_dir),
        "public_address": "83.88.146.132:25566",
        "allowed_origins": [checked_origin(origin) for origin in origins],
        "access_salt": salt,
        "access_hash": hashlib.scrypt(code.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex(),
        "port": 8766,
    }
    # This file is intentionally local-only so the owner can share the code privately.
    (private_dir / "friend-access-code.txt").write_text(code + "\n", encoding="utf-8")
    write_json(config_path, config)
    return config_path


def canonical_mod_url(raw):
    if not isinstance(raw, str) or len(raw) > 500 or any(ord(c) < 33 for c in raw):
        raise ApiError(400, "invalid_url", "Indsæt et direkte HTTPS-link til et mod på Modrinth eller CurseForge.")
    try:
        parsed = urllib.parse.urlsplit(raw)
        port = parsed.port
    except ValueError:
        raise ApiError(400, "invalid_url", "Linket er ugyldigt.")
    if parsed.scheme != "https" or parsed.username or parsed.password or port not in (None, 443):
        raise ApiError(400, "invalid_url", "Brug et HTTPS-link uden login eller specialport.")
    if parsed.hostname in {"modrinth.com", "www.modrinth.com"}:
        match = re.fullmatch(r"/mod/([A-Za-z0-9_-]{1,100})/?", parsed.path)
        source, base = "Modrinth", "https://modrinth.com/mod/"
    elif parsed.hostname in {"curseforge.com", "www.curseforge.com"}:
        match = re.fullmatch(r"/minecraft/mc-mods/([A-Za-z0-9_-]{1,100})/?", parsed.path)
        source, base = "CurseForge", "https://www.curseforge.com/minecraft/mc-mods/"
    else:
        match = None
    if not match:
        raise ApiError(400, "invalid_url", "Linket skal være mod-detaljesiden på Modrinth eller CurseForge.")
    slug = match.group(1)
    # Modrinth's eight-character project IDs are case-sensitive; normal slugs are not.
    if source != "Modrinth" or not re.fullmatch(r"[A-Za-z0-9]{8}", slug):
        slug = slug.lower()
    return base + slug, source, slug


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        # Only fixed upstream hosts are fetched. No redirect can reach a private host.
        return None


def fetch_bytes(url, maximum=1_500_000):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json,text/html"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=7) as response:
        data = response.read(maximum + 1)
        if len(data) > maximum:
            raise ValueError("Upstream response too large")
        return data


def safe_image(raw):
    if not isinstance(raw, str) or len(raw) > 1800:
        return None
    try:
        parsed = urllib.parse.urlsplit(raw)
        good_port = parsed.port in (None, 443)
    except ValueError:
        return None
    hosts = {"cdn.modrinth.com", "media.forgecdn.net", "mediafilez.forgecdn.net", "mediafiles.forgecdn.net"}
    return raw if parsed.scheme == "https" and parsed.hostname in hosts and not parsed.username and not parsed.password and good_port else None


class OpenGraphParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.values = {}

    def handle_starttag(self, tag, attributes):
        values = dict(attributes)
        if tag == "meta":
            key = values.get("property", values.get("name"))
            if key in {"og:title", "og:description", "og:image"}:
                self.values[key] = values.get("content", "")


def mod_metadata(raw):
    url, source, slug = canonical_mod_url(raw)
    result = {"url": url, "source": source, "title": slug.replace("-", " ").replace("_", " ").title(),
              "description": "", "image_url": None, "preview_available": False}
    try:
        if source == "Modrinth":
            data = json.loads(fetch_bytes("https://api.modrinth.com/v2/project/" + slug))
            if not isinstance(data, dict):
                raise ValueError("Unexpected metadata response")
            if data.get("project_type") != "mod":
                raise ApiError(400, "not_a_mod", "Linket skal pege på et mod.")
            canonical_slug = data.get("slug")
            if isinstance(canonical_slug, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", canonical_slug):
                result["url"] = "https://modrinth.com/mod/" + canonical_slug
            result.update(title=str(data.get("title", result["title"]))[:200],
                          description=str(data.get("description", ""))[:700],
                          image_url=safe_image(data.get("icon_url")), preview_available=True)
        else:
            parser = OpenGraphParser()
            parser.feed(fetch_bytes(url).decode("utf-8", errors="replace"))
            title = parser.values.get("og:title")
            if title:
                result.update(title=title[:200], description=parser.values.get("og:description", "")[:700],
                              image_url=safe_image(parser.values.get("og:image")), preview_available=True)
    except ApiError:
        raise
    except (OSError, ValueError, urllib.error.URLError):
        # A blocked or temporarily unavailable provider must not discard a valid suggestion.
        pass
    return result


def varint(value):
    output = bytearray()
    while True:
        digit = value & 127
        value >>= 7
        output.append(digit | (128 if value else 0))
        if not value:
            return bytes(output)


def receive(stream, count):
    output = bytearray()
    while len(output) < count:
        part = stream.recv(count - len(output))
        if not part:
            raise ConnectionError("Incomplete Minecraft status")
        output.extend(part)
    return bytes(output)


def read_varint(stream):
    result = 0
    for offset in range(5):
        digit = receive(stream, 1)[0]
        result |= (digit & 127) << (7 * offset)
        if not digit & 128:
            return result
    raise ValueError("Invalid Minecraft status length")


def minecraft_ping():
    with socket.create_connection(("127.0.0.1", 25565), timeout=1.5) as stream:
        stream.settimeout(1.5)
        name = b"localhost"
        handshake = b"\x00" + varint(763) + varint(len(name)) + name + struct.pack(">H", 25565) + b"\x01"
        stream.sendall(varint(len(handshake)) + handshake + b"\x01\x00")
        packet_length = read_varint(stream)
        if packet_length < 2 or packet_length > 262144 or read_varint(stream) != 0:
            raise ValueError("Invalid Minecraft status")
        length = read_varint(stream)
        if length > 262144 or length > packet_length:
            raise ValueError("Invalid Minecraft JSON length")
        return json.loads(receive(stream, length))


def process_matches(pid, filetime, executable):
    if os.name != "nt" or not pid or not filetime or not executable:
        return False
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        created, exited, cpu_kernel, cpu_user = (wintypes.FILETIME() for _ in range(4))
        buffer, size = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:
            return False
        if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(cpu_kernel), ctypes.byref(cpu_user)):
            return False
        if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return False
        return str((created.dwHighDateTime << 32) | created.dwLowDateTime) == str(filetime) and os.path.normcase(buffer.value) == os.path.normcase(str(executable))
    finally:
        kernel.CloseHandle(handle)


class Panel:
    def __init__(self, private_dir):
        self.private_dir = Path(private_dir).resolve()
        repository = Path(__file__).resolve().parents[1]
        if self.private_dir == repository or repository in self.private_dir.parents:
            raise ValueError("Private state must live outside the public repository")
        self.config = json.loads((self.private_dir / "config.json").read_text(encoding="utf-8-sig"))
        self.origins = {checked_origin(value) for value in self.config["allowed_origins"]}
        if not self.origins:
            raise ValueError("At least one allowed origin is required")
        self.server_dir = Path(self.config["server_directory"]).resolve()
        self.database = self.private_dir / "panel.sqlite3"
        self.lock, self.start_lock, self.status_lock = threading.RLock(), threading.Lock(), threading.Lock()
        self.sessions, self.limits, self.preview_cache = {}, {}, {}
        self.status_cache = (0, None)
        with self.connect() as db:
            db.executescript("""
              CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS suggestions (
                id INTEGER PRIMARY KEY, url TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
                description TEXT NOT NULL, image_url TEXT, source TEXT NOT NULL,
                reason TEXT NOT NULL, author TEXT NOT NULL, created_at TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS votes (
                suggestion_id INTEGER NOT NULL REFERENCES suggestions(id),
                voter TEXT NOT NULL, PRIMARY KEY (suggestion_id, voter));
            """)

    @contextlib.contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def rate_limit(self, key, limit, window):
        now = time.monotonic()
        with self.lock:
            bucket = self.limits.setdefault(key, collections.deque())
            while bucket and bucket[0] <= now - window:
                bucket.popleft()
            if len(bucket) >= limit:
                raise ApiError(429, "rate_limit", "For mange forsøg. Vent lidt, og prøv igen.")
            bucket.append(now)
            if len(self.limits) > 5000:
                self.limits = {k: v for k, v in self.limits.items() if v and v[-1] > now - 3600}

    def login(self, body, ip):
        self.rate_limit("login:global", 30, 60)
        self.rate_limit("login:" + ip, 8, 300)
        name, code = body.get("name"), body.get("code")
        if not isinstance(name, str) or not re.fullmatch(r"[\w .-]{2,32}", name.strip(), re.UNICODE):
            raise ApiError(400, "invalid_name", "Skriv et navn på 2–32 bogstaver, tal, mellemrum, punktum eller bindestreg.")
        if not isinstance(code, str) or len(code) > 200:
            raise ApiError(401, "invalid_code", "Adgangskoden er forkert.")
        digest = hashlib.scrypt(code.encode(), salt=bytes.fromhex(self.config["access_salt"]), n=16384, r=8, p=1).hex()
        if not hmac.compare_digest(digest, self.config["access_hash"]):
            raise ApiError(401, "invalid_code", "Adgangskoden er forkert.")
        token, expires = secrets.token_urlsafe(32), int(time.time()) + SESSION_SECONDS
        with self.lock:
            self.sessions = {k: v for k, v in self.sessions.items() if v["expires_at"] > time.time()}
            self.sessions[hashlib.sha256(token.encode()).hexdigest()] = {"name": name.strip(), "expires_at": expires}
        return {"token": token, "name": name.strip(), "expires_at": expires}

    def authenticate(self, header):
        if not isinstance(header, str) or not header.startswith("Bearer ") or len(header) > 150:
            raise ApiError(401, "unauthorized", "Log ind med venners adgangskode.")
        key = hashlib.sha256(header[7:].encode()).hexdigest()
        with self.lock:
            session = self.sessions.get(key)
        if not session or session["expires_at"] <= time.time():
            raise ApiError(401, "unauthorized", "Log ind igen. Din adgang er udløbet.")
        return session

    def last_start(self):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key='last_start'").fetchone()
            return float(row[0]) if row else 0.0

    def manager_state(self):
        try:
            status = json.loads((self.server_dir / "server-status.json").read_text(encoding="utf-8-sig"))
            manager_alive = process_matches(status.get("manager_pid"), status.get("manager_start_filetime"), status.get("manager_executable"))
            java_alive = process_matches(status.get("server_pid"), status.get("server_start_filetime"), status.get("java_executable"))
            if manager_alive or java_alive:
                return "stopping" if status.get("state") == "stopping" else "starting"
        except (OSError, ValueError, TypeError):
            pass
        return "offline"

    def status(self, fresh=False):
        with self.status_lock:
            if not fresh and time.monotonic() - self.status_cache[0] < 2:
                return self.status_cache[1].copy()
            result = {"state": self.manager_state(), "players": {"online": 0, "max": 10},
                      "version": "Minecraft 1.20.1 · Forge 47.4.28", "address": self.config["public_address"],
                      "can_start": False, "checked_at": utc_now()}
            try:
                ping = minecraft_ping()
                if result["state"] != "stopping":
                    result["state"] = "online"
                players = ping.get("players", {})
                result["players"] = {"online": max(0, int(players.get("online", 0))), "max": max(1, int(players.get("max", 10)))}
            except (OSError, ValueError, TypeError):
                pass
            since_start = time.time() - self.last_start()
            if result["state"] == "offline" and since_start < 15:
                result["state"] = "starting"
            result["can_start"] = result["state"] == "offline" and since_start >= START_COOLDOWN
            self.status_cache = time.monotonic(), result.copy()
            return result

    def launch_fixed_start(self):
        script = self.server_dir / "Start-Server.ps1"
        if os.name != "nt" or not script.is_file():
            raise OSError("Windows server start script unavailable")
        powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        with (self.private_dir / "server-start.log").open("ab", buffering=0) as output:
            subprocess.Popen([str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                             cwd=self.server_dir, stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                             creationflags=subprocess.CREATE_NO_WINDOW, shell=False)

    def start(self, session):
        self.rate_limit("start:" + session["name"].casefold(), 12, 300)
        with self.start_lock:
            status = self.status(fresh=True)
            if status["state"] != "offline":
                return {"state": status["state"], "started": False, "message": "Serveren er allerede aktiv eller ved at starte/stoppe."}
            if not status["can_start"]:
                raise ApiError(429, "start_cooldown", "Serveren har lige modtaget en startanmodning. Vent to minutter.")
            # Commit before launching so restarts cannot erase the launch cooldown.
            with self.connect() as db:
                db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('last_start',?)", (str(time.time()),))
            try:
                self.launch_fixed_start()
            except OSError:
                raise ApiError(503, "start_failed", "Serveren kunne ikke startes. Bed Marius kontrollere den lokale log.")
            self.status_cache = (0, None)
            return {"state": "starting", "started": True, "message": "Start er sendt. Modpakken kan bruge et par minutter på at blive klar."}

    def preview(self, raw, session):
        url, _, _ = canonical_mod_url(raw)
        self.rate_limit("preview:" + session["name"].casefold(), 12, 60)
        with self.lock:
            cached = self.preview_cache.get(url)
            if cached and cached[0] > time.monotonic():
                return cached[1].copy()
        result = mod_metadata(url)
        with self.lock:
            if len(self.preview_cache) > 500:
                self.preview_cache.clear()
            self.preview_cache[url] = (time.monotonic() + 3600, result.copy())
        return result

    def suggestions(self, session, only_id=None):
        query = """SELECT s.*, (SELECT COUNT(*) FROM votes v WHERE v.suggestion_id=s.id) AS votes,
                   EXISTS(SELECT 1 FROM votes v WHERE v.suggestion_id=s.id AND v.voter=?) AS voted
                   FROM suggestions s"""
        parameters = [session["name"].casefold()]
        if only_id is not None:
            query += " WHERE s.id=?"
            parameters.append(only_id)
        query += " ORDER BY votes DESC, s.id DESC LIMIT 200"
        with self.connect() as db:
            rows = [dict(row) for row in db.execute(query, parameters)]
        for row in rows:
            row["voted"] = bool(row["voted"])
        return rows

    def add_suggestion(self, body, session):
        self.rate_limit("suggest:" + session["name"].casefold(), 6, 600)
        reason = body.get("reason", "")
        if not isinstance(reason, str) or len(reason) > 1500:
            raise ApiError(400, "invalid_reason", "Begrundelsen må højst være 1.500 tegn og kan også være tom.")
        metadata = self.preview(body.get("url"), session)
        with self.connect() as db:
            old = db.execute("SELECT id FROM suggestions WHERE url=?", (metadata["url"],)).fetchone()
            if old:
                suggestion_id, duplicate = old[0], True
            else:
                cursor = db.execute("""INSERT OR IGNORE INTO suggestions(url,title,description,image_url,source,reason,author,created_at)
                           VALUES(?,?,?,?,?,?,?,?)""", (metadata["url"], metadata["title"], metadata["description"], metadata["image_url"],
                           metadata["source"], reason.strip(), session["name"], utc_now()))
                duplicate = cursor.rowcount == 0
                suggestion_id = db.execute("SELECT id FROM suggestions WHERE url=?", (metadata["url"],)).fetchone()[0]
        return {"suggestion": self.suggestions(session, suggestion_id)[0], "duplicate": duplicate}

    def vote(self, suggestion_id, session):
        self.rate_limit("vote:" + session["name"].casefold(), 30, 60)
        voter = session["name"].casefold()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT id FROM suggestions WHERE id=?", (suggestion_id,)).fetchone():
                raise ApiError(404, "not_found", "Forslaget findes ikke.")
            old = db.execute("SELECT 1 FROM votes WHERE suggestion_id=? AND voter=?", (suggestion_id, voter)).fetchone()
            if old:
                db.execute("DELETE FROM votes WHERE suggestion_id=? AND voter=?", (suggestion_id, voter))
            else:
                db.execute("INSERT INTO votes(suggestion_id,voter) VALUES(?,?)", (suggestion_id, voter))
        return {"suggestion": self.suggestions(session, suggestion_id)[0]}


class Handler(BaseHTTPRequestHandler):
    server_version = "FriendsPanel"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    @property
    def panel(self):
        return self.server.panel

    def log_message(self, format_string, *args):
        # Never log headers, bodies, query strings, names or access tokens.
        pass

    def send_json(self, status, value):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        origin = self.headers.get("Origin")
        if origin in self.panel.origins:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def require_origin(self):
        if self.headers.get("Origin") not in self.panel.origins:
            raise ApiError(403, "origin_denied", "Denne side har ikke adgang til kontrolpanelet.")

    def do_OPTIONS(self):
        try:
            self.require_origin()
            if self.headers.get("Access-Control-Request-Method") not in {"GET", "POST"}:
                raise ApiError(405, "method_not_allowed", "Kun GET og POST er tilladt.")
            requested = {item.strip().lower() for item in self.headers.get("Access-Control-Request-Headers", "").split(",") if item.strip()}
            if not requested.issubset({"authorization", "content-type"}):
                raise ApiError(403, "headers_denied", "Header ikke tilladt.")
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()
        except ApiError as error:
            self.send_json(error.status, {"error": error.code, "message": error.message})

    def body(self):
        if self.headers.get("Transfer-Encoding") or self.headers.get_content_type() != "application/json":
            raise ApiError(415, "json_required", "Send JSON-data.")
        try:
            size = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            size = -1
        if not 0 <= size <= 8192:
            raise ApiError(413, "body_too_large", "Anmodningen er for stor eller mangler længde.")
        try:
            value = json.loads(self.rfile.read(size))
        except (ValueError, UnicodeError):
            raise ApiError(400, "invalid_json", "Ugyldige JSON-data.")
        if not isinstance(value, dict):
            raise ApiError(400, "invalid_json", "Send et JSON-objekt.")
        return value

    def dispatch(self, method):
        try:
            path = urllib.parse.urlsplit(self.path).path
            if self.path != path:
                raise ApiError(400, "invalid_path", "Brug en API-sti uden parametre.")
            if method == "GET" and path == "/health":
                return self.send_json(200, {"ok": True})
            if method == "POST":
                self.require_origin()
            # Reject unknown routes before authentication; no hidden command surface exists.
            vote_match = re.fullmatch(r"/api/suggestions/([1-9][0-9]{0,9})/vote", path)
            allowed = {"GET": {"/api/status", "/api/suggestions"}, "POST": {"/api/login", "/api/start", "/api/preview", "/api/suggestions"}}
            if path not in allowed[method] and not (method == "POST" and vote_match):
                raise ApiError(404, "not_found", "Denne handling findes ikke.")
            if method == "POST" and path == "/api/login":
                ip = self.headers.get("CF-Connecting-IP", self.client_address[0])[:100]
                return self.send_json(200, self.panel.login(self.body(), ip))
            session = self.panel.authenticate(self.headers.get("Authorization"))
            self.panel.rate_limit("requests:" + session["name"].casefold(), 150, 60)
            if method == "GET":
                result = self.panel.status() if path == "/api/status" else {"suggestions": self.panel.suggestions(session)}
            else:
                body = self.body()
                if path == "/api/start":
                    if body:
                        raise ApiError(400, "no_arguments", "Start tager ingen argumenter.")
                    result = self.panel.start(session)
                elif path == "/api/preview":
                    result = self.panel.preview(body.get("url"), session)
                elif path == "/api/suggestions":
                    result = self.panel.add_suggestion(body, session)
                else:
                    if body:
                        raise ApiError(400, "no_arguments", "Afstemning tager ingen argumenter.")
                    result = self.panel.vote(int(vote_match.group(1)), session)
            self.send_json(200, result)
        except ApiError as error:
            self.send_json(error.status, {"error": error.code, "message": error.message})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except Exception:
            # Tracebacks are deliberately local; HTTP errors never disclose local paths.
            import traceback
            with self.panel.lock:
                log_path = self.panel.private_dir / "agent-errors.log"
                if log_path.exists() and log_path.stat().st_size > 1_000_000:
                    log_path.replace(log_path.with_suffix(".previous.log"))
                with log_path.open("a", encoding="utf-8") as log:
                    log.write(utc_now() + "\n" + traceback.format_exc() + "\n")
            self.send_json(500, {"error": "internal_error", "message": "Der opstod en fejl. Prøv igen om lidt."})

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")


class PanelServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, address, panel):
        self.panel = panel
        self.slots = threading.BoundedSemaphore(24)
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-dir", type=Path, default=DEFAULT_SERVER / "panel-private")
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--server-dir", type=Path, default=DEFAULT_SERVER)
    parser.add_argument("--origin", action="append", default=[])
    args = parser.parse_args()
    if args.init:
        if not args.origin:
            parser.error("--init needs at least one --origin")
        path = initialize(args.private_dir, args.server_dir, args.origin)
        print("Private configuration created: " + str(path))
        print("The friend code is in friend-access-code.txt beside that file. Do not publish it.")
        return
    panel = Panel(args.private_dir)
    port = int(panel.config.get("port", 8766))
    if not 1024 <= port <= 65535:
        raise ValueError("Invalid loopback port")
    server = PanelServer(("127.0.0.1", port), panel)
    print(f"Start-only panel listening on http://127.0.0.1:{port}", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
