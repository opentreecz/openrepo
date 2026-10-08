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

from openrepo_adapters import (  # noqa: F401
    ApkFileAdapter,
    DebFileAdapter,
    GenericFileAdapter,
    RpmFileAdapter,
)
from openrepo_adapters import create_adapter as _create_adapter

logger = logging.getLogger("openrepo_web")


def create_adapter(repo_type, filepath, original_filename):
    """Return the appropriate file adapter for the given repo type.

    Wraps the standalone ``openrepo_adapters.create_adapter`` factory,
    injecting Django settings where needed (e.g., RPM_VERSION_IGNORE_BUILD_NUM).
    """
    kwargs = {}
    if repo_type == "rpm":
        from django.conf import settings
        kwargs["ignore_build_num"] = getattr(settings, "RPM_VERSION_IGNORE_BUILD_NUM", False)
    return _create_adapter(repo_type, filepath, original_filename, **kwargs)
