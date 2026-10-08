"""openrepo-adapters: standalone package metadata extraction library.

Provides file adapters for .deb, .rpm, .apk, and generic files.
No Django dependency — can be used in any Python project.
"""

from .apk import ApkFileAdapter
from .base import RepoFileAdapter
from .deb import DebFileAdapter
from .generic import GenericFileAdapter
from .rpm import RpmFileAdapter

ADAPTERS = {
    "deb": DebFileAdapter,
    "rpm": RpmFileAdapter,
    "apk": ApkFileAdapter,
    "files": GenericFileAdapter,
}

__all__ = [
    "RepoFileAdapter",
    "DebFileAdapter",
    "RpmFileAdapter",
    "ApkFileAdapter",
    "GenericFileAdapter",
    "ADAPTERS",
    "create_adapter",
]


def create_adapter(repo_type, filepath, original_filename=None, **kwargs):
    """Return the appropriate file adapter for the given repo type.

    Extra keyword arguments are forwarded to the adapter constructor
    (e.g. ``ignore_build_num=True`` for RPM adapters).
    """
    adapter_cls = ADAPTERS.get(repo_type)
    if adapter_cls is None:
        return None
    return adapter_cls(filepath, original_filename, **kwargs)
