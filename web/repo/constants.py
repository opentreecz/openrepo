# Known package architectures for Debian and RPM repositories.
# This list is used for validation warnings (not hard rejections) when
# an uploaded package declares an architecture not in this set.

# Debian architecture names (dpkg --print-architecture)
DEB_ARCHITECTURES = frozenset([
    "all",       # Architecture-independent
    "amd64",     # 64-bit x86
    "arm64",     # 64-bit ARM (AArch64)
    "armel",     # 32-bit ARM (soft-float, little-endian)
    "armhf",     # 32-bit ARM (hard-float)
    "i386",      # 32-bit x86
    "mips64el",  # 64-bit MIPS (little-endian)
    "mipsel",    # 32-bit MIPS (little-endian)
    "ppc64el",   # 64-bit PowerPC (little-endian)
    "riscv64",   # 64-bit RISC-V
    "s390x",     # IBM System z
])

# RPM architecture names (from rpm --showrc | grep arch)
RPM_ARCHITECTURES = frozenset([
    "noarch",    # Architecture-independent
    "x86_64",    # 64-bit x86
    "aarch64",   # 64-bit ARM
    "armv7hl",   # 32-bit ARM (hard-float)
    "armv7l",    # 32-bit ARM
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

# Combined set for generic/unknown repo types
ALL_KNOWN_ARCHITECTURES = DEB_ARCHITECTURES | RPM_ARCHITECTURES | frozenset([
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
    else:
        return ALL_KNOWN_ARCHITECTURES


def is_known_architecture(architecture: str, repo_type: str) -> bool:
    """Check if the given architecture is in the known set for the repo type."""
    return architecture in get_known_architectures(repo_type)
