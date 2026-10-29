"""Offline release-catalog checks; all archives and databases are disposable.

Run with ``python -B -m unittest discover -s tests -p test_pack_catalog.py``.
No production profile, server, public docs directory, or network is used.
"""
from __future__ import annotations

from copy import deepcopy
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "agent" / "pack_catalog.py"
SPEC = importlib.util.spec_from_file_location("pack_catalog", SOURCE)
catalog = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = catalog
SPEC.loader.exec_module(catalog)


def item(project_id, file_id, version="1.0.0", kind="mod", environment=None):
    category = {"mod": "mc-mods", "resourcepack": "texture-packs", "shader": "shaders"}[kind]
    result = {
        "project_id": project_id,
        "file_id": file_id,
        "name": "Fixture " + str(project_id),
        "version": version,
        "kind": kind,
        "url": f"https://www.curseforge.com/minecraft/{category}/fixture-{project_id}",
    }
    if environment is not None:
        result["environment"] = environment
    return result


class PackCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pack-catalog-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.private = self.root / "private"
        self.docs = self.root / "docs"
        self.metadata = [
            item(101, 1001, "2.0.0", environment="client-and-server"),
            item(202, 2002, "32x", "resourcepack", "client"),
            item(303, 3003, "9.6", "shader", "client"),
        ]

    def archive(self, metadata=None, version="1.0.0", label="input", changes=None,
                extra_entries=(), comment=b"", filename=None):
        metadata = self.metadata if metadata is None else metadata
        manifest = {
            "name": "Create & Magic Lite",
            "version": version,
            "author": "Offline test fixture",
            "manifestType": "minecraftModpack",
            "manifestVersion": 1,
            "minecraft": {
                "version": "1.20.1",
                "modLoaders": [{"id": "forge-47.4.28", "primary": True}],
            },
            "overrides": "overrides",
            "files": [{"projectID": entry["project_id"], "fileID": entry["file_id"], "required": True}
                      for entry in metadata],
        }
        if changes:
            manifest.update(changes)
        parent = self.root / label
        parent.mkdir(parents=True, exist_ok=True)
        path = parent / (filename or f"Create-Magic-Lite-{version}.zip")
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            archive.writestr("overrides/README.txt", "Offline test fixture.\n")
            for name, content in extra_entries:
                if isinstance(name, str) and "\\" in name:
                    # ZipInfo otherwise normalizes separators on Windows before writing.
                    raw_name = name
                    name = zipfile.ZipInfo(name)
                    name.filename = name.orig_filename = raw_name
                archive.writestr(name, content)
            archive.comment = comment
        return path

    def publish(self, archive=None, metadata=None, **kwargs):
        return catalog.publish_release(
            self.private, archive or self.archive(),
            self.metadata if metadata is None else metadata, self.docs, **kwargs)

    def snapshot(self):
        with catalog.PackCatalog(self.private) as database:
            return database.snapshot()

    def assert_rejected(self, archive, metadata=None):
        with self.assertRaises(catalog.CatalogError):
            catalog.validate_archive(archive, self.metadata if metadata is None else metadata)

    def test_valid_archive_accepts_only_intended_pack_overrides(self):
        archive = self.archive(extra_entries=[
            ("overrides/config/DistantHorizons.toml", "enabled = true\n"),
            ("overrides/config/alexscaves-client.toml", "biome_ambient_light_coloring = false\n"),
            ("overrides/config/oculus.properties", "enableShaders=true\n"),
            ("overrides/shaderpacks/MakeUp-UltraFast-9.6.zip.txt", "SHADOWS=false\n"),
        ])
        self.assertIsInstance(catalog.validate_archive(archive, self.metadata), dict)

    def test_export_round_trip_has_exact_inventory_hash_and_public_contract(self):
        archive = self.archive()
        expected_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
        result = self.publish(archive, summary="The first public fixture release")
        self.assertEqual(result["version"], "1.0.0")
        self.assertFalse(result["idempotent"])
        self.assertEqual(result["release_count"], 1)
        exported = Path(result["archive_path"])
        snapshot_path = Path(result["snapshot_path"])
        self.assertTrue(exported.is_relative_to(self.docs))
        self.assertTrue(snapshot_path.is_relative_to(self.docs))
        self.assertEqual(exported.name, "Create-Magic-Lite-1.0.0.zip")
        self.assertEqual(hashlib.sha256(exported.read_bytes()).hexdigest(), expected_hash)
        public = json.loads(snapshot_path.read_text(encoding="utf-8"))
        self.assertEqual(public, self.snapshot())
        self.assertEqual(public["schema_version"], 1)
        self.assertEqual(public["latest_version"], "1.0.0")
        self.assertEqual(len(public["releases"]), 1)
        release = public["releases"][0]
        self.assertEqual(release["version"], "1.0.0")
        self.assertEqual(release["sha256"], expected_hash)
        self.assertEqual(release["minecraft_version"], "1.20.1")
        self.assertEqual(release["loader"], "forge-47.4.28")
        self.assertEqual(release["summary"], "The first public fixture release")
        self.assertTrue(release["published_at"])
        self.assertEqual({(entry["project_id"], entry["file_id"]) for entry in release["items"]},
                         {(101, 1001), (202, 2002), (303, 3003)})
        self.assertEqual({kind: sum(entry["kind"] == kind for entry in release["items"])
                          for kind in ("mod", "resourcepack", "shader")},
                         {"mod": 1, "resourcepack": 1, "shader": 1})
        encoded = json.dumps(public)
        self.assertNotIn(str(self.private), encoded)
        self.assertNotIn(str(archive), encoded)

    def test_existing_suggestions_and_votes_survive_with_pre_migration_backup(self):
        self.private.mkdir()
        database_path = self.private / "panel.sqlite3"
        with closing(sqlite3.connect(database_path)) as db, db:
            db.executescript("""
                CREATE TABLE suggestions (id INTEGER PRIMARY KEY, payload TEXT, custom_field BLOB);
                CREATE TABLE votes (suggestion_id INTEGER, user_name TEXT, extra TEXT);
                CREATE TABLE unrelated_settings (name TEXT PRIMARY KEY, value TEXT);
            """)
            db.execute("INSERT INTO suggestions VALUES (7, ?, ?)", ('{"arbitrary":"kept"}', b"\x00\x01"))
            db.execute("INSERT INTO votes VALUES (7, ?, ?)", ("Existing friend", "opaque vote value"))
            db.execute("INSERT INTO unrelated_settings VALUES (?, ?)", ("custom", "keep me"))
        before_tables = {"suggestions", "votes", "unrelated_settings"}
        result = self.publish()
        self.assertIsNotNone(result.get("backup_path"))
        backup = Path(result["backup_path"])
        self.assertTrue(backup.is_file())
        self.assertNotEqual(backup.resolve(), database_path.resolve())
        for path in (database_path, backup):
            with self.subTest(database=path.name), closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("SELECT * FROM suggestions").fetchall(),
                                 [(7, '{"arbitrary":"kept"}', b"\x00\x01")])
                self.assertEqual(db.execute("SELECT * FROM votes").fetchall(),
                                 [(7, "Existing friend", "opaque vote value")])
                self.assertEqual(db.execute("SELECT * FROM unrelated_settings").fetchall(),
                                 [("custom", "keep me")])
        with closing(sqlite3.connect(backup)) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(tables, before_tables, "Backup must precede catalog table creation")

    def test_identical_reimport_is_idempotent_and_keeps_publication_timestamp(self):
        archive = self.archive()
        first = self.publish(archive)
        original_snapshot = self.snapshot()
        second = self.publish(archive)
        self.assertFalse(first["idempotent"])
        self.assertTrue(second["idempotent"])
        self.assertEqual(second["release_count"], 1)
        self.assertEqual(self.snapshot(), original_snapshot)
        self.assertEqual(Path(first["archive_path"]).read_bytes(), archive.read_bytes())

    def test_existing_version_rejects_changed_zip_bytes_without_changing_release(self):
        self.publish(self.archive(label="first"))
        before = self.snapshot()
        changed = self.archive(label="changed", comment=b"different archive bytes")
        with self.assertRaises(catalog.CatalogError):
            self.publish(changed)
        self.assertEqual(self.snapshot(), before)

    def test_existing_version_rejects_changed_inventory_metadata(self):
        archive = self.archive()
        self.publish(archive)
        before = self.snapshot()
        changed = deepcopy(self.metadata)
        changed[0]["version"] = "different-displayed-version"
        with self.assertRaises(catalog.CatalogError):
            self.publish(archive, changed)
        self.assertEqual(self.snapshot(), before)

    def test_baseline_diff_contains_removal_and_previous_version_without_fake_release(self):
        baseline = [item(101, 1000, "1.0.0"), item(404, 4004, "4.0.0")]
        current = [item(101, 1001, "2.0.0"), item(505, 5005, "5.0.0")]
        self.publish(self.archive(current), current, baseline=baseline)
        public = self.snapshot()
        self.assertEqual([release["version"] for release in public["releases"]], ["1.0.0"])
        changes = public["releases"][0]["changes"]
        self.assertEqual([entry["project_id"] for entry in changes["added"]], [505])
        self.assertEqual([entry["project_id"] for entry in changes["removed"]], [404])
        self.assertEqual([entry["project_id"] for entry in changes["updated"]], [101])
        self.assertEqual(changes["updated"][0]["previous_version"], "1.0.0")
        self.assertEqual(changes["updated"][0]["version"], "2.0.0")
        self.assertEqual(changes["removed"][0]["version"], "4.0.0")

    def test_successive_releases_are_newest_first_and_diff_from_previous_inventory(self):
        old = [item(101, 1000, "1.0.0"), item(404, 4004, "4.0.0")]
        new = [item(101, 1001, "2.0.0"), item(505, 5005, "5.0.0")]
        self.publish(self.archive(old, "1.0.0"), old)
        result = self.publish(self.archive(new, "1.1.0"), new)
        public = self.snapshot()
        self.assertEqual(result["release_count"], 2)
        self.assertEqual(public["latest_version"], "1.1.0")
        self.assertEqual([release["version"] for release in public["releases"]], ["1.1.0", "1.0.0"])
        changes = public["releases"][0]["changes"]
        self.assertEqual([entry["project_id"] for entry in changes["removed"]], [404])
        self.assertEqual(changes["updated"][0]["previous_version"], "1.0.0")

    def test_manifest_references_must_exactly_match_metadata(self):
        archive = self.archive()
        wrong_file = deepcopy(self.metadata)
        wrong_file[0]["file_id"] += 1
        for metadata in (self.metadata[:-1], self.metadata + [item(999, 9999)], wrong_file):
            with self.subTest(metadata=metadata):
                self.assert_rejected(archive, metadata)

    def test_duplicate_manifest_and_metadata_references_are_rejected(self):
        base_refs = [{"projectID": entry["project_id"], "fileID": entry["file_id"], "required": True}
                     for entry in self.metadata]
        for reference in (base_refs[0], {"projectID": 101, "fileID": 9999, "required": True}):
            with self.subTest(reference=reference):
                self.assert_rejected(self.archive(changes={"files": base_refs + [reference]}))
        archive = self.archive()
        for duplicate in (deepcopy(self.metadata[0]), item(101, 9999)):
            with self.subTest(duplicate=duplicate):
                self.assert_rejected(archive, self.metadata + [duplicate])

    def test_curseforge_optional_islocked_flag_accepts_only_booleans(self):
        references = [{"projectID": entry["project_id"], "fileID": entry["file_id"],
                       "required": True, "isLocked": False} for entry in self.metadata]
        archive = self.archive(changes={"files": references})
        self.assertEqual(len(catalog.validate_archive(archive, self.metadata)["items"]), 3)
        references[0]["isLocked"] = True
        self.assertIsInstance(catalog.validate_archive(self.archive(changes={"files": references}), self.metadata), dict)
        for invalid in (0, "false", None):
            references[0]["isLocked"] = invalid
            with self.subTest(invalid=invalid):
                self.assert_rejected(self.archive(changes={"files": references}))

    def test_unsafe_release_versions_and_oversized_metadata_are_rejected(self):
        for version in ("../1.0.0", "1/2", "1\\2", "1..2", "1:2", "1.0.0.", "1%2f2"):
            with self.subTest(version=version):
                self.assert_rejected(self.archive(changes={"version": version}, filename="input.zip"))
        oversized = [item(i, i) for i in range(1, 1002)]
        with self.assertRaises(catalog.CatalogError):
            catalog.validate_metadata(oversized)

    def test_existing_different_download_is_not_overwritten_or_imported(self):
        downloads = self.docs / "downloads"
        downloads.mkdir(parents=True)
        target = downloads / "Create-Magic-Lite-1.0.0.zip"
        target.write_bytes(b"existing different download")
        with self.assertRaises(catalog.CatalogError):
            self.publish()
        self.assertEqual(target.read_bytes(), b"existing different download")
        self.assertEqual(self.snapshot()["releases"], [])

    def test_failed_snapshot_export_can_retry_the_same_committed_release(self):
        archive = self.archive()
        with patch.object(catalog, "atomic_snapshot", side_effect=OSError("fixture failure")):
            with self.assertRaises(OSError):
                self.publish(archive)
        committed = self.snapshot()
        self.assertEqual(len(committed["releases"]), 1)
        result = self.publish(archive)
        self.assertTrue(result["idempotent"])
        self.assertEqual(self.snapshot(), committed)
        self.assertEqual(json.loads(Path(result["snapshot_path"]).read_text(encoding="utf8")), committed)

    def test_manifest_identity_and_minecraft_forge_fields_are_enforced(self):
        invalid = [
            {"manifestType": "other"}, {"manifestVersion": 2}, {"overrides": "../overrides"},
            {"name": "Another pack"},
            {"minecraft": {"version": "invalid-version", "modLoaders": [{"id": "forge-47.4.28", "primary": True}]}},
            {"minecraft": {"version": "1.20.1", "modLoaders": [{"id": "fabric-0.16.0", "primary": True}]}},
            {"minecraft": {"version": "1.20.1", "modLoaders": [{"id": "forge-47.4.28", "primary": False}]}},
            {"minecraft": {"version": "1.20.1", "modLoaders": [
                {"id": "forge-47.4.28", "primary": True}, {"id": "forge-47.4.27", "primary": False}]}},
        ]
        for changes in invalid:
            with self.subTest(changes=changes):
                self.assert_rejected(self.archive(changes=changes))
        # The input may have an arbitrary local name; the download name is derived safely.
        facts = catalog.validate_archive(self.archive(filename="local-export.zip"), self.metadata)
        self.assertEqual(facts["download_url"], "downloads/Create-Magic-Lite-1.0.0.zip")

    def test_metadata_requires_positive_integer_ids_and_category_correct_urls(self):
        invalid = [
            {"project_id": True}, {"project_id": 0}, {"file_id": -1}, {"file_id": "1001"},
            {"kind": "executable"}, {"environment": "secret-machine"},
            {"url": "https://www.curseforge.com/minecraft/shaders/fixture-101"},
            {"url": "javascript:alert(1)"},
            {"url": "https://attacker.invalid/minecraft/mc-mods/fixture-101"},
            {"url": "https://user:password@www.curseforge.com/minecraft/mc-mods/fixture-101"},
        ]
        archive = self.archive()
        for fields in invalid:
            metadata = deepcopy(self.metadata)
            metadata[0].update(fields)
            with self.subTest(fields=fields):
                self.assert_rejected(archive, metadata)

    def test_unsafe_zip_paths_raw_jars_and_private_overrides_are_rejected(self):
        names = [
            "../outside.txt", "overrides/../outside.txt", "/overrides/README.txt",
            "C:/overrides/README.txt", "overrides\\config\\oculus.properties",
            "mods/raw.jar", "overrides/mods/raw.jar", "overrides/config/secret.jar",
            "overrides/config/embeddium-fingerprint.json", "overrides/config/jei/world/history.ini",
            "overrides/essential/config.toml", "overrides/servers.dat", "overrides/options.txt",
            "overrides/shaderpacks/MakeUp-UltraFast-../../private.zip.txt",
        ]
        for name in names:
            with self.subTest(name=name):
                self.assert_rejected(self.archive(extra_entries=[(name, b"forbidden fixture")]))

    def test_symlink_entry_is_rejected_even_when_its_name_is_allowlisted(self):
        entry = zipfile.ZipInfo("overrides/config/oculus.properties")
        entry.create_system = 3
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive = self.archive(extra_entries=[(entry, "../../private/config.json")])
        self.assert_rejected(archive)

    def test_invalid_publish_does_not_create_release_or_public_archive(self):
        archive = self.archive(extra_entries=[("overrides/servers.dat", b"private fixture")])
        with self.assertRaises(catalog.CatalogError):
            self.publish(archive)
        self.assertFalse(any(self.docs.rglob("*.zip")) if self.docs.exists() else False)
        if self.private.exists():
            self.assertEqual(self.snapshot()["releases"], [])

    def test_cli_publishes_archive_metadata_baseline_and_summary_in_temporary_dirs(self):
        archive = self.archive()
        metadata_path = self.root / "metadata.json"
        baseline_path = self.root / "baseline.json"
        metadata_path.write_text(json.dumps(self.metadata), encoding="utf-8")
        baseline_path.write_text(json.dumps([item(101, 1000, "1.0.0")]), encoding="utf-8")
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run([
            sys.executable, "-B", str(ROOT / "scripts" / "publish_pack.py"),
            "--private-dir", str(self.private), "--archive", str(archive),
            "--metadata", str(metadata_path), "--baseline", str(baseline_path),
            "--docs-dir", str(self.docs), "--summary", "CLI fixture release",
        ], cwd=ROOT, env=environment, capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        reply = json.loads(result.stdout)
        self.assertEqual(reply["version"], "1.0.0")
        public = json.loads(Path(reply["snapshot_path"]).read_text(encoding="utf-8"))
        self.assertEqual(public["releases"][0]["summary"], "CLI fixture release")
        self.assertEqual(public["releases"][0]["changes"]["updated"][0]["previous_version"], "1.0.0")


if __name__ == "__main__":
    unittest.main()
