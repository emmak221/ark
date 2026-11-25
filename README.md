# Ark — Offline Linux Repository

An Ansible-managed offline collection of Linux ISOs, APT packages, language toolchains, and Python wheels. Designed for air-gapped environments, disaster recovery, or any situation where you need to install and configure Linux systems with no internet connection.

Store it on an external SSD, update it quarterly, and you have everything needed to go from bare metal to a fully configured workstation or server — entirely offline.

---

## What's In It

**Operating System ISOs** — Ubuntu 24.04 LTS (desktop + server, amd64 and arm64), Linux Mint 22.3, Debian 13 Trixie (amd64 + arm64), Debian 12 Bookworm (archived), Raspberry Pi OS (Trixie, desktop + lite), SystemRescue, Clonezilla, OpenWrt

**APT Package Repository** — ~350 curated top-level packages that resolve to ~5,200 total packages (with dependencies) per distribution. Covers desktop environments (XFCE + GNOME), productivity (LibreOffice, GIMP, Inkscape, Blender, Kdenlive, Audacity, OBS), development toolchains (GCC, Clang, Python, Java, Lua, Perl, Ruby, PHP, R), networking (OpenSSH, WireGuard, dnsmasq, nginx, Wireshark), security/auditing tools (nmap, aircrack-ng, John, Hashcat, ClamAV, fail2ban), system utilities (tmux, Neovim, Docker, Podman, Ansible), virtualization (QEMU, libvirt), firmware, fonts, and common build libraries. Built for both amd64 and arm64.

**Standalone Toolchains** — Rust, Go, Node.js, and Zig as self-contained tarballs for x86_64 and aarch64. No package manager needed to install them.

**Python Wheel Cache** — ~200 pre-downloaded wheels covering scientific computing, web frameworks, security tools, and dev utilities. Source distributions included as a fallback.

---

## Requirements

| Requirement | Details |
|---|---|
| **Build host** | Debian or Ubuntu (needs APT tools for dependency resolution). Can be a VM or container if your daily driver is something else. |
| **Ansible** | 2.14 or newer on the build host |
| **Storage** | 500 GB minimum, 1+ TB recommended. External SSD or NVMe in an enclosure works well. |
| **Internet** | Required only during sync. The entire point is that everything works offline afterward. |

---

## Quick Start

### 1. First-Time Setup

Clone or extract the Ark project onto your build host:

```bash
cd ~/ark
```

If your storage drive is a removable disk, mount it:

```bash
sudo mkdir -p /mnt/ark
sudo mount /dev/sdX1 /mnt/ark
```

Or, to download to a local directory first and transfer later:

```bash
mkdir -p ~/ark-backup
```

### 2. Initial Download (Full Sync)

```bash
# To a mounted drive:
sudo ansible-playbook playbooks/full-sync.yml

# To a local directory:
sudo ansible-playbook playbooks/full-sync.yml -e "ark_storage_root=/home/youruser/ark-backup"
```

This downloads everything from scratch. Expect 2-6 hours and ~50-80 GB depending on your bandwidth.

You can monitor ISO download progress from another terminal:

```bash
tail -f /tmp/ark-iso-download.log
```

And watch APT package downloads:

```bash
watch -n 10 'for d in /path/to/ark-backup/.staging/debs/*/; do
  echo "$(basename $d): $(ls "$d"/*.deb 2>/dev/null | wc -l) debs"
done'
```

### 3. Quarterly Update

Before updating, review and bump version numbers as needed:

- `inventory/group_vars/all/isos.yml` — ISO versions and URLs
- `inventory/group_vars/all/toolchains.yml` — Rust/Go/Node/Zig version numbers
- `inventory/group_vars/all/packages.yml` — add or remove APT packages

Then run:

```bash
sudo ansible-playbook playbooks/update.yml -e "ark_storage_root=/path/to/ark"
```

This is incremental — only new/changed packages and ISOs are downloaded.

### 4. Verify Integrity

