import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "scripts" / "catalog_metadata.py"
SPEC = importlib.util.spec_from_file_location("catalog_metadata", SOURCE)
metadata = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(metadata)


class CatalogMetadataTests(unittest.TestCase):
    def test_allowlist_excludes_profile_secrets_and_unrelated_files(self):
        profile = {"accountToken": "secret", "installedAddons": [
            {"addonID": 1, "name": "Test Mod", "categoryClassID": 6,
             "modFolderPath": "C:/Private", "instanceID": "private-id",
             "webSiteURL": "https://www.curseforge.com/minecraft/mc-mods/test?tracking=1",
             "thumbnailUrl": "https://media.forgecdn.net/avatars/1/2.png?private_test_parameter=secret#fragment",
             "installedFile": {"id": 2, "fileName": "test-1.20.1-2.5.0.jar", "private": "secret"}},
            {"addonID": 9, "installedFile": {"id": 10}, "private": "secret"}]}
        result = metadata.extract_metadata(profile, {(1, 2)}, {"test-1.20.1-2.5.0.jar"})
        self.assertEqual(result, [{"project_id": 1, "file_id": 2, "name": "Test Mod", "version": "2.5.0",
                                  "kind": "mod", "url": "https://www.curseforge.com/minecraft/mc-mods/test",
                                  "image_url": "https://media.forgecdn.net/avatars/1/2.png",
                                  "environment": "client-and-server"}])
        with self.assertRaises(ValueError):
            metadata.extract_metadata(profile, {(1, 999)})

    def test_versions_and_resource_pack_project_links(self):
        cases = {"Structory_1.20.x_v1.3.5.jar": "1.3.5", "Quark-4.0-462.jar": "4.0-462",
                 "Essential_1-5-1_forge_1-20-1.jar": "1.5.1", "moonlight-1.20-2.16.38B-forge.jar": "2.16.38B",
                 "Faithful 64x - Beta 9.zip": "Beta 9", "Faithful 32x - 1.20.1.zip": "1.20.1",
                 "copycats-3.0.10+mc.1.20.1-forge.jar": "3.0.10",
                 "test-1.20.1-2.0.0-beta.1-forge.jar": "2.0.0-beta.1",
                 "test-2.0.0-beta.2.jar": "2.0.0-beta.2", "test-2.0.0-rc.1.jar": "2.0.0-rc.1"}
        for filename, expected in cases.items():
            with self.subTest(filename=filename):
                self.assertEqual(metadata.display_version(filename), expected)
        self.assertEqual(metadata.public_url("https://www.curseforge.com/minecraft/texture-packs/faithful-32x", "resourcepack"),
                         "https://www.curseforge.com/minecraft/texture-packs/faithful-32x")
        for url in ["https://attacker.invalid/minecraft/mc-mods/test", "javascript:alert(1)",
                    "https://user:password@www.curseforge.com/minecraft/mc-mods/test"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                metadata.public_url(url, "mod")

    def test_missing_server_directory_fails_without_writing_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            instance = root / "instance.json"
            instance.write_text(json.dumps({"installedAddons": []}), encoding="utf-8")
            output = root / "metadata.json"
            result = subprocess.run([sys.executable, str(SOURCE), "--instance", str(instance),
                                     "--server-mods", str(root / "missing"), "--output", str(output)],
                                    capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("existing directory", result.stderr)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
