"""
Pure-Python fallback implementations of apt-ftparchive and createrepo_c.

Used ONLY on OpenWrt (or other minimal environments) where native C tools
are not available. Controlled by the OPENREPO_USE_PYTHON_TOOLS=1 environment
variable. This module has NO impact on standard deployments (Docker, DEB, RPM,
Arch, bare-metal) which continue using apt-ftparchive and createrepo_c.
"""

import gzip
import hashlib
import logging
import os
import time
from xml.etree import ElementTree as ET

logger = logging.getLogger("openrepo_web")


def _compute_hashes(filepath):
    """Compute MD5, SHA1, and SHA256 hashes + file size."""
    md5 = hashlib.md5()
    sha1 = hashlib.sha1()
    sha256 = hashlib.sha256()
    size = 0
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            md5.update(chunk)
            sha1.update(chunk)
            sha256.update(chunk)
            size += len(chunk)
    return {
        "md5": md5.hexdigest(),
        "sha1": sha1.hexdigest(),
        "sha256": sha256.hexdigest(),
        "size": size,
    }


def _read_deb_control(filepath):
    """
    Read the control file from a .deb package (ar archive format).
    Returns the control file content as a string.
    """
    import tarfile
    import io

    with open(filepath, "rb") as f:
        # Skip ar magic
        magic = f.read(8)
        if magic != b"!<arch>\n":
            raise ValueError(f"Not a valid .deb file: {filepath}")

        # Iterate ar members to find control.tar.*
        while True:
            header = f.read(60)
            if len(header) < 60:
                break
            name = header[0:16].strip().decode("ascii")
            size_str = header[48:58].strip().decode("ascii")
            size = int(size_str)

            if name.startswith("control.tar"):
                control_data = f.read(size)
                # Determine compression
                if name.endswith(".gz"):
                    control_data = gzip.decompress(control_data)
                elif name.endswith(".xz"):
                    import lzma
                    control_data = lzma.decompress(control_data)
                elif name.endswith(".zst"):
                    try:
                        import zstandard
                        dctx = zstandard.ZstdDecompressor()
                        control_data = dctx.decompress(control_data)
                    except ImportError:
                        raise ValueError("zstandard library required for .zst debs")

                # Parse as tar
                tar = tarfile.open(fileobj=io.BytesIO(control_data))
                for member in tar.getmembers():
                    if member.name in ("./control", "control"):
                        ctrl_file = tar.extractfile(member)
                        return ctrl_file.read().decode("utf-8")
                break
            else:
                f.read(size)
                if size % 2:
                    f.read(1)  # ar padding

    raise ValueError(f"No control file found in {filepath}")


def generate_packages_file(pool_dir, output_dir, arch=None):
    """
    Generate Debian Packages and Packages.gz files from .deb files in pool_dir.

    This replaces apt-ftparchive for OpenWrt deployments.

    Args:
        pool_dir: Directory containing .deb files (or symlinks to them)
        output_dir: Directory to write Packages and Packages.gz
        arch: If specified, only include packages matching this architecture
              (plus 'all' packages per Debian policy)
    """
    entries = []

    for root, dirs, files in os.walk(pool_dir):
        for filename in sorted(files):
            if not filename.endswith(".deb"):
                continue
            filepath = os.path.join(root, filename)
            rel_path = os.path.relpath(filepath, os.path.dirname(pool_dir))

            try:
                control = _read_deb_control(filepath)
            except (ValueError, Exception) as e:
                logger.warning(f"fallback_tools: skipping {filename}: {e}")
                continue

            # Parse architecture from control
            pkg_arch = None
            for line in control.splitlines():
                if line.startswith("Architecture:"):
                    pkg_arch = line.split(":", 1)[1].strip()
                    break

            # Filter by architecture if specified
            if arch and pkg_arch and pkg_arch != "all" and pkg_arch != arch:
                continue

            hashes = _compute_hashes(filepath)

            # Build the Packages entry
            entry = control.rstrip("\n")
            entry += f"\nFilename: {rel_path}"
            entry += f"\nSize: {hashes['size']}"
            entry += f"\nMD5sum: {hashes['md5']}"
            entry += f"\nSHA1: {hashes['sha1']}"
            entry += f"\nSHA256: {hashes['sha256']}"
            entry += "\n"
            entries.append(entry)

    packages_content = "\n".join(entries)

    # Write Packages file
    packages_path = os.path.join(output_dir, "Packages")
    with open(packages_path, "w") as f:
        f.write(packages_content)

    # Write Packages.gz
    packages_gz_path = os.path.join(output_dir, "Packages.gz")
    with gzip.open(packages_gz_path, "wt", encoding="utf-8") as f:
        f.write(packages_content)

    logger.info(
        f"fallback_tools: generated Packages ({len(entries)} entries) "
        f"for {output_dir}"
    )
    return len(entries)


