"""Publish a validated local CurseForge ZIP to the private catalog/public snapshot."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))
from pack_catalog import CatalogError, publish_release


def read_metadata(path):
    if path.stat().st_size > 4 * 1024 * 1024:
        raise CatalogError("Metadata JSON exceeds the size limit")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-dir", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--docs-dir", type=Path, default=ROOT / "docs")
    parser.add_argument("--summary")
    args = parser.parse_args()
    try:
        result = publish_release(args.private_dir, args.archive, read_metadata(args.metadata), args.docs_dir,
                                 baseline=read_metadata(args.baseline) if args.baseline else None,
                                 summary=args.summary)
    except CatalogError as error:
        print("Udgivelsen blev afvist: " + str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError, sqlite3.Error):
        print("Udgivelsen kunne ikke gemmes. Kontrollér de angivne filer og mapper; ingen private data udskrives.", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
