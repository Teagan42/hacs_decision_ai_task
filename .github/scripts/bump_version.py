"""Bump the integration's manifest version and print the new version.

Usage: bump_version.py {major,minor,patch}
"""

import json
from pathlib import Path
import sys

MANIFEST = Path("custom_components/decision_ai_task/manifest.json")


def main() -> None:
    part = sys.argv[1]
    manifest = json.loads(MANIFEST.read_text())
    major, minor, patch = (int(n) for n in manifest["version"].split("."))
    if part == "major":
        major, minor, patch = major + 1, 0, 0
    elif part == "minor":
        minor, patch = minor + 1, 0
    elif part == "patch":
        patch += 1
    else:
        sys.exit(f"unknown bump {part!r}")
    manifest["version"] = f"{major}.{minor}.{patch}"
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    print(manifest["version"])


if __name__ == "__main__":
    main()
