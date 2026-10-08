# Thin wrapper — the canonical implementation now lives in the
# standalone ``openrepo_adapters`` package.  This module re-exports
# the base class so that existing in-tree imports continue to work.

from openrepo_adapters.base import RepoFileAdapter  # noqa: F401
