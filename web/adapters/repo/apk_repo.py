# Alpine APK repository adapter.
#
# Generates an APKINDEX.tar.gz file that Alpine's apk-tools can consume.

import base64
import gzip
import hashlib
import io
import logging
import os
import tarfile
import time

from .base_repo import BaseRepoAdapter

logger = logging.getLogger("openrepo_web")


class ApkRepoAdapter(BaseRepoAdapter):

    def _get_repo_instructions(self):
        return (
            f"# Add this to /etc/apk/repositories:\n"
            f"{self.base_url}\n"
        )

    def _generate_repo_structure(self, repo_path):
        # Symlink all packages into the repo directory
        self._copy_packages(repo_path)

        # Build the APKINDEX
        with self._buildlog_section("Generating APKINDEX.tar.gz") as log_entry:
            entries = []
            for pkg in self.packages:
                entry = _build_index_entry(pkg, repo_path)
                if entry:
                    entries.append(entry)

            index_text = "\n".join(entries) + "\n" if entries else ""
            _write_apkindex_tar_gz(repo_path, index_text, self.repo_uid)
            log_entry.set_message(f"Generated APKINDEX.tar.gz with {len(entries)} package(s)")

        # Export PGP public key if configured
        if self.signing_key is not None:
            self._save_public_key(repo_path)

        return True


def _build_index_entry(pkg, repo_path):
    """Build an APKINDEX entry block for a single package."""
    ext = os.path.splitext(pkg.filename)[1]
    pool_name = f"{pkg.package_name}_{pkg.version}_{pkg.architecture}{ext}"
    apk_path = os.path.join(repo_path, pool_name)

    if not os.path.exists(apk_path):
        logger.warning("APK file not found for index: %s", apk_path)
        return None

    try:
        file_size = os.path.getsize(apk_path)
        control_hash = _sha1_file(apk_path)
    except OSError as exc:
        logger.warning("Cannot stat APK %s: %s", apk_path, exc)
        return None

    checksum = "Q1" + base64.b64encode(control_hash).decode("ascii")

    lines = [
        f"C:{checksum}",
        f"P:{pkg.package_name}",
        f"V:{pkg.version}",
        f"A:{pkg.architecture}",
        f"S:{file_size}",
        f"T:{_first_line(pkg.filename)}",
        f"U:{_first_line(pkg.filename)}",
    ]

    return "\n".join(lines)


def _write_apkindex_tar_gz(repo_path, index_text, repo_uid):
    """Write APKINDEX.tar.gz containing the APKINDEX text file."""
    index_bytes = index_text.encode("utf-8")
    now = int(time.time())

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        desc = f"OpenRepo Alpine repository: {repo_uid}\n".encode("utf-8")
        desc_info = tarfile.TarInfo(name="DESCRIPTION")
        desc_info.size = len(desc)
        desc_info.mtime = now
        tar.addfile(desc_info, io.BytesIO(desc))

        info = tarfile.TarInfo(name="APKINDEX")
        info.size = len(index_bytes)
        info.mtime = now
        tar.addfile(info, io.BytesIO(index_bytes))

    tar_bytes = buf.getvalue()

    out_path = os.path.join(repo_path, "APKINDEX.tar.gz")
    with gzip.open(out_path, "wb") as gz:
        gz.write(tar_bytes)


def _sha1_file(filepath):
    """Return the raw SHA-1 digest (bytes) of a file."""
    h = hashlib.sha1()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.digest()


def _first_line(text):
    """Return the first non-empty line of text, or the text itself."""
    for line in str(text).splitlines():
        line = line.strip()
        if line:
            return line
    return str(text)
