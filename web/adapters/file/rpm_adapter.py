# Thin wrapper — the canonical implementation now lives in the
# standalone ``openrepo_adapters`` package.
#
# This wrapper auto-injects Django's RPM_VERSION_IGNORE_BUILD_NUM setting
# so that existing code constructing RpmFileAdapter directly continues to
# work without changes.

from django.conf import settings
from openrepo_adapters.rpm import RpmFileAdapter as _RpmFileAdapter


class RpmFileAdapter(_RpmFileAdapter):
    """Django-aware wrapper that auto-injects the ignore_build_num setting."""

    def __init__(self, filepath, original_filename=None, *, ignore_build_num=None):
        if ignore_build_num is None:
            ignore_build_num = getattr(settings, "RPM_VERSION_IGNORE_BUILD_NUM", False)
        super().__init__(filepath, original_filename, ignore_build_num=ignore_build_num)
