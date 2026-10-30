"""Offline, append-only modpack releases in the panel's private SQLite database.

Only the pack_catalog_* tables belong to this module. ZIPs are validated, never
extracted. Public JSON contains an explicit allowlist of release/item fields.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import stat
import tempfile
from urllib.parse import urlsplit
import uuid
import zipfile


REPOSITORY = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 1
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_EXPANDED_BYTES = 64 * 1024 * 1024
MAX_ENTRY_BYTES = 8 * 1024 * 1024
KINDS = {"mod": "mc-mods", "resourcepack": "texture-packs", "shader": "shaders"}
ENVIRONMENTS = {"client", "server", "client-and-server", "unknown"}
OVERRIDES = {
    "overrides/README.txt", "overrides/config/DistantHorizons.toml",
    "overrides/config/alexscaves-client.toml", "overrides/config/oculus.properties",
    "overrides/defaultconfigs/securitycraft-server.toml",
}


class CatalogError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise CatalogError(message)


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def checked_path(path):
    """Resolve a local path without accepting a symlink/junction at any level."""
    path = Path(os.path.abspath(path))
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        require(not stat.S_ISLNK(info.st_mode)
                and not getattr(info, "st_file_attributes", 0) & 0x400,
                "Symlinks and reparse points are not valid catalog paths")
    return path


def text(value, field, limit):
    require(isinstance(value, str) and 0 < len(value.strip()) <= limit
            and not any(ord(c) < 32 for c in value), "Invalid " + field)
    return value.strip()


def public_url(value, kind=None, image=False):
    value = text(value, "public URL", 2000)
    require("\\" not in value and not any(c.isspace() for c in value), "Invalid public URL")
    try:
        parsed = urlsplit(value)
        require(parsed.scheme == "https" and parsed.hostname and parsed.port in (None, 443)
                and not parsed.username and not parsed.password and not parsed.fragment,
                "Public URLs must use HTTPS without credentials")
    except ValueError as error:
        raise CatalogError("Invalid public URL") from error
    host = parsed.hostname.lower()
    if image:
        require(host == "cdn.modrinth.com" or host == "forgecdn.net" or host.endswith(".forgecdn.net"),
                "Image URL is not on an approved public CDN")
    elif host in {"curseforge.com", "www.curseforge.com"}:
        require(bool(re.fullmatch(r"/minecraft/" + KINDS[kind] + r"/[A-Za-z0-9_-]+/?", parsed.path)),
                "Project URL category does not match the item kind")
    elif host in {"modrinth.com", "www.modrinth.com"}:
        category = {"mod": "mod", "resourcepack": "resourcepack", "shader": "shader"}[kind]
        require(bool(re.fullmatch("/" + category + r"/[A-Za-z0-9_-]+/?", parsed.path)),
                "Project URL category does not match the item kind")
    else:
        raise CatalogError("Project URL must be on CurseForge or Modrinth")
    require(not parsed.query, "Public metadata URLs must not contain query parameters")
    return value


def validate_metadata(items):
    require(isinstance(items, list) and len(items) <= 1000, "Metadata must be an item list")
    result, seen = [], set()
    required = {"project_id", "file_id", "name", "version", "kind", "url"}
    for item in items:
        require(isinstance(item, dict) and required <= item.keys()
                and not item.keys() - required - {"image_url", "environment"},
                "Metadata contains missing or non-public fields")
        project, file_id = item["project_id"], item["file_id"]
        require(type(project) is int and 0 < project < 2**63
                and type(file_id) is int and 0 < file_id < 2**63, "Invalid project/file ID")
        require(project not in seen, "Duplicate metadata project ID")
        seen.add(project)
        kind = item["kind"]
        require(isinstance(kind, str) and kind in KINDS, "Invalid item kind")
        cleaned = {"project_id": project, "file_id": file_id,
                   "name": text(item["name"], "item name", 200),
                   "version": text(item["version"], "item version", 200),
                   "kind": kind, "url": public_url(item["url"], kind=kind)}
        if "image_url" in item:
            cleaned["image_url"] = None if item["image_url"] is None else public_url(item["image_url"], image=True)
        if "environment" in item:
            require(isinstance(item["environment"], str) and item["environment"] in ENVIRONMENTS,
                    "Invalid item environment")
            cleaned["environment"] = item["environment"]
        result.append(cleaned)
    return sorted(result, key=lambda x: (x["kind"], x["name"].casefold(), x["project_id"]))


def archive_name(version):
    require(isinstance(version, str) and bool(re.fullmatch(r"[0-9][A-Za-z0-9._+-]{0,63}", version))
            and ".." not in version and not version.endswith("."), "Unsafe release version")
    return "Create-Magic-Lite-" + version + ".zip"


def allowed_entry(name, directory=False):
    require(isinstance(name, str) and name and "\\" not in name and ":" not in name
            and not any(ord(c) < 32 for c in name), "Unsafe ZIP member path")
    clean = name[:-1] if directory and name.endswith("/") else name
    parts = clean.split("/")
    require(not name.startswith("/") and all(p not in ("", ".", "..") for p in parts)
            and all(not p.endswith((".", " ")) for p in parts), "Unsafe ZIP member path")
    require(not PurePosixPath(clean).is_absolute(), "Absolute ZIP member path")
    if directory:
        require(clean in {"overrides", "overrides/config", "overrides/shaderpacks", "overrides/defaultconfigs"}, "ZIP directory is not allowed")
    else:
        require(clean in {"manifest.json", "modlist.html"} | OVERRIDES
                or bool(re.fullmatch(r"overrides/shaderpacks/MakeUp-UltraFast-[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*\.zip\.txt", clean)),
                "ZIP member is not on the public override allowlist")


def validate_archive(archive_path, metadata):
    """Return validated public facts and the exact ZIP bytes to publish."""
    items = validate_metadata(metadata)
    path = checked_path(archive_path)
    require(path.is_file() and path.suffix.lower() == ".zip", "Archive must be a ZIP file")
    require(path.stat().st_size <= MAX_ARCHIVE_BYTES, "Archive exceeds the size limit")
    raw = path.read_bytes()
    require(len(raw) <= MAX_ARCHIVE_BYTES, "Archive exceeds the size limit")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            require(0 < len(entries) <= 1000, "Invalid ZIP member count")
            seen, expanded = set(), 0
            for entry in entries:
                require(entry.orig_filename == entry.filename, "ZIP member name contains a null byte")
                allowed_entry(entry.filename, entry.is_dir())
                key = entry.filename.rstrip("/").casefold()
                require(key not in seen, "Duplicate or case-colliding ZIP member")
                seen.add(key)
                mode = entry.external_attr >> 16
                require(not stat.S_ISLNK(mode) and stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR),
                        "ZIP links and special files are not allowed")
                require(not entry.flag_bits & 1 and entry.file_size <= MAX_ENTRY_BYTES,
                        "Encrypted or oversized ZIP member")
                expanded += entry.file_size
                require(expanded <= MAX_EXPANDED_BYTES, "Expanded ZIP exceeds the size limit")
                # Read each allowed text entry to verify its CRC and text encoding.
                if not entry.is_dir():
                    archive.read(entry).decode("utf-8-sig")
            require("manifest.json" in archive.namelist(), "ZIP has no manifest.json")
            manifest = json.loads(archive.read("manifest.json").decode("utf-8-sig"))
    except (zipfile.BadZipFile, RuntimeError, UnicodeError, KeyError, json.JSONDecodeError) as error:
        raise CatalogError("ZIP or manifest is invalid") from error
    require(isinstance(manifest, dict) and manifest.get("manifestType") == "minecraftModpack"
            and type(manifest.get("manifestVersion")) is int and manifest["manifestVersion"] == 1
            and manifest.get("name") == "Create & Magic Lite" and manifest.get("overrides") == "overrides",
            "Manifest is not the expected CurseForge modpack")
    version = manifest.get("version")
    filename = archive_name(version)
    minecraft = manifest.get("minecraft")
    require(isinstance(minecraft, dict), "Minecraft manifest section is missing")
    mc_version = minecraft.get("version")
    require(isinstance(mc_version, str) and bool(re.fullmatch(r"1\.\d+(?:\.\d+)?", mc_version)),
            "Invalid Minecraft version")
    loaders = minecraft.get("modLoaders")
    require(isinstance(loaders, list) and len(loaders) == 1 and isinstance(loaders[0], dict)
            and loaders[0].get("primary") is True and isinstance(loaders[0].get("id"), str)
            and bool(re.fullmatch(r"forge-\d+(?:\.\d+){1,3}", loaders[0]["id"])),
            "Manifest must specify one primary Forge loader")
    references = manifest.get("files")
    require(isinstance(references, list) and 0 < len(references) <= 1000, "Manifest file references are missing")
    refs, projects = set(), set()
    for ref in references:
        require(isinstance(ref, dict) and set(ref) <= {"projectID", "fileID", "required", "isLocked"},
                "Invalid manifest file reference")
        project, file_id = ref.get("projectID"), ref.get("fileID")
        require(type(project) is int and project > 0 and type(file_id) is int and file_id > 0
                and type(ref.get("required")) is bool, "Invalid manifest file reference")
        require("isLocked" not in ref or type(ref["isLocked"]) is bool, "Invalid manifest isLocked flag")
        require(project not in projects, "Duplicate manifest project reference")
        projects.add(project)
        refs.add((project, file_id))
    require(refs == {(x["project_id"], x["file_id"]) for x in items},
            "Manifest references do not exactly match public metadata")
    return {"version": version, "minecraft_version": mc_version, "loader": loaders[0]["id"],
            "sha256": digest(raw), "download_url": "downloads/" + filename,
            "items": items, "archive_bytes": raw}


def changes_between(previous, current):
    before = {x["project_id"]: x for x in previous}
    after = {x["project_id"]: x for x in current}
    added = [x for x in current if x["project_id"] not in before]
    removed = [x for x in previous if x["project_id"] not in after]
    updated = []
    for item in current:
        old = before.get(item["project_id"])
        if old and any(old[k] != item[k] for k in ("file_id", "version", "kind")):
            updated.append({**item, "previous_version": old["version"]})
    return {"added": added, "updated": updated, "removed": removed}


class PackCatalog:
    def __init__(self, private_dir):
        self.private_dir = checked_path(private_dir)
        require(self.private_dir != REPOSITORY and REPOSITORY not in self.private_dir.parents,
                "Private database must remain outside the repository")
        self.private_dir.mkdir(parents=True, exist_ok=True)
        self.path = checked_path(self.private_dir / "panel.sqlite3")
        self.backup_path = None
        self.connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            self._migrate()
        except BaseException:
            self.connection.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.connection.close()

    @contextmanager
    def transaction(self):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise

    def _migrate(self):
        tables = {r[0] for r in self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "pack_catalog_meta" not in tables:
            require(not any(n.startswith("pack_catalog_") for n in tables), "Incomplete catalog schema needs review")
            folder = checked_path(self.private_dir / "pack-catalog-backups")
            folder.mkdir(exist_ok=True)
            backup = folder / ("before-v1-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex + ".sqlite3")
            with closing(sqlite3.connect(backup)) as destination:
                self.connection.backup(destination)
            self.backup_path = backup
        with self.transaction():
            self.connection.execute("CREATE TABLE IF NOT EXISTS pack_catalog_meta (id INTEGER PRIMARY KEY CHECK(id=1), schema_version INTEGER NOT NULL)")
            self.connection.execute("INSERT OR IGNORE INTO pack_catalog_meta VALUES (1, ?)", (SCHEMA_VERSION,))
            row = self.connection.execute("SELECT schema_version FROM pack_catalog_meta WHERE id=1").fetchone()
            require(row == (SCHEMA_VERSION,), "Unsupported catalog schema version")
            self.connection.execute("""CREATE TABLE IF NOT EXISTS pack_catalog_releases (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, version TEXT UNIQUE NOT NULL,
                sha256 TEXT NOT NULL, release_json TEXT NOT NULL, baseline_json TEXT
            )""")
            self.connection.execute("""CREATE TRIGGER IF NOT EXISTS pack_catalog_no_update BEFORE UPDATE ON pack_catalog_releases
                BEGIN SELECT RAISE(ABORT, 'Published releases are immutable'); END""")
            self.connection.execute("""CREATE TRIGGER IF NOT EXISTS pack_catalog_no_delete BEFORE DELETE ON pack_catalog_releases
                BEGIN SELECT RAISE(ABORT, 'Published releases are immutable'); END""")

    def snapshot(self):
        releases = [json.loads(r[0]) for r in self.connection.execute(
            "SELECT release_json FROM pack_catalog_releases ORDER BY sequence DESC")]
        return {"schema_version": SCHEMA_VERSION,
                "latest_version": releases[0]["version"] if releases else None, "releases": releases}

    def prepare_release(self, facts, baseline=None, summary=None):
        """Must run inside transaction(); returns public release and idempotence."""
        row = self.connection.execute("SELECT release_json, baseline_json FROM pack_catalog_releases WHERE version=?",
                                      (facts["version"],)).fetchone()
        if row:
            existing = json.loads(row[0])
            require(all(existing[k] == facts[k] for k in ("sha256", "minecraft_version", "loader", "items", "download_url")),
                    "This version already exists with different ZIP bytes or metadata")
            require(summary is None or summary == existing["summary"], "Published summary is immutable")
            require(baseline is None or encode(baseline) == row[1], "Published baseline is immutable")
            return existing, True
        previous = self.snapshot()["releases"]
        require(not previous or baseline is None, "A baseline is only valid for the first real release")
        old_items = previous[0]["items"] if previous else (baseline or [])
        changes = changes_between(old_items, facts["items"])
        if summary is None:
            summary = f"{len(changes['added'])} tilføjet, {len(changes['updated'])} opdateret og {len(changes['removed'])} fjernet."
        release = {k: facts[k] for k in ("version", "minecraft_version", "loader", "download_url", "sha256", "items")}
        release.update(published_at=utc_now(), summary=summary, changes=changes,
                       mod_count=sum(x["kind"] == "mod" for x in facts["items"]),
                       resourcepack_count=sum(x["kind"] == "resourcepack" for x in facts["items"]),
                       shader_count=sum(x["kind"] == "shader" for x in facts["items"]))
        self.connection.execute("INSERT INTO pack_catalog_releases(version,sha256,release_json,baseline_json) VALUES (?,?,?,?)",
                                (facts["version"], facts["sha256"], encode(release), encode(baseline) if baseline is not None else None))
        return release, False


def write_archive(destination, raw):
    checked_path(destination)
    if destination.exists():
        require(destination.is_file() and digest(destination.read_bytes()) == digest(raw),
                "Public download filename already contains different bytes")
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".pack-download-", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        # Exclusive promotion: do not overwrite a different file that appeared.
        try:
            os.link(temporary, destination)
        except FileExistsError:
            checked_path(destination)
            require(destination.is_file() and digest(destination.read_bytes()) == digest(raw),
                    "Public download appeared with different bytes")
    finally:
        Path(temporary).unlink(missing_ok=True)


def atomic_snapshot(path, snapshot):
    checked_path(path)
    descriptor, temporary = tempfile.mkstemp(prefix=".pack-catalog-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(snapshot, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def publish_release(private_dir, archive_path, metadata, docs_dir, baseline=None, summary=None):
    facts = validate_archive(archive_path, metadata)
    baseline = validate_metadata(baseline) if baseline is not None else None
    summary = text(summary, "release summary", 1500) if summary is not None else None
    private, docs = checked_path(private_dir), checked_path(docs_dir)
    require(private != docs and private not in docs.parents and docs not in private.parents,
            "Private state and public docs must be separate directory trees")
    require(private != REPOSITORY and REPOSITORY not in private.parents,
            "Private database must remain outside the repository")
    docs.mkdir(parents=True, exist_ok=True)
    downloads = checked_path(docs / "downloads")
    downloads.mkdir(exist_ok=True)
    destination = checked_path(downloads / archive_name(facts["version"]))
    snapshot_path = checked_path(docs / "releases.json")
    with PackCatalog(private) as database:
        with database.transaction():
            release, idempotent = database.prepare_release(facts, baseline, summary)
            write_archive(destination, facts["archive_bytes"])
        # Reacquire the database write lock and export the latest committed set.
        # Concurrent publishers cannot overwrite a newer snapshot with an older one.
        with database.transaction():
            snapshot = database.snapshot()
            atomic_snapshot(snapshot_path, snapshot)
        return {"version": release["version"], "idempotent": idempotent,
                "release_count": len(snapshot["releases"]), "item_count": len(release["items"]),
                "archive_path": str(destination), "snapshot_path": str(snapshot_path),
                "backup_path": str(database.backup_path) if database.backup_path else None}
