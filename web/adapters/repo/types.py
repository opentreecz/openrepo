"""Data types for the repo adapter layer — no Django imports.

These types decouple the repo adapters from Django ORM models and settings,
allowing them to be tested and potentially reused outside of Django.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import ContextManager, List, Optional, Protocol


@dataclass(frozen=True)
class PackageInfo:
    """Immutable snapshot of a package's metadata for repo generation."""
    package_uid: str
    filename: str
    package_name: str
    architecture: str
    version: str
    relative_path: str          # e.g. "aa/axbpoiergm"
    checksum_sha512: str = ""
    upload_date: Optional[str] = None  # ISO format or None


@dataclass
class RepoConfig:
    """Paths and settings needed by repo adapters."""
    storage_path: str       # where package files live
    repo_www_path: str      # where repo output goes
    keyring_path: str       # GPG home directory
    deb_db_path: str = ""   # apt-ftparchive DB cache
    rpm_cache_dir: str = "" # createrepo cache dir
    subprocess_timeout: int = 600


@dataclass(frozen=True)
class SigningKeyInfo:
    """PGP key metadata needed for signing."""
    fingerprint: str
    public_key_pem: str
    passphrase: str = ""
    private_key_pem: str = ""


class BuildLogWriter(Protocol):
    """Protocol for build log output — no Django dependency."""

    def write(self, command: str, message: str = "",
              loglevel: str = "info", is_complete: bool = True) -> object:
        """Write a log line. Returns an opaque log-line handle."""
        ...

    def section(self, command: str,
                loglevel: str = "info") -> ContextManager:
        """Context manager for timed build sections."""
        ...


class RepoSigner(Protocol):
    """Protocol for GPG signing operations."""

    def ensure_key(self, key_info: SigningKeyInfo) -> None:
        """Ensure the signing key is available on the keyring."""
        ...