```bash
sudo ansible-playbook playbooks/verify.yml -e "ark_storage_root=/path/to/ark"
```

Read-only. Checks ISO checksums, APT repo integrity, toolchain archive validity, and reports totals.

### 5. Run Specific Components

Use `--tags` to run only part of the sync:

```bash
# Just re-download ISOs:
sudo ansible-playbook playbooks/update.yml --tags isos -e "ark_storage_root=/path/to/ark"

# Just re-resolve and download APT packages:
sudo ansible-playbook playbooks/update.yml --tags apt -e "ark_storage_root=/path/to/ark"

# Just update toolchains:
sudo ansible-playbook playbooks/update.yml --tags toolchains -e "ark_storage_root=/path/to/ark"

# Just update Python wheels:
sudo ansible-playbook playbooks/update.yml --tags pip -e "ark_storage_root=/path/to/ark"
```

---

## Using the Ark Offline

When the internet is gone and you need to get machines running, here's how to use each component.

### Installing an OS

1. Plug in the Ark drive and mount it
2. Find the ISO you need in the `isos/` directory
3. Write it to a USB stick:

```bash
# For ISO files:
sudo dd if=/mnt/ark/isos/ubuntu-server-amd64/ubuntu-24.04.5-live-server-amd64.iso \
       of=/dev/sdX bs=4M status=progress

# For .img.xz files (Raspberry Pi):
xzcat /mnt/ark/isos/raspios-lite-arm64/2026-04-21-raspios-trixie-arm64-lite.img.xz \
  | sudo dd of=/dev/sdX bs=4M status=progress
```

4. Boot from the USB stick and install normally

### Setting Up the Offline APT Repository

After installing the OS, mount the Ark drive and run the setup script:

```bash
# Mount the Ark drive
sudo mkdir -p /mnt/ark
sudo mount /dev/sdX1 /mnt/ark

# Configure APT to use the offline repo
sudo /mnt/ark/scripts/generate-offline-sources.sh /mnt/ark
```

This creates `/etc/apt/sources.list.d/ark-offline.list` and imports the repo signing key (if present). Now you can install packages offline just like you normally would:

```bash
sudo apt-get update
sudo apt-get install tmux neovim git build-essential
sudo apt-get install xfce4 lightdm        # install a desktop environment
sudo apt-get install nginx openssh-server  # set up services
sudo apt-get install nmap wireshark tcpdump # network tools
```

Everything in the curated package list and all their dependencies are available. Use `apt-cache search <keyword>` to browse what's in the repo.

To remove the offline source later (once internet returns):

```bash
sudo rm /etc/apt/sources.list.d/ark-offline.list
sudo apt-get update
```

### Installing Standalone Toolchains

These don't need APT — they're self-contained tarballs:

```bash
ARK=/mnt/ark  # wherever you mounted the drive

# ── Rust ──
cd /tmp
tar xf $ARK/toolchains/rust/rust-*-x86_64-unknown-linux-gnu.tar.xz
cd rust-*
sudo ./install.sh
rustc --version

# ── Go ──
sudo tar xf $ARK/toolchains/go/go*linux-amd64.tar.gz -C /usr/local
export PATH=$PATH:/usr/local/go/bin
go version

# ── Node.js ──
sudo tar xf $ARK/toolchains/node/node-*-linux-x64.tar.xz \
  -C /usr/local --strip-components=1
node --version

# ── Zig ── (runs from the extracted directory)
mkdir -p ~/zig
tar xf $ARK/toolchains/zig/zig-linux-x86_64-*.tar.xz -C ~/zig --strip-components=1
export PATH=$PATH:~/zig
zig version
```

For ARM64 machines, use the `aarch64` / `linux-arm64` tarballs instead.

### Installing Python Packages Offline

```bash
# Install from the wheel cache:
pip install --no-index --find-links=/mnt/ark/pip-cache/full numpy pandas flask

# If a binary wheel isn't available, fall back to source distributions
# (requires build tools — install build-essential from APT first):
pip install --no-index --find-links=/mnt/ark/pip-cache/sdist <package>
```

