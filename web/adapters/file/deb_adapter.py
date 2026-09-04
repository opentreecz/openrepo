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

from apt.debfile import DebPackage

from .base_adapter import RepoFileAdapter


class DebFileAdapter(RepoFileAdapter):
    def __init__(self, filepath, original_filename=None):
        super().__init__(filepath, original_filename)

        pkg = DebPackage(self.filepath)
        self.control = pkg.control_content("control")
        self.pkgname = pkg._sections["Package"]
        self._architecture = pkg._sections["Architecture"]
        self._version = pkg._sections["Version"]
        self._description = pkg._sections["Description"]

    def get_name(self):
        return self.pkgname

    def get_architecture(self):
        return self._architecture

    def get_version(self):
        return self._version

    def get_description(self):
        return self._description

    def get_builddate(self):
        return None
