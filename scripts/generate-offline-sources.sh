#!/bin/bash
# ╔══════════════════════════════════════════════════════════════╗
# ║  Ark — Configure a target machine to use the offline repo   ║
# ╚══════════════════════════════════════════════════════════════╝
#
# Run this ON THE TARGET MACHINE after mounting the Ark drive.
# It configures APT to use the offline repository.
#
# Usage:
#   sudo ./generate-offline-sources.sh /mnt/ark
#
# What it does:
#   1. Detects available distributions in the repo
#   2. Imports the repo signing key (if present)
#   3. Creates /etc/apt/sources.list.d/ark-offline.list
#   4. Runs apt-get update
#
# To revert:
#   sudo rm /etc/apt/sources.list.d/ark-offline.list
#   sudo rm -f /etc/apt/trusted.gpg.d/ark-offline.gpg
#   sudo apt-get update

set -euo pipefail

REPO_PATH="${1:-}"

if [ -z "$REPO_PATH" ]; then
    echo "Usage: $0 /path/to/mounted/ark"
    echo ""
    echo "Mount the Ark drive first, then point this script at it."
    exit 1
fi

if [ "$(id -u)" -ne 0 ]; then
    echo "Error: must run as root (sudo)"
    exit 1
fi

APT_REPO="$REPO_PATH/apt-repo"

if [ ! -d "$APT_REPO/dists" ]; then
    echo "Error: $APT_REPO/dists not found."
    echo "This doesn't look like an Ark repository."
    echo "Check that the drive is mounted at $REPO_PATH."
    exit 1
fi

echo "Ark Offline Repository Setup"
echo "============================="
echo "Repo path: $APT_REPO"
echo ""

# ── Detect this machine's codename ────────────────────────────
CODENAME=$(lsb_release -cs 2>/dev/null || echo "unknown")
echo "This machine: $(lsb_release -ds 2>/dev/null || echo 'unknown') ($CODENAME)"

# ── Import GPG key ────────────────────────────────────────────
if [ -f "$APT_REPO/repo-key.gpg" ]; then
    cp "$APT_REPO/repo-key.gpg" /etc/apt/trusted.gpg.d/ark-offline.gpg
    echo "✓ Imported repo signing key"
    SIGNED="signed-by=/etc/apt/trusted.gpg.d/ark-offline.gpg"
else
    echo "  No signing key found — using [trusted=yes]"
    SIGNED="trusted=yes"
fi

# ── Generate sources.list entries ─────────────────────────────
SOURCES_FILE="/etc/apt/sources.list.d/ark-offline.list"
echo "# Ark offline repository" > "$SOURCES_FILE"
echo "# Generated: $(date -Iseconds)" >> "$SOURCES_FILE"
echo "" >> "$SOURCES_FILE"

FOUND=0
for dist_dir in "$APT_REPO"/dists/*/; do
    if [ ! -d "$dist_dir" ]; then
        continue
    fi

    dist_codename=$(basename "$dist_dir")
    echo "deb [$SIGNED] file://$APT_REPO $dist_codename main" >> "$SOURCES_FILE"
    echo "✓ Added distribution: $dist_codename"
    FOUND=$((FOUND + 1))

    if [ "$dist_codename" = "$CODENAME" ]; then
        echo "  ↑ Matches this machine!"
    fi
done

if [ "$FOUND" -eq 0 ]; then
    echo "Error: no distributions found in $APT_REPO/dists/"
    rm -f "$SOURCES_FILE"
    exit 1
fi

echo ""
echo "Sources file: $SOURCES_FILE"
echo ""

# ── Update APT cache ──────────────────────────────────────────
echo "Updating apt cache..."
apt-get update

echo ""
echo "============================="
echo "Done! You can now install packages offline:"
echo "  apt-get install <package>"
echo ""
echo "Standalone toolchains are in: $REPO_PATH/toolchains/"
echo "  Rust:    tar xf rust-*.tar.xz && ./install.sh"
echo "  Go:      tar xf go*.tar.gz -C /usr/local"
echo "  Node.js: tar xf node-*.tar.xz -C /usr/local --strip-components=1"
echo "  Zig:     tar xf zig-*.tar.xz (runs from extracted dir)"
echo ""
echo "Python wheels are in: $REPO_PATH/pip-cache/"
echo "  pip install --no-index --find-links=$REPO_PATH/pip-cache/full <package>"
echo ""
echo "To revert: sudo rm $SOURCES_FILE && sudo apt-get update"
