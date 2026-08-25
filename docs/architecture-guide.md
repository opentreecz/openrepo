---
layout: default
title: Multi-Architecture Guide
nav_order: 6
---

<p align="center">
  <img src="https://raw.githubusercontent.com/opentreecz/.github/master/profile/img/opentreeczlogo.jpeg" alt="opentree.cz" width="120"/>
</p>

# Multi-Architecture Guide
{: .no_toc }

<details open markdown="block">
  <summary>Contents</summary>
  {: .text-delta }
- TOC
{:toc}
</details>

---

## Overview

OpenRepo supports hosting packages for multiple CPU architectures in a single repository. This is the standard and expected behavior for both Debian and RPM package ecosystems.

Having the same application version for different architectures (e.g., `myapp_1.0_amd64.deb` and `myapp_1.0_arm64.deb`) in the same repository is **correct and compliant** with Debian Policy and RPM conventions.

---

## How it works

### Debian (.deb) repositories

A standard Debian repository has the following structure:

```
repo/
  pool/
    main/
      myapp_1.0_amd64.deb
      myapp_1.0_arm64.deb
      myapp-common_1.0_all.deb
  dists/
    stable/
      main/
        binary-amd64/
          Packages
          Packages.gz
        binary-arm64/
          Packages
          Packages.gz
      Release
      Release.gpg
      InRelease
```

- Each architecture has its own `binary-<arch>/` directory with a `Packages` index
- Packages with `Architecture: all` (architecture-independent) appear in **every** architecture index per Debian Policy
- APT clients use `[arch=amd64,arm64]` in their `sources.list` to specify which architectures to download
- The unique constraint is `(package_name, version, architecture)` — same version for different architectures is allowed

**OpenRepo implements this via the `multi_arch` setting:**
- **Enabled (recommended):** Generates per-architecture `binary-<arch>/` directories
- **Disabled (legacy):** Generates a single `binary-any/` directory (non-standard but simpler)

### RPM (.rpm) repositories

RPM repositories support two modes:

**Multi-arch mode (recommended, `multi_arch=True`):**

```
repo/
  x86_64/
    repodata/
      repomd.xml
      primary.xml.gz
    myapp-1.0-1.x86_64.rpm
    myapp-common-1.0-1.noarch.rpm   <- noarch duplicated here
  aarch64/
    repodata/
      repomd.xml
      primary.xml.gz
    myapp-1.0-1.aarch64.rpm
    myapp-common-1.0-1.noarch.rpm   <- noarch duplicated here
  public.gpg
```

