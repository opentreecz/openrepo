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

"""Base repo adapter — Django-free.

All Django ORM interactions (Build records, Package queries, settings) are
handled by the orchestrator (``orchestrator.py``).  This module receives
its dependencies via constructor injection.
"""

import logging
import os
import shutil
import subprocess

logger = logging.getLogger("openrepo_web")


class BaseRepoAdapter:

    BUILDLOG_DEBUG = "debug"
    BUILDLOG_INFO = "info"
    BUILDLOG_WARNING = "warning"
    BUILDLOG_ERROR = "error"

    # Subprocess timeout in seconds — prevents indefinite hangs from
    # createrepo, apt-ftparchive, or gpg.
    SUBPROCESS_TIMEOUT = 600

    def __init__(self, repo_db_obj=None, *, repo_uid=None, packages=None, config=None,
                 build_logger=None, signing_key=None, signer=None, base_url="",
                 multi_arch=False):
        """
        Supports two calling conventions:

        **New (injected dependencies):**
            Adapter(repo_uid=..., packages=[...], config=..., build_logger=...)

        **Legacy (Django model — backward compat for tests/serializers):**
            Adapter(repo_db_obj)

        Args:
            repo_db_obj: Legacy positional — a Django Repository model instance.
            repo_uid: Repository identifier string.
            packages: List of ``PackageInfo`` dataclasses.
            config: ``RepoConfig`` with filesystem paths.
            build_logger: Object implementing ``BuildLogWriter`` protocol.
            signing_key: Optional ``SigningKeyInfo`` for PGP signing.
            signer: Optional ``RepoSigner`` for GPG keyring operations.
            base_url: Base URL for repo instructions.
            multi_arch: Whether to generate per-architecture directories.
        """
        if repo_db_obj is not None:
            # Legacy path — construct from Django ORM model
            from adapters.repo import get_repo_adapter as _compat
            # Re-use the compat factory to populate fields
            self._init_from_model(repo_db_obj)
            return

        self.repo_uid = repo_uid
        self.packages = packages or []
        self.config = config
        self.build_logger = build_logger
        self.signing_key = signing_key
        self.signer = signer
        self.base_url = base_url
        self.multi_arch = multi_arch

    def _init_from_model(self, repo_db_obj):
        """Initialize from a legacy Django Repository model."""
        import contextlib
        from django.conf import settings

        self.repo_uid = repo_db_obj.repo_uid
        self.multi_arch = repo_db_obj.multi_arch
        self.base_url = f"<origin>/{self.repo_uid}"

        # Lazy import to avoid circular deps
        from adapters.repo.types import PackageInfo, RepoConfig, SigningKeyInfo
        from repo.models import Package

        self.packages = [
            PackageInfo(
                package_uid=p.package_uid,
                filename=p.filename,
                package_name=p.package_name,
                architecture=p.architecture,
                version=p.version,
                relative_path=p.relative_path(),
                checksum_sha512=p.checksum_sha512,
                upload_date=p.upload_date.isoformat() if p.upload_date else None,
            )
            for p in Package.objects.filter(repo__repo_uid=self.repo_uid)
        ]

        self.config = RepoConfig(
            storage_path=settings.STORAGE_PATH,
            repo_www_path=settings.REPO_WWW_PATH,
            keyring_path=settings.KEYRING_PATH,
            deb_db_path=getattr(settings, "DEB_DB_PATH", ""),
            rpm_cache_dir=getattr(settings, "RPM_CACHE_DIR", ""),
        )

        self.signing_key = None
        if repo_db_obj.signing_key:
            self.signing_key = SigningKeyInfo(
                fingerprint=repo_db_obj.signing_key.fingerprint,
                public_key_pem=repo_db_obj.signing_key.public_key_pem,
                passphrase=repo_db_obj.signing_key.passphrase,
                private_key_pem=repo_db_obj.signing_key.private_key_pem,
            )

        # Lightweight no-op build logger
        class _NoopBuildLogger:
            def write(self, command, message="", loglevel="info", is_complete=True):
                class _Line:
                    pass
                return _Line()
            def section(self, command, loglevel="info"):
                @contextlib.contextmanager
                def _noop():
                    class _Entry:
                        def set_message(self, m): pass
                        def set_loglevel(self, l): pass
                    yield _Entry()
                return _noop()

        self.build_logger = _NoopBuildLogger()
        self.signer = None

    def set_build(self, build):
        """Attach a Django Build record and switch to a real build logger.

        Used by legacy code / tests that set ``adapter.build`` after construction.
        """
        from adapters.repo.django_build_logger import DjangoBuildLogger
        self.build_logger = DjangoBuildLogger(build, self.repo_uid)

    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        # Auto-upgrade to a real build logger when a Build object is assigned
        if name == "build" and value is not None and hasattr(value, "pk"):
            self.set_build(value)

    # ------------------------------------------------------------------
    # Build-log helpers (delegate to the injected build_logger)
    # ------------------------------------------------------------------

    def _buildlog_write(self, command, message="", loglevel=BUILDLOG_INFO, is_complete=True):
        return self.build_logger.write(command, message, loglevel, is_complete)

    def _buildlog_section(self, command, loglevel=BUILDLOG_INFO):
        return self.build_logger.section(command, loglevel)

    # ------------------------------------------------------------------
    # Package file management
    # ------------------------------------------------------------------

    def _copy_packages(self, dest_dir, packages=None):
        """Symlink packages into *dest_dir*.

        If *packages* is ``None``, ``self.packages`` is used.
        """
        if packages is None:
            packages = self.packages

        with self._buildlog_section(f"Symlinking {len(packages)} packages") as log_entry:
            for package in packages:
                # Support both PackageInfo (string attr) and Django Package model (method)
                rel_path = package.relative_path
                if callable(rel_path):
                    rel_path = rel_path()
                src_sym = os.path.join(self.config.storage_path, rel_path)
                ext = os.path.splitext(package.filename)[1]
                pool_name = f"{package.package_name}_{package.version}_{package.architecture}{ext}"
                dst_sym = os.path.join(dest_dir, pool_name)
                logger.debug("Symlinking %s to %s", src_sym, dst_sym)
                if not os.path.isfile(src_sym):
                    log_entry.set_message(f"Unable to find source package file {src_sym}")
                    continue

                if os.path.lexists(dst_sym):
                    os.unlink(dst_sym)

                os.symlink(src_sym, dst_sym)

    # ------------------------------------------------------------------
    # Abstract methods — subclasses must implement
    # ------------------------------------------------------------------

    def _generate_repo_structure(self, repo_path):
        """Generate repository metadata into *repo_path*.

        Must be implemented by each subclass.  Return ``True`` on success.
        """
        raise NotImplementedError("Subclasses must implement _generate_repo_structure()")

    def _get_repo_instructions(self):
        """Return user-facing instructions for configuring the repo."""
        raise NotImplementedError("Subclasses must implement _get_repo_instructions()")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _clean_old_dirs(self, cur_repo_dir):
        alldirs = os.listdir(self.config.repo_www_path)
        prefix = f"{self.repo_uid}."
        for d in alldirs:
            if d.startswith(prefix) and d != cur_repo_dir:
                suffix = d[len(prefix):]
                if suffix.isdigit():
                    fullpath = os.path.join(self.config.repo_www_path, d)
                    logger.debug("Removing old repo dir %s", fullpath)
                    shutil.rmtree(fullpath)

    def _save_public_key(self, repo_path):
        """Export the public key to the repo for convenience."""
        with self._buildlog_section("Updating PGP keys"):
            pgp_output_path = os.path.join(repo_path, "public.gpg")
            with open(pgp_output_path, "w") as outf:
                self._buildlog_write(f"Writing PGP key to {pgp_output_path}")
                outf.write(self.signing_key.public_key_pem)

    def _execute_commands(self, commands, repo_path):
        """Execute a list of commands without invoking a shell.

        Each element of *commands* is a ``(args, output_file)`` tuple:

        * *args* — a list of strings (the program and its arguments).
        * *output_file* — ``None``, or a path **relative to repo_path**.

        Returns ``True`` if every command succeeds, ``False`` on the first
        non-zero exit code.
        """
        working_dir = repo_path
        custom_env = os.environ.copy()
        custom_env["GNUPGHOME"] = self.config.keyring_path

        for args, output_file in commands:
            display_cmd = " ".join(args)
            if output_file:
                display_cmd += f" > {output_file}"
            with self._buildlog_section(display_cmd) as log_entry:
                try:
                    proc_status = subprocess.run(
                        args,
                        cwd=working_dir,
                        env=custom_env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        timeout=self.SUBPROCESS_TIMEOUT,
                    )
                except subprocess.TimeoutExpired:
                    log_entry.set_message(
                        f"Command timed out after {self.SUBPROCESS_TIMEOUT}s"
                    )
                    log_entry.set_loglevel(self.BUILDLOG_ERROR)
                    return False

                if output_file:
                    output_path = os.path.join(repo_path, output_file)
                    with open(output_path, "w") as f:
                        f.write(proc_status.stdout)
                    log_entry.set_message(f"Wrote {output_file}")
                else:
                    log_entry.set_message(proc_status.stdout)

                if proc_status.returncode != 0:
                    log_entry.set_loglevel(self.BUILDLOG_WARNING)
                    return False

        return True

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def setup_repo(self):
        """Generate repo structure.  Returns ``True`` on success.

        The caller (orchestrator) is responsible for creating the Build
        record and updating the Repository model.
        """
        # Ensure PGP key is prepped and ready
        if self.signing_key is not None and self.signer is not None:
            self.signer.ensure_key(self.signing_key)

        success = False
        try:
            # The orchestrator already incremented refresh_count; we need to
            # compute the dirname from the repo_www_path listing.
            existing = []
            prefix = f"{self.repo_uid}."
            if os.path.isdir(self.config.repo_www_path):
                for d in os.listdir(self.config.repo_www_path):
                    if d.startswith(prefix):
                        suffix = d[len(prefix):]
                        if suffix.isdigit():
                            existing.append(int(suffix))
            next_num = (max(existing) + 1) if existing else 1

            dirname = f"{self.repo_uid}.{next_num:=09}"
            dest_dir = os.path.join(self.config.repo_www_path, dirname)

            if os.path.exists(dest_dir):
                with self._buildlog_section(f"Removing old directory path {dest_dir}"):
                    shutil.rmtree(dest_dir)

            os.makedirs(dest_dir)

            self._buildlog_write(f"Generating repo structure {dest_dir}")
            success = self._generate_repo_structure(dest_dir)
            self._buildlog_write(f"Create repo complete {dest_dir}", str(success))

            if success:
                with self._buildlog_section(f"Updating repo symlink to point to {dirname}"):
                    repo_uid_symlink = os.path.join(self.config.repo_www_path, self.repo_uid)
                    if os.path.exists(repo_uid_symlink):
                        os.unlink(repo_uid_symlink)
                    os.symlink(dirname, repo_uid_symlink)

                with self._buildlog_section(f"Cleaning old directories in {self.config.repo_www_path}"):
                    self._clean_old_dirs(dirname)

        except Exception as e:
            self._buildlog_write(
                f"Exception processing repo {self.repo_uid}",
                str(e),
                loglevel=self.BUILDLOG_ERROR,
            )
            success = False

        return success
