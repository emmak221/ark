#!/usr/bin/env python3 -I
"""
Generate a manifest of everything currently on the Ark.

Walks the storage directory and records every file with its name,
size, and SHA256 hash. The manifest is used by the download step
to diff against what's available upstream — only fetching what's
new or updated.

Usage:
    ./generate_manifest.py --storage-root /mnt/ark --output /mnt/ark/manifests/ark-manifest.json
"""

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(filepath, chunk_size=65536):
    """Compute SHA256 hash of a file."""
    h = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
    except (OSError, PermissionError) as e:
        print(f"  Warning: could not hash {filepath}: {e}", file=sys.stderr)
        return None
    return h.hexdigest()


def inventory_directory(base_path, extensions=None, compute_hashes=True):
    """
    Walk a directory and inventory all files.
    Returns a dict of {relative_path: {size, sha256, mtime}}.
    """
    inventory = {}
    base = Path(base_path)

    if not base.exists():
        return inventory

    for filepath in sorted(base.rglob("*")):
        if not filepath.is_file():
            continue

        # Filter by extension if specified
        if extensions:
            if not any(filepath.name.endswith(ext) for ext in extensions):
                continue

        rel_path = str(filepath.relative_to(base))
        stat = filepath.stat()

        entry = {
            "size": stat.st_size,
            "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        }

        if compute_hashes:
            sha = sha256_file(filepath)
            if sha:
                entry["sha256"] = sha

        inventory[rel_path] = entry

    return inventory


def inventory_debs(staging_dir):
    """
    Inventory .deb files in the staging directory.
    Returns a dict keyed by distro-arch/filename.
    """
    inventory = {}
    base = Path(staging_dir)

    if not base.exists():
        return inventory

    for pool_dir in sorted(base.iterdir()):
        if not pool_dir.is_dir():
            continue

        pool_name = pool_dir.name  # e.g., noble-amd64

        for deb in sorted(pool_dir.glob("*.deb")):
            key = f"{pool_name}/{deb.name}"

            # Parse package name and version from filename
            # Format: name_version_arch.deb
            parts = deb.name.rsplit("_", 2)
            pkg_name = parts[0] if len(parts) >= 1 else deb.name
            pkg_version = parts[1] if len(parts) >= 2 else "unknown"
            pkg_arch = parts[2].replace(".deb", "") if len(parts) >= 3 else "unknown"

            stat = deb.stat()
            inventory[key] = {
                "package": pkg_name,
                "version": pkg_version,
                "arch": pkg_arch,
                "size": stat.st_size,
                "sha256": sha256_file(deb),
            }

    return inventory


def main():
    parser = argparse.ArgumentParser(
        description="Generate inventory manifest of the Ark"
    )
    parser.add_argument(
        "--storage-root", required=True,
        help="Root of the Ark storage (e.g., /mnt/ark)",
    )
    parser.add_argument(
        "--output", required=True,
        help="Path to write the manifest JSON",
    )
    parser.add_argument(
        "--skip-hashes", action="store_true",
        help="Skip SHA256 computation (much faster, less secure)",
    )
    parser.add_argument(
        "--staging-only", action="store_true",
        help="Only inventory the staging directory (for pre-scan manifest)",
    )

    args = parser.parse_args()
    root = Path(args.storage_root)
    compute_hashes = not args.skip_hashes

    print(f"{'=' * 60}")
    print(f"  Ark Manifest Generator")
    print(f"  Storage root: {root}")
    print(f"  Hashing:      {'yes' if compute_hashes else 'no (fast mode)'}")
    print(f"{'=' * 60}")

    manifest = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "storage_root": str(root),
    }

    if args.staging_only:
        # Only inventory staging — used before scanning
        staging_dir = root / ".staging" / "debs"
        print(f"\nInventorying staging debs...")
        t0 = time.time()
        manifest["staging_packages"] = inventory_debs(staging_dir)
        elapsed = time.time() - t0
        count = len(manifest["staging_packages"])
        print(f"  {count} packages in {elapsed:.1f}s")

    else:
        # Full inventory
        # ISOs
        iso_dir = root / "isos"
        print(f"\nInventorying ISOs...")
        t0 = time.time()
        manifest["isos"] = inventory_directory(
            iso_dir,
            extensions=[".iso", ".img", ".img.xz", ".img.gz"],
            compute_hashes=compute_hashes,
        )
        elapsed = time.time() - t0
        print(f"  {len(manifest['isos'])} files in {elapsed:.1f}s")

        # APT repo (the live repo, not staging)
        # We inventory the pool directory for the actual .debs
        pool_dir = root / "apt-repo" / "pool"
        print(f"\nInventorying APT repo pool...")
        t0 = time.time()
        manifest["apt_packages"] = inventory_directory(
            pool_dir,
            extensions=[".deb"],
            compute_hashes=compute_hashes,
        )
        elapsed = time.time() - t0
        print(f"  {len(manifest['apt_packages'])} packages in {elapsed:.1f}s")

        # Staging area (packages downloaded but not yet promoted)
        staging_dir = root / ".staging" / "debs"
        print(f"\nInventorying staging area...")
        t0 = time.time()
        manifest["staging_packages"] = inventory_debs(staging_dir)
        elapsed = time.time() - t0
        print(f"  {len(manifest['staging_packages'])} packages in {elapsed:.1f}s")

        # Toolchains
        tc_dir = root / "toolchains"
        print(f"\nInventorying toolchains...")
        t0 = time.time()
        manifest["toolchains"] = inventory_directory(
            tc_dir,
            extensions=[".tar.gz", ".tar.xz"],
            compute_hashes=compute_hashes,
        )
        elapsed = time.time() - t0
        print(f"  {len(manifest['toolchains'])} archives in {elapsed:.1f}s")

        # Pip cache
        pip_dir = root / "pip-cache"
        print(f"\nInventorying pip cache...")
        t0 = time.time()
        manifest["pip_cache"] = inventory_directory(
            pip_dir,
            extensions=[".whl", ".tar.gz", ".zip"],
            compute_hashes=compute_hashes,
        )
        elapsed = time.time() - t0
        print(f"  {len(manifest['pip_cache'])} files in {elapsed:.1f}s")

    # Summary
    total_files = sum(
        len(v) for k, v in manifest.items()
        if isinstance(v, dict) and k != "generated" and k != "storage_root"
    )

    manifest["total_files"] = total_files

    # Write manifest
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\n{'=' * 60}")
    print(f"  Manifest written: {args.output}")
    print(f"  Total files:      {total_files}")
    print(f"{'=' * 60}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
