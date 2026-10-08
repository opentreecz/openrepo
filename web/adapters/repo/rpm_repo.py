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
import os

from .base_repo import BaseRepoAdapter

logger = logging.getLogger("openrepo_web")

RPM_ARCH_DEFAULT = "x86_64"


class RpmRepoAdapter(BaseRepoAdapter):

    def _get_architectures(self):
        if not self.multi_arch:
            return None

        arches = sorted(set(
            p.architecture for p in self.packages
            if p.architecture and p.architecture != "noarch"
        ))
        return arches if arches else [RPM_ARCH_DEFAULT]

    def _get_repo_instructions(self):
        repo_cfg_file = f"/etc/yum.repos.d/{self.repo_uid}.repo"

        if self.multi_arch:
            baseurl = f"{self.base_url}/$basearch"
        else:
            baseurl = self.base_url

        repo_instr = 'echo """\n'
        repo_instr += f"[{self.repo_uid}]\n"
        repo_instr += f"name={self.repo_uid}\n"
        repo_instr += f"baseurl={baseurl}\n"
        repo_instr += "enabled=1\n"
        repo_instr += "repo_gpgcheck=1\n"
        repo_instr += f"gpgkey={self.base_url}/public.gpg\n"
        repo_instr += f'""" > {repo_cfg_file}'

        return repo_instr

    def _generate_repo_structure(self, repo_path):
        architectures = self._get_architectures()

        if architectures is not None:
            return self._generate_multi_arch(repo_path, architectures)
        else:
            return self._generate_legacy(repo_path)

    def _generate_multi_arch(self, repo_path, architectures):
        noarch_packages = [p for p in self.packages if p.architecture == "noarch"]

        exec_commands = []
        use_python_tools = os.environ.get("OPENREPO_USE_PYTHON_TOOLS") == "1"

        for arch in architectures:
            arch_dir = os.path.join(repo_path, arch)
            os.makedirs(arch_dir, exist_ok=True)

            arch_packages = [p for p in self.packages if p.architecture == arch]
            self._copy_packages(arch_dir, packages=arch_packages + noarch_packages)

            if use_python_tools:
                from .fallback_tools import generate_rpm_repodata
                generate_rpm_repodata(arch_dir)
            else:
                if not os.path.isdir(self.config.rpm_cache_dir):
                    os.makedirs(self.config.rpm_cache_dir)
                exec_commands.append((
                    ["createrepo", "--cachedir", self.config.rpm_cache_dir, arch_dir],
                    None,
                ))

        if self.signing_key is None:
            self._buildlog_write(
                "Missing PGP Key",
                "PGP key not configured for this repo.  Signing disabled",
                loglevel=self.BUILDLOG_WARNING,
            )
        else:
            for arch in architectures:
                arch_dir = os.path.join(repo_path, arch)
                repomd_path = os.path.join(arch_dir, "repodata", "repomd.xml")
                exec_commands.append((
                    [
                        "gpg", "--detach-sign", "--yes",
                        "--local-user", self.signing_key.fingerprint,
                        "--armor", repomd_path,
                    ],
                    None,
                ))
            self._save_public_key(repo_path)

        return self._execute_commands(exec_commands, repo_path)

    def _generate_legacy(self, repo_path):
        self._copy_packages(repo_path)

        use_python_tools = os.environ.get("OPENREPO_USE_PYTHON_TOOLS") == "1"
        exec_commands = []

        if use_python_tools:
            from .fallback_tools import generate_rpm_repodata
            generate_rpm_repodata(repo_path)
        else:
            if not os.path.isdir(self.config.rpm_cache_dir):
                os.makedirs(self.config.rpm_cache_dir)
            exec_commands = [
                (["createrepo", "--cachedir", self.config.rpm_cache_dir, repo_path], None),
            ]

        if self.signing_key is None:
            self._buildlog_write(
                "Missing PGP Key",
                "PGP key not configured for this repo.  Signing disabled",
                loglevel=self.BUILDLOG_WARNING,
            )
        else:
            repomd_path = os.path.join(repo_path, "repodata", "repomd.xml")
            exec_commands.append((
                [
                    "gpg", "--detach-sign", "--yes",
                    "--local-user", self.signing_key.fingerprint,
                    "--armor", repomd_path,
                ],
                None,
            ))
            self._save_public_key(repo_path)

        return self._execute_commands(exec_commands, repo_path)
