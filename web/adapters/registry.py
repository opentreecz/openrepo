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

"""
Adapter registry — maps repo types to their adapter classes.

File adapters are re-exported from the standalone ``openrepo_adapters``
package.  Repo adapters remain in-tree.
"""

from openrepo_adapters import (
    ApkFileAdapter,
    DebFileAdapter,
    GenericFileAdapter,
    RpmFileAdapter,
)

from adapters.repo.apk_repo import ApkRepoAdapter
from adapters.repo.deb_repo import DebRepoAdapter
from adapters.repo.generic_repo import GenericRepoAdapter
from adapters.repo.rpm_repo import RpmRepoAdapter

REPO_ADAPTERS = {
    "deb": DebRepoAdapter,
    "rpm": RpmRepoAdapter,
    "apk": ApkRepoAdapter,
    "files": GenericRepoAdapter,
}

FILE_ADAPTERS = {
    "deb": DebFileAdapter,
    "rpm": RpmFileAdapter,
    "apk": ApkFileAdapter,
    "files": GenericFileAdapter,
}
