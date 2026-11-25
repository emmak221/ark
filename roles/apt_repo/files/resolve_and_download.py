#!/usr/bin/env python3 -I
"""
Resolve APT package dependencies and download .deb files for offline repo.

Recursively resolves all hard dependencies (Depends, Pre-Depends) for a
list of packages, then downloads the full set using apt-get. Handles
cross-architecture downloads when the host is configured for multi-arch.

Usage:
    ./resolve_and_download.py \\
        --packages-file packages.txt \\
        --output-dir /mnt/ark/.staging/debs/noble-amd64 \\
        --arch amd64 \\
        --manifest /mnt/ark/manifests/noble-amd64.json

Requirements:
    - Must run on a Debian/Ubuntu host (needs apt-cache, apt-get)
    - Target architecture must be enabled: dpkg --add-architecture arm64
    - Package lists must be up to date: apt-get update
"""

import argparse
import json
import os
import subprocess
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path


def apt_cache_depends(package, arch=None):
    """
    Get direct hard dependencies of a package using apt-cache.
    Returns (resolved_name, [dep_names]) or (None, []) if not found.
    """
    pkg_spec = f"{package}:{arch}" if arch and ":" not in package else package

    result = subprocess.run(
        ["apt-cache", "depends", "--important", "--no-recommends",
         "--no-suggests", "--no-conflicts", "--no-breaks",
         "--no-replaces", "--no-enhances", pkg_spec],
        capture_output=True, text=True, timeout=30,
    )

    if result.returncode != 0:
        return None, []

    deps = []
    for line in result.stdout.splitlines():
        stripped = line.strip()

        # Match hard dependencies: "Depends: name" or "PreDepends: name"
        for prefix in ("Depends: ", "PreDepends: "):
            if stripped.startswith(prefix):
                dep_name = stripped[len(prefix):]
                # Skip virtual packages (angle-bracket names)
                if not dep_name.startswith("<"):
                    deps.append(dep_name)
                break

        # Alternatives: "|Depends: name" — take first concrete option
        for prefix in ("|Depends: ", "|PreDepends: "):
            if stripped.startswith(prefix):
                dep_name = stripped[len(prefix):]
                if not dep_name.startswith("<"):
                    deps.append(dep_name)
                break

    return pkg_spec, deps


def resolve_all_dependencies(packages, arch=None, verbose=False):
    """
    Recursively resolve all dependencies for a list of packages.

    Returns:
        (resolved_set, not_found_list)
    """
    resolved = set()
    not_found = []
    queue = deque(packages)
    seen = set()

    while queue:
        pkg = queue.popleft()

        # Normalize: strip arch qualifier for dedup tracking
        base_name = pkg.split(":")[0] if ":" in pkg else pkg
        if base_name in seen:
            continue
        seen.add(base_name)

        _, deps = apt_cache_depends(pkg, arch)
        if _ is None:
            not_found.append(pkg)
            if verbose:
                print(f"  [MISS] {pkg}", file=sys.stderr)
            continue

        resolved.add(base_name)

        for dep in deps:
            dep_base = dep.split(":")[0] if ":" in dep else dep
            if dep_base not in seen:
                queue.append(dep)

    return resolved, not_found


