# Copyright 2022 by Open Kilt LLC. All rights reserved.
# This file is part of the OpenRepo Repository Management Software (OpenRepo)
# OpenRepo is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License
# version 3 as published by the Free Software Foundation
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

import logging

from .deb_adapter import DebFileAdapter  # noqa: F401
from .file_adapter import GenericFileAdapter  # noqa: F401
from .rpm_adapter import RpmFileAdapter  # noqa: F401

logger = logging.getLogger("openrepo_web")


def create_adapter(repo_type, filepath, original_filename):
    """Return the appropriate file adapter for the given repo type."""
    from adapters.registry import FILE_ADAPTERS

    adapter_cls = FILE_ADAPTERS.get(repo_type)
    if adapter_cls is None:
        logger.warning(f"Unable to determine file adapter from repo type {repo_type}")
        return None
    return adapter_cls(filepath, original_filename)
