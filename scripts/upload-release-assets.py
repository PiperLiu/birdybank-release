#!/usr/bin/env python3
"""Copy verified public R2 archives into an existing GitHub release.

Manual workflow helper: no builds, private R2 credentials, overwrites, or publishing.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def expected_assets(notes, version):
    names = {
        f"BirdyBank_{version}_aarch64.dmg.zip",
        f"BirdyBank_{version}_x64.dmg.zip",
        f"BirdyBank_{version}_x64-setup.exe.zip",
    }
    matches = re.findall(r"^([0-9a-f]{64})  (BirdyBank_[^\s/]+\.zip)$", notes, re.M)
    if len(matches) != 3 or {name for _, name in matches} != names:
        raise ValueError("Release notes must contain one SHA-256 for each of the three ZIPs")
    return {name: digest for digest, name in matches}


def release(version, notes, expected):
    result = subprocess.check_output(
        ["gh", "release", "view", version, "--json", "tagName,body,assets"], text=True
    )
    data = json.loads(result)
    if data["tagName"] != version or data["body"].strip() != notes.strip():
        raise ValueError("Existing release tag or notes differ from the checked-out notes")
    assets = {asset["name"]: asset for asset in data["assets"]}
    if not set(assets).issubset(expected):
        raise ValueError("Existing release contains unexpected assets; review it manually")
    for name, asset in assets.items():
        if (
            asset["state"] != "uploaded"
            or asset.get("digest") != "sha256:" + expected[name]
            or asset["size"] <= 0
        ):
            raise ValueError(f"Existing asset differs or is incomplete; refusing to overwrite: {name}")
    return assets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument("--plan", action="store_true", help="Read-only manifest and release validation")
    args = parser.parse_args()
    if not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
        raise ValueError("Expected a stable x.y.z version without a v prefix")
    if os.environ.get("GH_REPO") != "PiperLiu/birdybank-release":
        raise ValueError("GH_REPO must be PiperLiu/birdybank-release")
    root = Path(__file__).resolve().parent.parent
    notes = (root / "v0" / f"{args.version}.md").read_text(encoding="utf-8")
    expected = expected_assets(notes, args.version)
    assets = release(args.version, notes, expected)
    for name, digest in expected.items():
        if name in assets:
            print(f"Verified existing asset: {name}", flush=True)
            continue
        if args.plan:
            print(f"Missing asset to upload: {name} SHA-256 {digest}", flush=True)
            continue
        with tempfile.TemporaryDirectory(prefix="birdybank-release-") as directory:
            path = Path(directory) / name
            url = f"https://download.birdybank.top/releases/v{args.version}/{name}"
            subprocess.run(
                ["curl", "--fail", "--location", "--retry", "3", "--retry-delay", "2",
                 "--connect-timeout", "15", "--max-time", "600", "--output", str(path), url],
                check=True,
            )
            checksum = hashlib.sha256()
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    checksum.update(chunk)
            if checksum.hexdigest() != digest:
                raise ValueError(f"R2 archive SHA-256 mismatch: {name}")
            size = path.stat().st_size
            print(f"Verified R2 archive: {name} {size} bytes SHA-256 {digest}", flush=True)
            subprocess.run(["gh", "release", "upload", args.version, str(path)], check=True)
            assets = release(args.version, notes, expected)
            if assets.get(name, {}).get("size") != size:
                raise ValueError(f"Uploaded asset size differs: {name}")
    if not args.plan and set(release(args.version, notes, expected)) != set(expected):
        raise ValueError("The release is still missing assets")
    print("Plan verified." if args.plan else "All three release assets verified. Release visibility unchanged.", flush=True)


if __name__ == "__main__":
    main()
