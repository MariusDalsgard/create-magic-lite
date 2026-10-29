"""Extract only public mod metadata from a local CurseForge profile.

This never copies the profile, account settings, local paths or saved worlds.
The release manifest remains authoritative for exactly which files are published.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit
import zipfile


KINDS = {6: "mod", 12: "resourcepack", 6552: "shader"}
PATHS = {"mod": "mc-mods", "resourcepack": "texture-packs", "shader": "shaders"}


def display_version(filename: str) -> str:
    stem = re.sub(r"\.(?:jar|zip)$", "", filename, flags=re.I)
    if stem.startswith("Essential_"):
        found = re.search(r"Essential_(\d+)-(\d+)-(\d+)", stem)
        if found:
            return ".".join(found.groups())
    if re.search(r"\bBeta\s+\d+", stem, re.I):
        return re.search(r"\bBeta\s+\d+", stem, re.I).group(0)
    without_minecraft = re.sub(r"(?<!\d)(?:mc[.-]?)?1\.20(?:\.1|\.x)?(?![\d.])", "", stem, flags=re.I)
    version = re.search(r"(?<!\d)\d+\.\d+(?:\.\d+)*(?:B)?(?:-(?:\d+|(?:alpha|beta|rc|pre|preview|dev|snapshot)(?:[.-]?\d+)*))?(?!\d)", without_minecraft, re.I)
    if version:
        return version.group(0)
    minecraft = re.search(r"(?<!\d)1\.20\.1(?!\d)", stem)
    return minecraft.group(0) if minecraft else stem


def public_url(raw: object, kind: str) -> str:
    value = urlsplit(str(raw))
    if (value.scheme != "https" or value.hostname not in ("www.curseforge.com", "curseforge.com")
            or value.username or value.password or value.port
            or not re.fullmatch(r"/minecraft/" + PATHS[kind] + r"/[a-zA-Z0-9_-]+/?", value.path)):
        raise ValueError("Profile contains a non-project website URL")
    return urlunsplit(("https", "www.curseforge.com", value.path.rstrip("/"), "", ""))


def extract_metadata(profile: dict, references: set[tuple[int, int]] | None = None,
                     server_files: set[str] | None = None) -> list[dict]:
    output = []
    seen = set()
    for addon in profile.get("installedAddons", []):
        installed = addon.get("installedFile") or {}
        identity = (addon.get("addonID"), installed.get("id"))
        if references is not None and identity not in references:
            continue
        if any(type(value) is not int or value <= 0 for value in identity) or identity[0] in seen:
            raise ValueError("Missing or duplicate CurseForge project/file identity")
        seen.add(identity[0])
        kind = KINDS.get(addon.get("categoryClassID"))
        if kind is None:
            raise ValueError("Unsupported CurseForge content category")
        filename = installed.get("fileName", "")
        if not isinstance(filename, str) or not filename or Path(filename).name != filename:
            raise ValueError("Invalid published filename")
        item = {
            "project_id": identity[0], "file_id": identity[1],
            "name": str(addon["name"]), "version": display_version(filename),
            "kind": kind, "url": public_url(addon["webSiteURL"], kind),
        }
        image = urlsplit(str(addon.get("thumbnailUrl") or ""))
        if (image.scheme == "https" and image.hostname in ("media.forgecdn.net", "mediafilez.forgecdn.net", "edge.forgecdn.net")
                and not image.username and not image.password and not image.port):
            item["image_url"] = urlunsplit((image.scheme, image.netloc, image.path, "", ""))
        if kind != "mod":
            item["environment"] = "client"
        elif server_files is not None:
            item["environment"] = "client-and-server" if filename.casefold() in server_files else "client"
        output.append(item)
    if references is not None and {(item["project_id"], item["file_id"]) for item in output} != references:
        raise ValueError("Profile is missing one or more exact files from the release manifest")
    if not output:
        raise ValueError("No supported files found")
    return sorted(output, key=lambda item: item["name"].casefold())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", type=Path, required=True, help="Local minecraftinstance.json")
    parser.add_argument("--archive", type=Path, help="Restrict to this exported CurseForge manifest")
    parser.add_argument("--server-mods", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.server_mods and not args.server_mods.is_dir():
        parser.error("--server-mods must be an existing directory")
    references = None
    if args.archive:
        with zipfile.ZipFile(args.archive) as archive:
            manifest = json.loads(archive.read("manifest.json"))
        references = {(item["projectID"], item["fileID"]) for item in manifest["files"]}
    server_files = {path.name.casefold() for path in args.server_mods.glob("*.jar")} if args.server_mods else None
    profile = json.loads(args.instance.read_text(encoding="utf-8-sig"))
    metadata = extract_metadata(profile, references, server_files)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"items": len(metadata), "output": str(args.output)}))


if __name__ == "__main__":
    main()