### Flashing OpenWrt

```bash
gunzip -c /mnt/ark/isos/openwrt-x86-64/openwrt-25.12.5-x86-64-generic-ext4-combined.img.gz \
  | sudo dd of=/dev/sdX bs=4M status=progress
```

For specific router hardware, add your router's firmware image to `isos.yml` using the [OpenWrt firmware selector](https://firmware-selector.openwrt.org).

---

## Quarantine Workflow (Data Fortress Mode)

For maximum security, use the three-phase quarantine workflow instead of the quick-path playbooks. This ensures no compromised package ever reaches the Ark.

### Overview

```
  Phase 1: DOWNLOAD          Phase 2: SCAN           Phase 3: PROMOTE
  (internet connected)       (airgapped)             (Ark storage only)
  ┌─────────────────┐       ┌─────────────────┐     ┌─────────────────┐
  │ download.yml    │       │ scan.yml        │     │ promote.yml     │
  │                 │       │                 │     │                 │
  │ • Fetch ISOs    │       │ • ClamAV scan   │     │ • Import .debs  │
  │ • Resolve deps  │  ──►  │ • GPG verify    │ ──► │ • Update repo   │
  │ • Download .debs│  1-2  │ • Hash check    │     │ • Gen manifest  │
  │ • Toolchains    │ weeks │ • Scan report   │     │ • Verify        │
  │ • Pip wheels    │       │                 │     │                 │
  └─────────────────┘       └─────────────────┘     └─────────────────┘
   then disconnect            freshclam first         Ark drive only
```

### Phase 1 — Download (internet connected)

```bash
sudo ansible-playbook playbooks/download.yml -e "ark_storage_root=/path/to/staging"
```

Downloads everything to the staging area. When done, **disconnect from the internet**.

### Quarantine Period (1-2 weeks)

The staged downloads sit untouched. During this window, the security community discovers and publishes signatures for any active supply chain attacks. This is the defense against novel zero-day compromises — by the time you scan, ClamAV's definitions will have caught up.

### Phase 2 — Scan (airgapped)

```bash
# Briefly reconnect ONLY to update virus definitions:
sudo systemctl stop clamav-freshclam
sudo freshclam

# Disconnect from the internet, then scan:
sudo ansible-playbook playbooks/scan.yml -e "ark_storage_root=/path/to/staging"
```

Runs three checks:
1. **ClamAV malware scan** — every file in staging, ISOs, toolchains, pip cache
2. **GPG signature verification** — APT Release file signatures
3. **SHA256 hash verification** — every .deb checked against upstream Packages manifests

If any check fails, the playbook halts and tells you which files are flagged. **Do not promote** — investigate the flagged files first.

### Phase 3 — Promote (Ark storage only)

```bash
# Mount the Ark drive (do NOT reconnect to internet)
sudo ansible-playbook playbooks/promote.yml -e "ark_storage_root=/path/to/staging"
```

Only runs if the scan report shows a pass. Imports verified packages into the live reprepro repository and updates the Ark manifest. After this, unmount the storage drive and store it securely.

### Quick Path (no quarantine)

If you trust the upstream and want the old behavior — download and import in one step:

```bash
sudo ansible-playbook playbooks/update.yml -e "ark_storage_root=/path/to/ark"
```

This sets `ark_auto_promote: true` internally, which imports packages directly into reprepro without requiring a scan. Use this for routine updates when speed matters more than paranoia.

---

## Project Structure

