# Known package architectures for Debian, RPM, and OpenWrt repositories.
# This list is used for validation warnings (not hard rejections) when
# an uploaded package declares an architecture not in this set.

# Debian architecture names (dpkg --print-architecture)
DEB_ARCHITECTURES = frozenset([
    "all",          # Architecture-independent
    "amd64",        # 64-bit x86
    "arm64",        # 64-bit ARM (AArch64)
    "armel",        # 32-bit ARM (soft-float, little-endian)
    "armhf",        # 32-bit ARM (hard-float)
    "i386",         # 32-bit x86
    "loongarch64",  # 64-bit Loongson (added to Debian 2023)
    "mips64el",     # 64-bit MIPS (little-endian)
    "mipsel",       # 32-bit MIPS (little-endian)
    "ppc64el",      # 64-bit PowerPC (little-endian)
    "riscv64",      # 64-bit RISC-V
    "s390x",        # IBM System z
])

# RPM architecture names (from rpm --showrc | grep arch)
RPM_ARCHITECTURES = frozenset([
    "noarch",    # Architecture-independent
    "x86_64",    # 64-bit x86
    "aarch64",   # 64-bit ARM
    "armv7hl",   # 32-bit ARM (hard-float)
    "armv7l",    # 32-bit ARM
    "armv6l",    # 32-bit ARM (Raspberry Pi Zero/1)
    "i686",      # 32-bit x86
    "i586",      # 32-bit x86 (older)
    "i486",      # 32-bit x86 (very old)
    "i386",      # 32-bit x86
    "ppc64le",   # 64-bit PowerPC (little-endian)
    "ppc64",     # 64-bit PowerPC
    "s390x",     # IBM System z
    "riscv64",   # 64-bit RISC-V
    "mips64el",  # 64-bit MIPS (little-endian)
    "mipsel",    # 32-bit MIPS (little-endian)
])

# OpenWrt architecture names (target/subtarget naming convention)
OPENWRT_ARCHITECTURES = frozenset([
    "all",                          # Architecture-independent (ipk)
    "mipsel_24kc",                  # MIPS little-endian (MediaTek MT76x8, Ramips)
    "mips_24kc",                    # MIPS big-endian (Atheros/QCA)
    "arm_cortex-a7_neon-vfpv4",     # ARM Cortex-A7 (MT7621, Allwinner)
    "arm_cortex-a9_vfpv3-d16",      # ARM Cortex-A9 (Marvell, Broadcom)
    "arm_cortex-a15_neon-vfpv4",    # ARM Cortex-A15 (IPQ platforms)
    "aarch64_cortex-a53",           # AArch64 Cortex-A53 (RPi 3/4, modern routers)
    "aarch64_cortex-a72",           # AArch64 Cortex-A72
    "aarch64_generic",              # Generic AArch64
    "x86_64",                       # x86 routers / VMs
    "i386_pentium4",                # 32-bit x86
    "riscv64_riscv64",              # RISC-V
])

# Combined set for generic/unknown repo types
ALL_KNOWN_ARCHITECTURES = DEB_ARCHITECTURES | RPM_ARCHITECTURES | OPENWRT_ARCHITECTURES | frozenset([
    "any",       # OpenRepo legacy/generic
    "src",       # Source packages
    "source",    # Source packages (alternative naming)
])


def get_known_architectures(repo_type: str) -> frozenset:
    """Return the set of known architectures for the given repository type."""
    if repo_type == "deb":
        return DEB_ARCHITECTURES
    elif repo_type == "rpm":
        return RPM_ARCHITECTURES
    elif repo_type in ("openwrt", "ipk"):
        return OPENWRT_ARCHITECTURES
    else:
        return ALL_KNOWN_ARCHITECTURES


def is_known_architecture(architecture: str, repo_type: str) -> bool:
    """Check if the given architecture is in the known set for the repo type."""
    return architecture in get_known_architectures(repo_type)