def generate_rpm_repodata(repo_dir, arch=None):
    """
    Generate RPM repository metadata (repomd.xml, primary.xml.gz).

    This replaces createrepo_c for OpenWrt deployments. Uses the rpmfile
    library (already a dependency of OpenRepo) to read RPM headers.

    Args:
        repo_dir: Directory containing .rpm files
        arch: If specified, only include RPMs matching this architecture
              (plus 'noarch' packages, which are included in every arch index)
    """
    try:
        import rpmfile
    except ImportError:
        logger.error("fallback_tools: rpmfile library required for RPM repo generation")
        return False

    repodata_dir = os.path.join(repo_dir, "repodata")
    os.makedirs(repodata_dir, exist_ok=True)

    # Collect RPM package info
    packages = []
    for filename in sorted(os.listdir(repo_dir)):
        if not filename.endswith(".rpm"):
            continue
        filepath = os.path.join(repo_dir, filename)
        if os.path.isdir(filepath):
            continue

        try:
            with rpmfile.open(filepath) as rpm:
                name = rpm.headers.get("name", b"").decode("utf-8", errors="replace")
                version = rpm.headers.get("version", b"").decode("utf-8", errors="replace")
                release = rpm.headers.get("release", b"").decode("utf-8", errors="replace")
                pkg_arch = rpm.headers.get("arch", b"").decode("utf-8", errors="replace")
                summary = rpm.headers.get("summary", b"").decode("utf-8", errors="replace")

            # Filter by architecture if specified (include matching arch + noarch)
            if arch and pkg_arch and pkg_arch != "noarch" and pkg_arch != arch:
                continue

            hashes = _compute_hashes(filepath)
            packages.append({
                "name": name,
                "version": version,
                "release": release,
                "arch": pkg_arch,
                "summary": summary,
                "filename": filename,
                "size": hashes["size"],
                "sha256": hashes["sha256"],
            })
        except Exception as e:
            logger.warning(f"fallback_tools: skipping {filename}: {e}")
            continue

    # Generate primary.xml
    root = ET.Element("metadata", xmlns="http://linux.duke.edu/metadata/common",
                      packages=str(len(packages)))

    for pkg in packages:
        pkg_el = ET.SubElement(root, "package", type="rpm")
        ET.SubElement(pkg_el, "name").text = pkg["name"]
        ET.SubElement(pkg_el, "arch").text = pkg["arch"]
        ET.SubElement(pkg_el, "version",
                      epoch="0", ver=pkg["version"], rel=pkg["release"])
        ET.SubElement(pkg_el, "checksum", type="sha256", pkgid="YES").text = pkg["sha256"]
        ET.SubElement(pkg_el, "summary").text = pkg["summary"]
        ET.SubElement(pkg_el, "size", package=str(pkg["size"]))
        ET.SubElement(pkg_el, "location", href=pkg["filename"])

    primary_xml = ET.tostring(root, encoding="unicode", xml_declaration=True)

    # Write primary.xml.gz
    primary_gz_path = os.path.join(repodata_dir, "primary.xml.gz")
    with gzip.open(primary_gz_path, "wt", encoding="utf-8") as f:
        f.write(primary_xml)

    # Compute hash of primary.xml.gz
    primary_hashes = _compute_hashes(primary_gz_path)

    # Generate repomd.xml
    repomd = ET.Element("repomd", xmlns="http://linux.duke.edu/metadata/repo")
    ET.SubElement(repomd, "revision").text = str(int(time.time()))

    data_el = ET.SubElement(repomd, "data", type="primary")
    ET.SubElement(data_el, "checksum", type="sha256").text = primary_hashes["sha256"]
    ET.SubElement(data_el, "location", href="repodata/primary.xml.gz")
    ET.SubElement(data_el, "size").text = str(primary_hashes["size"])
    ET.SubElement(data_el, "timestamp").text = str(int(time.time()))

    repomd_xml = ET.tostring(repomd, encoding="unicode", xml_declaration=True)
    repomd_path = os.path.join(repodata_dir, "repomd.xml")
    with open(repomd_path, "w") as f:
        f.write(repomd_xml)

    logger.info(
        f"fallback_tools: generated repodata ({len(packages)} packages) "
        f"for {repo_dir}"
    )
    return True
