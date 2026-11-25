#!/usr/bin/env python3 -I
"""
Verify APT package integrity against upstream Packages manifests.

The trust chain for Debian/Ubuntu packages:
  1. Release file — GPG signed by the distro
  2. Packages file — SHA256 listed in Release
  3. Individual .debs — SHA256 listed in Packages

This script verifies steps 2 and 3: it parses the Packages file for
expected hashes, then checks every .deb in the staging directory
against those hashes. Any mismatch means the package was tampered
with or corrupted in transit.

Usage:
    ./verify_packages.py \\
        --staging-dir /mnt/ark/.staging/debs/noble-amd64 \\
        --packages-file /var/lib/apt/lists/*noble*Packages \\
        --report /mnt/ark/manifests/scan-noble-amd64.json
"""

import argparse
import gzip
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(filepath, chunk_size=65536):
    """Compute SHA256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def parse_packages_file(packages_path):
    """
    Parse an APT Packages file and extract filename → sha256 mapping.
    Handles both plain text and gzipped Packages files.
    """
    hashes = {}

    if packages_path.endswith(".gz"):
        opener = gzip.open
    else:
        opener = open

    current_filename = None
    current_sha256 = None
    current_package = None
    current_version = None

    with opener(packages_path, "rt", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")

            if line.startswith("Package: "):
                current_package = line[9:]
            elif line.startswith("Version: "):
                current_version = line[9:]
            elif line.startswith("Filename: "):
                # Filename is relative to repo root, e.g. pool/main/v/vim/vim_9.1.0-1_amd64.deb
                current_filename = line[10:]
            elif line.startswith("SHA256: "):
                current_sha256 = line[8:]
            elif line == "":
                # End of stanza — record the entry
                if current_filename and current_sha256:
                    # Key by just the .deb filename (basename)
                    basename = os.path.basename(current_filename)
                    hashes[basename] = {
                        "sha256": current_sha256,
                        "package": current_package,
                        "version": current_version,
                        "repo_path": current_filename,
                    }
                current_filename = None
                current_sha256 = None
                current_package = None
                current_version = None

    # Handle last stanza if file doesn't end with blank line
    if current_filename and current_sha256:
        basename = os.path.basename(current_filename)
        hashes[basename] = {
            "sha256": current_sha256,
            "package": current_package,
            "version": current_version,
            "repo_path": current_filename,
        }

    return hashes


def find_packages_files(apt_lists_dir="/var/lib/apt/lists", codename=None):
    """
    Find relevant Packages files in the APT lists directory.
    Returns a list of paths.
    """
    packages_files = []
    lists_dir = Path(apt_lists_dir)

    if not lists_dir.exists():
        return packages_files

    for f in sorted(lists_dir.iterdir()):
        name = f.name
        if "Packages" not in name:
            continue
        if codename and codename not in name:
            continue
        packages_files.append(str(f))

    return packages_files


def verify_staging_dir(staging_dir, expected_hashes, verbose=False):
    """
    Verify every .deb in the staging directory against expected hashes.

    Returns:
        (verified, unverified, mismatched, results_list)
    """
    staging = Path(staging_dir)
    verified = 0
    unverified = 0
    mismatched = 0
    results = []

    debs = sorted(staging.glob("*.deb"))
    total = len(debs)

    for i, deb in enumerate(debs):
        basename = deb.name
        actual_sha256 = sha256_file(deb)

        if basename in expected_hashes:
            expected = expected_hashes[basename]["sha256"]
            if actual_sha256 == expected:
                status = "VERIFIED"
                verified += 1
            else:
                status = "MISMATCH"
                mismatched += 1
                if verbose:
                    print(f"  MISMATCH: {basename}", file=sys.stderr)
                    print(f"    expected: {expected}", file=sys.stderr)
                    print(f"    actual:   {actual_sha256}", file=sys.stderr)
        else:
            # Package not in any Packages file — can't verify
            status = "UNVERIFIED"
            unverified += 1
            if verbose:
                print(f"  UNVERIFIED: {basename} (not in Packages manifest)",
                      file=sys.stderr)

        results.append({
            "file": basename,
            "status": status,
            "sha256": actual_sha256,
            "expected_sha256": expected_hashes.get(basename, {}).get("sha256"),
            "package": expected_hashes.get(basename, {}).get("package"),
        })

        # Progress
        if (i + 1) % 100 == 0 or (i + 1) == total:
            pct = int((i + 1) / total * 100)
            print(f"\r  Verified: {i + 1}/{total} ({pct}%)", end="", flush=True)

    print()  # newline after progress
    return verified, unverified, mismatched, results


def main():
    parser = argparse.ArgumentParser(
        description="Verify APT package integrity against upstream manifests"
    )
    parser.add_argument(
        "--staging-dir", required=True,
        help="Directory containing .deb files to verify",
    )
    parser.add_argument(
        "--packages-file", action="append",
        help="Path to an APT Packages file (can specify multiple)",
    )
    parser.add_argument(
        "--codename",
        help="Distribution codename to filter Packages files (e.g., noble)",
    )
    parser.add_argument(
        "--report", required=True,
        help="Path to write the verification report JSON",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
    )

    args = parser.parse_args()

    print(f"{'=' * 60}")
    print(f"  Ark Package Integrity Verifier")
    print(f"  Staging dir: {args.staging_dir}")
    print(f"{'=' * 60}")

    # Collect expected hashes from Packages files
    expected_hashes = {}

    if args.packages_file:
        packages_files = args.packages_file
    else:
        # Auto-discover from APT lists
        packages_files = find_packages_files(codename=args.codename)

    if not packages_files:
        print("  Warning: no Packages files found. Cannot verify hashes.",
              file=sys.stderr)
        print("  Run 'apt-get update' on the build host to fetch Packages manifests.",
              file=sys.stderr)

    for pf in packages_files:
        print(f"\n  Parsing: {os.path.basename(pf)}")
        hashes = parse_packages_file(pf)
        expected_hashes.update(hashes)
        print(f"    {len(hashes)} package hashes loaded")

    print(f"\n  Total known hashes: {len(expected_hashes)}")

    # Verify
    print(f"\n  Checking .debs in {args.staging_dir}...")
    verified, unverified, mismatched, results = verify_staging_dir(
        args.staging_dir, expected_hashes, verbose=args.verbose
    )

    # Build report
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "staging_dir": args.staging_dir,
        "packages_files_used": packages_files,
        "total_checked": len(results),
        "verified": verified,
        "unverified": unverified,
        "mismatched": mismatched,
        "passed": mismatched == 0,
        "mismatched_files": [
            r for r in results if r["status"] == "MISMATCH"
        ],
        "unverified_files": [
            r["file"] for r in results if r["status"] == "UNVERIFIED"
        ],
    }

    # Write report
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    # Summary
    print(f"\n{'=' * 60}")
    print(f"  Results:")
    print(f"    Verified (hash match):   {verified}")
    print(f"    Unverified (no ref):     {unverified}")
    print(f"    MISMATCHED (TAMPERED?):  {mismatched}")
    print(f"  Overall: {'PASS' if mismatched == 0 else '*** FAIL — POSSIBLE TAMPERING ***'}")
    print(f"  Report:  {args.report}")
    print(f"{'=' * 60}")

    return 0 if mismatched == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
