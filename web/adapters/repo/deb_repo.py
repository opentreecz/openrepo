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

from django.conf import settings

from .base_repo import BaseRepoAdapter

logger = logging.getLogger("openrepo_web")


# Repo config looks like:
# deb [arch=amd64 signed-by=/key.gpg2] http://172.17.0.1:9000/mytestrepo/amd64 stable main

# Legacy single-architecture name used when multi_arch is disabled on the repo.
DEB_ARCH_LEGACY = "any"

# Default architecture used in single-arch mode and as the fallback when a
# multi_arch repo has no packages yet.
DEB_ARCH_DEFAULT = "amd64"


class DebRepoAdapter(BaseRepoAdapter):

    def _get_architectures(self):
        """
        Return the list of distinct architectures present in the repo's package set.

        In multi_arch mode: collect real architectures from packages (e.g. amd64, arm64).
        In legacy mode: always return ["any"].

        Falls back to [DEB_ARCH_DEFAULT] when no packages exist yet so that
        an empty multi_arch repo still generates a valid (if empty) structure.
        """
        if not self.repo_db_obj.multi_arch:
            return [DEB_ARCH_LEGACY]

        arches = sorted(set(
            p.architecture for p in self.packages
            if p.architecture and p.architecture != "all"
        ))
        return arches if arches else [DEB_ARCH_DEFAULT]

    def _get_repo_instructions(self):
        dest_gpg_path = f"/usr/share/keyrings/openrepo-{self.repo_uid}.gpg"

        if self.repo_db_obj.multi_arch:
            # Collect real architectures; fall back to default when repo is empty.
            arches = sorted(set(
                p.architecture for p in self.packages
                if p.architecture and p.architecture != "all"
            )) or [DEB_ARCH_DEFAULT]
            arch_str = ",".join(arches)
        else:
            arch_str = DEB_ARCH_LEGACY

        repo_address = "apt update && apt install -y curl gnupg\n"
        repo_address += f"curl {self.base_url}/public.gpg | gpg --yes --dearmor -o {dest_gpg_path}\n"
        repo_address += (
            f'echo "deb [arch={arch_str} signed-by={dest_gpg_path}] '
            f'{self.base_url}/ stable main" '
            f'> /etc/apt/sources.list.d/openrepo-{self.repo_uid}.list\n'
        )
        repo_address += "apt update"
        return repo_address

    def _generate_repo_structure(self, repo_path):

        # poolnames = ['main', 'contrib', 'non-free']
        poolnames = ["main"]

        architectures = self._get_architectures()

        # Create pool and per-architecture binary dirs
        directories = []
        for poolname in poolnames:
            directories.append(f"pool/{poolname}")
            for arch in architectures:
                directories.append(f"dists/stable/{poolname}/binary-{arch}")

        for dirpath in directories:
            fullpath = os.path.join(repo_path, dirpath)
            with self._buildlog_section(f"Creating directory {fullpath}"):
                os.makedirs(fullpath, exist_ok=True)

        all_pools = " ".join(poolnames)
        arch_list = " ".join(architectures)
        release_conf = 'APT::FTPArchive::Release::Codename "stable";' + "\n"
        release_conf += f'APT::FTPArchive::Release::Components "{all_pools}";' + "\n"
        release_conf += f'APT::FTPArchive::Release::Label "{self.repo_uid} APT Repository";' + "\n"
        release_conf += f'APT::FTPArchive::Release::Architectures "{arch_list}";'

        with self._buildlog_section("Writing release.conf"):
            release_conf_path = os.path.join(repo_path, "release.conf")
            with open(release_conf_path, "w+") as f:
                f.writelines(release_conf)

        # Symlink all files into pool/main/
        package_dest = os.path.join(repo_path, "pool/main/")
        self._copy_packages(package_dest)

        # Each command is a (args_list, output_file_or_None) tuple.
        # When output_file is set, stdout is written to that path (relative
        # to repo_path) — replacing the old shell ">" redirection.
        exec_commands = []

        # Check if we should use pure-Python fallback tools (OpenWrt only)
        use_python_tools = os.environ.get("OPENREPO_USE_PYTHON_TOOLS") == "1"

        if use_python_tools:
            # Pure-Python fallback: generate Packages/Packages.gz without apt-ftparchive.
            # This path is ONLY used on OpenWrt where apt-ftparchive is unavailable.
            from .fallback_tools import generate_packages_file

            pool_dir = os.path.join(repo_path, "pool")
            if self.repo_db_obj.multi_arch and len(architectures) > 1:
                for arch in architectures:
                    output_dir = os.path.join(repo_path, f"dists/stable/main/binary-{arch}")
                    generate_packages_file(pool_dir, output_dir, arch=arch)
            else:
                arch = architectures[0]
                for poolname in poolnames:
                    output_dir = os.path.join(repo_path, f"dists/stable/{poolname}/binary-{arch}")
                    generate_packages_file(pool_dir, output_dir, arch=None)
        else:
            # Standard path: use apt-ftparchive (Docker, DEB, RPM, Arch, bare-metal)
            aptftp_base = [
                "apt-ftparchive",
                "--db", settings.DEB_DB_PATH,
                "-o", "APT::FTPArchive::AlwaysStat=true",
            ]

            if self.repo_db_obj.multi_arch and len(architectures) > 1:
                # Per-architecture Packages index.
                # arch=all packages must appear in every arch's index (Debian policy).
                for arch in architectures:
                    exec_commands.append((
                        aptftp_base + ["packages", "--arch", arch, "pool/"],
                        f"dists/stable/main/binary-{arch}/Packages",
                    ))
                    exec_commands.append((
                        ["gzip", "-k", f"dists/stable/main/binary-{arch}/Packages"],
                        None,
                    ))
            else:
                # Legacy single-arch (or only one real arch present)
                arch = architectures[0]
                for poolname in poolnames:
                    exec_commands.append((
                        aptftp_base + ["packages", "pool/"],
                        f"dists/stable/{poolname}/binary-{arch}/Packages",
                    ))
                exec_commands.append((
                    ["gzip", "-k", f"dists/stable/{poolname}/binary-{arch}/Packages"],
                    None,
                ))

        # Contents files (per-arch)
        aptftp_base_contents = [
            "apt-ftparchive",
            "--db", settings.DEB_DB_PATH,
            "-o", "APT::FTPArchive::AlwaysStat=true",
        ]
        for poolname in poolnames:
            for arch in architectures:
                exec_commands.append((
                    aptftp_base_contents + ["contents", f"pool/{poolname}"],
                    f"dists/stable/{poolname}/Contents-{arch}",
                ))
                exec_commands.append((
                    ["gzip", "-k", f"dists/stable/{poolname}/Contents-{arch}"],
                    None,
                ))

        # Per-component Release files
        for poolname in poolnames:
            for arch in architectures:
                exec_commands.append((
                    aptftp_base_contents + [
                        "release",
                        f"dists/stable/{poolname}/binary-{arch}",
                    ],
                    f"dists/stable/{poolname}/binary-{arch}/Release",
                ))

        # Top-level Release file (lists all architectures via release.conf)
        exec_commands.append((
            aptftp_base_contents + [
                "release", "-c", "release.conf", "dists/stable",
            ],
            "dists/stable/Release",
        ))

        if self.pgp_key is None:
            self._buildlog_write(
                "Missing PGP Key",
                "PGP key not configured for this repo.  Signing disabled",
                loglevel=self.BUILDLOG_WARNING,
            )
        else:
            exec_commands.append((
                [
                    "gpg", "-a", "--yes",
                    "--output", "dists/stable/Release.gpg",
                    "--local-user", self.pgp_key.fingerprint,
                    "--detach-sign", "dists/stable/Release",
                ],
                None,
            ))
            exec_commands.append((
                [
                    "gpg", "-a", "--yes", "--clearsign",
                    "--output", "dists/stable/InRelease",
                    "--local-user", self.pgp_key.fingerprint,
                    "--detach-sign", "dists/stable/Release",
                ],
                None,
            ))

            self._save_public_key(repo_path)

        return self._execute_commands(exec_commands, repo_path)
