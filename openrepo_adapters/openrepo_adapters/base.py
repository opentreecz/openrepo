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

from abc import ABC, abstractmethod


class RepoFileAdapter(ABC):
    """Base class for package file metadata adapters.

    Subclasses parse format-specific metadata (name, version, architecture,
    etc.) from an uploaded package file.
    """

    def __init__(self, filepath, original_filename=None):
        self.filepath = filepath
        self.original_filename = original_filename

    @abstractmethod
    def get_name(self):
        """Return the package name."""

    @abstractmethod
    def get_architecture(self):
        """Return the package architecture string."""

    @abstractmethod
    def get_version(self):
        """Return the package version string."""

    @abstractmethod
    def get_description(self):
        """Return the package description."""

    @abstractmethod
    def get_builddate(self):
        """Return the package build date (datetime or None)."""