def download_packages(packages, output_dir, arch=None, verbose=False):
    """
    Download .deb files for a set of packages using apt-get download.

    Returns:
        (downloaded_count, failed_list, skipped_count)
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build list of already-present package basenames
    existing_debs = set()
    for f in output_dir.glob("*.deb"):
        # .deb filenames: name_version_arch.deb
        parts = f.name.split("_")
        if parts:
            existing_debs.add(parts[0])

    to_download = sorted(packages)

    # When downloading for a foreign arch (e.g. arm64 on an amd64 host),
    # we need to handle Architecture: all packages specially — they can't
    # be downloaded with an :arch qualifier. Check each package's arch
    # and only qualify the ones that are arch-specific.
    arch_qualified = []
    arch_all_packages = []

    if arch:
        for pkg in to_download:
            if ":" in pkg:
                arch_qualified.append(pkg)
                continue
            # Check if this package is Architecture: all
            result = subprocess.run(
                ["apt-cache", "show", pkg],
                capture_output=True, text=True, timeout=10,
            )
            is_all = False
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if line.startswith("Architecture:"):
                        if "all" in line:
                            is_all = True
                        break
            if is_all:
                arch_all_packages.append(pkg)
            else:
                arch_qualified.append(f"{pkg}:{arch}")

        to_download_final = arch_qualified + arch_all_packages
        print(f"  ({len(arch_qualified)} arch-specific + "
              f"{len(arch_all_packages)} arch:all packages)")
    else:
        to_download_final = to_download

    failed = []
    downloaded = 0
    total = len(to_download_final)

    # Download in batches — apt-get download can handle multiple at once
    # but can fail the whole batch on one missing package
    batch_size = 30

    for i in range(0, total, batch_size):
        batch = to_download_final[i : i + batch_size]

        result = subprocess.run(
            ["apt-get", "download"] + batch,
            capture_output=True,
            text=True,
            cwd=str(output_dir),
            timeout=600,
        )

        if result.returncode == 0:
            downloaded += len(batch)
        else:
            # Batch failed — retry individually to isolate failures
            for pkg in batch:
                r = subprocess.run(
                    ["apt-get", "download", pkg],
                    capture_output=True,
                    text=True,
                    cwd=str(output_dir),
                    timeout=120,
                )
                if r.returncode == 0:
                    downloaded += 1
                else:
                    failed.append(pkg)
                    if verbose:
                        print(f"  [FAIL] {pkg}: {r.stderr.strip()}", file=sys.stderr)

        # Progress indicator
        done = min(i + batch_size, total)
        pct = int(done / total * 100) if total > 0 else 100
        print(f"\r  Downloading: {done}/{total} ({pct}%)", end="", flush=True)

    print()  # newline after progress
    return downloaded, failed


def count_debs(directory):
    """Count .deb files in a directory."""
    return len(list(Path(directory).glob("*.deb")))


def total_size_mb(directory):
    """Get total size of .deb files in MB."""
    total = sum(f.stat().st_size for f in Path(directory).glob("*.deb"))
    return round(total / (1024 * 1024), 1)


def main():
    parser = argparse.ArgumentParser(
        description="Resolve and download APT packages with all dependencies"
    )
    parser.add_argument(
        "--packages", nargs="+",
        help="Package names to resolve",
    )
    parser.add_argument(
        "--packages-file",
        help="File containing package names, one per line (# comments ok)",
    )
    parser.add_argument(
        "--output-dir", required=True,
        help="Directory to download .deb files into",
    )
    parser.add_argument(
        "--arch",
        help="Target architecture (amd64, arm64). Omit for native.",
    )
    parser.add_argument(
        "--manifest",
        help="Write a JSON manifest of resolved packages to this path",
    )
    parser.add_argument(
        "--resolve-only", action="store_true",
        help="Only resolve dependencies, don't download",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print detailed progress",
    )

    args = parser.parse_args()

    # ── Collect package names ──────────────────────────────────
    packages = set()
    if args.packages:
        packages.update(args.packages)
    if args.packages_file:
        with open(args.packages_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    # Strip inline comments
                    line = line.split("#")[0].strip()
                    if line:
                        packages.add(line)

    if not packages:
        print("Error: no packages specified. Use --packages or --packages-file.",
              file=sys.stderr)
        sys.exit(1)

    arch_label = args.arch or "native"
    print(f"{'=' * 60}")
    print(f"  Ark Package Resolver")
    print(f"  Requested packages:  {len(packages)}")
    print(f"  Target architecture: {arch_label}")
    print(f"  Output directory:    {args.output_dir}")
    print(f"{'=' * 60}")

    # ── Resolve dependencies ───────────────────────────────────
    print(f"\nResolving dependencies...")
    t0 = time.time()
    resolved, not_found = resolve_all_dependencies(
        packages, args.arch, verbose=args.verbose
    )
    elapsed = time.time() - t0

    print(f"  Resolved {len(resolved)} total packages "
          f"(from {len(packages)} requested) in {elapsed:.1f}s")

    if not_found:
        print(f"\n  WARNING: {len(not_found)} packages not found in apt-cache:")
        for p in sorted(not_found)[:20]:
            print(f"    - {p}")
        if len(not_found) > 20:
            print(f"    ... and {len(not_found) - 20} more")

    if args.resolve_only:
        # Print the resolved list and exit
        for p in sorted(resolved):
            print(p)
        sys.exit(0)

    # ── Download ───────────────────────────────────────────────
    print(f"\nDownloading {len(resolved)} packages...")
    t0 = time.time()
    downloaded, failed = download_packages(
        resolved, args.output_dir, args.arch, verbose=args.verbose
    )
    elapsed = time.time() - t0

    deb_count = count_debs(args.output_dir)
    size_mb = total_size_mb(args.output_dir)

    print(f"  Downloaded: {downloaded} new packages in {elapsed:.1f}s")
    print(f"  Failed:     {len(failed)}")
    print(f"  Pool total: {deb_count} .deb files, {size_mb} MB")

    if failed:
        print(f"\n  Failed packages:")
        for p in sorted(failed):
            print(f"    - {p}")

    # ── Write manifest ─────────────────────────────────────────
    if args.manifest:
        manifest_path = Path(args.manifest)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "architecture": arch_label,
            "requested_packages": sorted(packages),
            "resolved_packages": sorted(resolved),
            "not_found": sorted(not_found),
            "failed_downloads": [p.split(":")[0] for p in sorted(failed)],
            "total_resolved": len(resolved),
            "total_downloaded": downloaded,
            "total_debs_in_pool": deb_count,
            "pool_size_mb": size_mb,
        }
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)
        print(f"\n  Manifest: {args.manifest}")

    print(f"\n{'=' * 60}")
    if failed:
        print("  Completed with errors. Review failed packages above.")
        return 1
    else:
        print("  Complete. All packages resolved and downloaded.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
