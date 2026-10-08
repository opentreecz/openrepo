# Alpine APK file adapter.
#
# Parses .apk package metadata from the .PKGINFO file embedded inside
# the gzipped tar archive.

import gzip
import io
import logging
import tarfile
from datetime import datetime, timezone

from .base import RepoFileAdapter

logger = logging.getLogger("openrepo_adapters")


class ApkFileAdapter(RepoFileAdapter):
    """Extract metadata from an Alpine APK package file.

    APK v2 packages consist of multiple concatenated gzip streams that
    together form a tar archive.  The control section contains a
    ``.PKGINFO`` file with key = value metadata lines.
    """

    def __init__(self, filepath, original_filename=None):
        super().__init__(filepath, original_filename)
        self.fields = _parse_pkginfo(filepath)

    def get_name(self):
        return self.fields.get("pkgname", "unknown")

    def get_version(self):
        return self.fields.get("pkgver", "0")

    def get_architecture(self):
        return self.fields.get("arch", "noarch")

    def get_description(self):
        return self.fields.get("pkgdesc", "")

    def get_builddate(self):
        ts = self.fields.get("builddate")
        if ts:
            try:
                return datetime.fromtimestamp(int(ts), tz=timezone.utc)
            except (ValueError, OSError):
                pass
        return None


def _parse_pkginfo(filepath):
    """Read .PKGINFO from the first gzip stream(s) of an APK archive.

    APK files are multi-stream gzip archives.  We decompress the entire
    file (Python's gzip module transparently concatenates streams) and
    look for a tar entry named ``.PKGINFO``.
    """
    fields = {}
    try:
        with gzip.open(filepath, "rb") as gz:
            raw = gz.read()
        with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
            for member in tar.getmembers():
                if member.name == ".PKGINFO" or member.name.endswith("/.PKGINFO"):
                    f = tar.extractfile(member)
                    if f is None:
                        continue
                    for line in f.read().decode("utf-8", errors="replace").splitlines():
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if " = " in line:
                            key, _, value = line.partition(" = ")
                            # Some fields (depend, provides, etc.) can repeat.
                            # We keep only the first value for simple fields,
                            # and concatenate repeating fields with spaces.
                            if key in fields and key in _MULTI_VALUE_KEYS:
                                fields[key] += " " + value
                            else:
                                fields[key] = value
                    break  # Only need the first .PKGINFO
    except Exception as exc:
        logger.warning("Failed to parse APK metadata from %s: %s", filepath, exc)
    return fields


# .PKGINFO keys that can appear multiple times per package.
_MULTI_VALUE_KEYS = frozenset({
    "depend", "provides", "replaces", "install_if", "triggers",
})