- Per-architecture subdirectories (`x86_64/`, `aarch64/`, etc.)
- `noarch` packages are symlinked into **every** architecture directory (same pattern as Debian's `Architecture: all`)
- `createrepo` runs separately for each architecture directory
- DNF/YUM clients use `$basearch` in the `baseurl` to automatically resolve to their architecture
- This is the standard pattern used by Fedora, RHEL, CentOS, and other major RPM distros

**Legacy mode (`multi_arch=False`):**

```
repo/
  myapp-1.0-1.x86_64.rpm
  myapp-1.0-1.aarch64.rpm
  myapp-common-1.0-1.noarch.rpm
  repodata/
    repomd.xml
    primary.xml.gz
```

- All packages (all architectures) stored flat in one directory
- Single `createrepo` run generates one metadata set
- `dnf`/`yum` clients filter by their system architecture at install time
- `noarch` packages are installed regardless of client architecture

### Generic file repositories

Generic repositories have no architecture handling — files are served as-is.

---

## Supported architectures

### Debian architectures

| Architecture | Description |
|---|---|
| `all` | Architecture-independent (scripts, data, documentation) |
| `amd64` | 64-bit x86 (Intel/AMD) |
| `arm64` | 64-bit ARM (AArch64) |
| `armhf` | 32-bit ARM with hardware floating-point |
| `armel` | 32-bit ARM with software floating-point |
| `i386` | 32-bit x86 |
| `loongarch64` | 64-bit Loongson (added to Debian 2023) |
| `riscv64` | 64-bit RISC-V |
| `s390x` | IBM System z |
| `ppc64el` | 64-bit PowerPC (little-endian) |
| `mips64el` | 64-bit MIPS (little-endian) |
| `mipsel` | 32-bit MIPS (little-endian) |

### RPM architectures

| Architecture | Description |
|---|---|
| `noarch` | Architecture-independent |
| `x86_64` | 64-bit x86 (Intel/AMD) |
| `aarch64` | 64-bit ARM (AArch64) |
| `armv7hl` | 32-bit ARM with hardware floating-point |
| `armv6l` | 32-bit ARM (Raspberry Pi Zero/1) |
| `i686` | 32-bit x86 |
| `ppc64le` | 64-bit PowerPC (little-endian) |
| `s390x` | IBM System z |
| `riscv64` | 64-bit RISC-V |

### OpenWrt architectures

| Architecture | Description |
|---|---|
| `all` | Architecture-independent (ipk) |
| `mipsel_24kc` | MIPS little-endian (MediaTek MT76x8, Ramips) |
| `mips_24kc` | MIPS big-endian (Atheros/QCA) |
| `arm_cortex-a7_neon-vfpv4` | ARM Cortex-A7 (MT7621, Allwinner) |
| `arm_cortex-a9_vfpv3-d16` | ARM Cortex-A9 (Marvell, Broadcom) |
| `arm_cortex-a15_neon-vfpv4` | ARM Cortex-A15 (IPQ platforms) |
| `aarch64_cortex-a53` | AArch64 Cortex-A53 (RPi 3/4, modern routers) |
| `aarch64_cortex-a72` | AArch64 Cortex-A72 |
| `aarch64_generic` | Generic AArch64 |
| `x86_64` | x86 routers / VMs |
| `i386_pentium4` | 32-bit x86 |
| `riscv64_riscv64` | RISC-V |

---

## Setting up multi-architecture repositories

### Creating a new repo (Web UI)

1. Click the **+** button to create a new repository
2. Enter a **Repo Unique ID** (e.g., `myproject-packages`)
3. Select **Debian/APT** as the repo type
4. The **Multi-architecture support** checkbox is enabled by default for new deb repos
5. Select a **Signing Key**
6. Click **Create Repo**

### Creating a new repo (API)

```bash
curl -X POST \
  -H "Authorization: Token <your-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "repo_uid": "myproject-packages",
    "repo_type": "deb",
    "signing_key": "<fingerprint>",
    "multi_arch": true
  }' \
  http://localhost:7376/api/repos/
```

### Uploading packages for multiple architectures

Upload each architecture variant separately:

```bash
# Upload amd64 package
openrepo upload myproject-packages myapp_1.0_amd64.deb

# Upload arm64 package
openrepo upload myproject-packages myapp_1.0_arm64.deb

# Upload architecture-independent package
openrepo upload myproject-packages myapp-docs_1.0_all.deb
```

All three packages will coexist in the same repository. The `Packages` index for `binary-amd64/` will list `myapp_1.0_amd64.deb` and `myapp-docs_1.0_all.deb`. The `binary-arm64/` index will list `myapp_1.0_arm64.deb` and `myapp-docs_1.0_all.deb`.

---

## Client configuration

### Debian/Ubuntu clients

For a multi-arch repo, the generated setup instructions include the architecture list:

```bash
# On an amd64 machine
echo "deb [arch=amd64,arm64 signed-by=/usr/share/keyrings/openrepo.gpg] \
  http://your-server:7376/myproject-packages/ stable main" \
  | sudo tee /etc/apt/sources.list.d/myproject.list
```

Each client will only download the package index for its own architecture, saving bandwidth and avoiding confusion.

### RPM/DNF clients

```bash
cat <<EOF | sudo tee /etc/yum.repos.d/myproject.repo
[myproject]
name=My Project
baseurl=http://your-server:7376/myproject-rpm/
enabled=1
gpgcheck=1
gpgkey=http://your-server:7376/myproject-rpm/public.gpg
EOF
```

The `dnf`/`yum` client automatically filters packages by the system architecture.

---

## Filtering by architecture (Web UI)

The package list view includes an **Architecture** filter dropdown. Use it to:

- View only packages for a specific architecture
- Verify that all expected architectures are present for a given version
- Quickly identify architecture-independent packages (`all` / `noarch`)

---

## Retention policies and architectures

Retention policies are applied **per (package_name, architecture)** group:

- **Keep latest N versions** keeps N versions for each architecture independently
- If you have `myapp_1.0_amd64.deb`, `myapp_2.0_amd64.deb`, and `myapp_1.0_arm64.deb` with "Keep latest 1", the result is `myapp_2.0_amd64.deb` and `myapp_1.0_arm64.deb`

This ensures that pruning old versions for one architecture does not affect packages for other architectures.

---

## CI/CD multi-architecture builds

A typical CI pipeline builds packages for multiple architectures and uploads them all to the same repo:

```yaml
# GitHub Actions example
jobs:
  build:
    strategy:
      matrix:
        arch: [amd64, arm64, armhf]
    steps:
      - uses: actions/checkout@v4
      - name: Build package
        run: dpkg-buildpackage -a${{ matrix.arch }}
      - name: Upload to OpenRepo
        run: |
          openrepo upload my-repo ./myapp_*_${{ matrix.arch }}.deb
```

---

## FAQ

**Q: Can I mix amd64 and arm64 packages in the same Debian repository?**

A: Yes. This is the standard and expected behavior. Enable `multi_arch` mode and each architecture gets its own index.

**Q: What happens if I upload a package with an unknown architecture?**

A: OpenRepo will accept it with a warning in the logs. The package will be stored and served, but clients may not be able to install it if the architecture doesn't match.

**Q: Do I need separate repos for each architecture?**

A: No. A single repo with `multi_arch` enabled handles all architectures. This is how Debian's official repositories work.

**Q: What about `Architecture: all` packages?**

A: They are automatically included in every architecture index (per Debian Policy). No special handling is needed from the user.

---

## OpenWrt deployment

OpenRepo can run as a full server on OpenWrt devices (requires 256MB+ RAM and 128MB+ storage). On OpenWrt, native C tools (`apt-ftparchive`, `createrepo_c`) are not available, so OpenRepo uses **pure-Python fallback tools** for generating repository metadata.

This is controlled by the `OPENREPO_USE_PYTHON_TOOLS=1` environment variable, which is set automatically by the OpenWrt procd init script. **This fallback only applies to OpenWrt deployments** — all other platforms (Docker, DEB, RPM, Arch, bare-metal) continue using native tools.

See the dedicated [OpenWrt Deployment](openwrt) page for full installation and configuration instructions.

---

## Future package formats (roadmap)

The following package formats are planned or under consideration for future OpenRepo releases:

| Format | Extension | Ecosystem | Status |
|---|---|---|---|
| **Alpine APK** | `.apk` | Alpine Linux, Docker base images | Planned |
| **Flatpak** | `.flatpak` | Desktop Linux (sandboxed) | Under consideration |
| **AppImage** | `.AppImage` | Desktop Linux (portable) | Under consideration |
| **Snap** | `.snap` | Ubuntu, IoT devices | Under consideration |
| **Nix** | `.nix` | NixOS (declarative, reproducible) | Under consideration |
| **Void XBPS** | `.xbps` | Void Linux | Under consideration |
| **Gentoo ebuild** | `.ebuild` | Gentoo/Calculate/Funtoo (source-based) | Under consideration |
| **FreeBSD pkg** | `.pkg` | FreeBSD | Under consideration |

Community contributions for any of these formats are welcome. See the [CONTRIBUTING guide](https://github.com/opentreecz/openrepo/blob/main/CONTRIBUTING.md) for how to add a new package format adapter.