```
ark/
├── ansible.cfg
├── inventory/
│   ├── local.yml
│   └── group_vars/all/
│       ├── main.yml                      # Paths, architectures, signing
│       ├── isos.yml                      # ← Edit: ISO list and URLs
│       ├── packages.yml                  # ← Edit: APT packages by category
│       └── toolchains.yml               # ← Edit: toolchain versions, pip pkgs
├── playbooks/
│   ├── full-sync.yml                     # Quick path — download + import
│   ├── update.yml                        # Quick path — incremental update
│   ├── download.yml                      # Quarantine: Phase 1 (internet)
│   ├── scan.yml                          # Quarantine: Phase 2 (airgapped)
│   ├── promote.yml                       # Quarantine: Phase 3 (Ark only)
│   └── verify.yml                        # Integrity check — read-only
├── roles/
│   ├── setup/                            # Installs tools, creates directories
│   ├── manifest/                         # Generates inventory manifest
│   │   └── files/generate_manifest.py
│   ├── isos/                             # Downloads and verifies ISOs
│   ├── apt_repo/                         # Resolves deps, downloads debs
│   │   └── files/resolve_and_download.py
│   ├── toolchains/                       # Downloads standalone toolchains
│   ├── pip_cache/                        # Downloads Python wheels
│   ├── scan/                             # ClamAV + GPG + hash verification
│   │   └── files/verify_packages.py
│   ├── promote/                          # Import scanned packages to live repo
│   └── verify/                           # Integrity check and reporting
├── scripts/
│   └── generate-offline-sources.sh       # Configure APT on a target machine
└── .gitignore
```

### Adding a Package

Open `inventory/group_vars/all/packages.yml`, find the right category, and add the package name:

```yaml
  terminal_tools:
    - tmux
    - neovim
    - my-new-package          # just add it here
```

Then run: `sudo ansible-playbook playbooks/update.yml --tags apt -e "ark_storage_root=..."`

The resolver will pull the package and all its dependencies automatically.

### Adding an ISO

Add an entry to `inventory/group_vars/all/isos.yml`:

```yaml
  - name: my-distro
    label: "My Distro 1.0"
    url: "https://example.com/my-distro-1.0.iso"
    checksum_url: "https://example.com/SHA256SUMS"
    arch: amd64
    category: desktop
```

Then run with `--tags isos`.

---

## Storage Layout (on the Ark drive)

```
/mnt/ark/
├── isos/                    # OS images, one directory per entry
│   ├── ubuntu-desktop-amd64/
│   ├── ubuntu-server-amd64/
│   ├── debian-trixie-netinst-amd64/
│   └── ...
├── apt-repo/                # Proper APT repository (reprepro-managed)
│   ├── dists/               #   distribution metadata
│   ├── pool/                #   .deb package files
│   └── conf/                #   reprepro configuration
├── toolchains/              # Standalone language runtimes
│   ├── rust/
│   ├── go/
│   ├── node/
│   └── zig/
├── pip-cache/               # Python wheels and source dists
│   ├── full/                #   with dependencies (native platform)
│   ├── manylinux2014_x86_64/
│   ├── manylinux2014_aarch64/
│   └── sdist/               #   source distributions (fallback)
├── manifests/               # JSON reports from each sync run
├── scripts/                 # Helper scripts for target machines
└── ARK_INFO.txt             # Sync history and timestamps
```

---

## Known Limitations

- **APT repo currently resolves against the build host's repos only.** The dependency resolver uses the host's `apt-cache`, so both the Noble and Trixie pools contain Ubuntu Noble packages. For true Debian Trixie packages, you would need to run the resolver inside a Debian container. Noble packages work on Trixie in most cases since they share the same package base.

- **Some packages are amd64-only.** Security tools (nikto, sqlmap, recon-ng), virtualization GUIs (virt-manager), and x86-specific firmware (intel-microcode) don't have arm64 builds. These are annotated with `# amd64 only` in `packages.yml`.

- **SourceForge downloads can be flaky.** SystemRescue uses the Fastly CDN to avoid this. Clonezilla uses a direct SourceForge link. If either fails, try running `--tags isos` again.

---

## License

The Ansible code is yours to use and modify. The packages, ISOs, and toolchains it downloads are subject to their respective open-source licenses.
