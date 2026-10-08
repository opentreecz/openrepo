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

from .deb_repo import DebRepoAdapter  # noqa: F401
from .generic_repo import GenericRepoAdapter  # noqa: F401
from .orchestrator import build_repo  # noqa: F401
from .rpm_repo import RpmRepoAdapter  # noqa: F401
from .types import PackageInfo, RepoConfig, SigningKeyInfo


def get_repo_adapter_class(repo_type):
    """Return the adapter *class* for the given repo type string."""
    from adapters.registry import REPO_ADAPTERS
    return REPO_ADAPTERS.get(repo_type)


def get_repo_adapter(repo_obj):
    """Return an instantiated repo adapter for a Django Repository model.

    This is a backward-compatible convenience wrapper.  New code should
    prefer ``build_repo()`` (the orchestrator) instead.
    """
    from django.conf import settings
    from repo.models import Package

    adapter_cls = get_repo_adapter_class(repo_obj.repo_type)
    if adapter_cls is None:
        raise ValueError(f"Unknown repo type: {repo_obj.repo_type!r}")

    packages = [
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
        for p in Package.objects.filter(repo__repo_uid=repo_obj.repo_uid)
    ]

    config = RepoConfig(
        storage_path=settings.STORAGE_PATH,
        repo_www_path=settings.REPO_WWW_PATH,
        keyring_path=settings.KEYRING_PATH,
        deb_db_path=getattr(settings, "DEB_DB_PATH", ""),
        rpm_cache_dir=getattr(settings, "RPM_CACHE_DIR", ""),
    )

    signing_key = None
    if repo_obj.signing_key:
        signing_key = SigningKeyInfo(
            fingerprint=repo_obj.signing_key.fingerprint,
            public_key_pem=repo_obj.signing_key.public_key_pem,
            passphrase=repo_obj.signing_key.passphrase,
            private_key_pem=repo_obj.signing_key.private_key_pem,
        )

    from .django_build_logger import DjangoBuildLogger
    from repo.models import Build

    # Lightweight no-op build logger for read-only usage (e.g. serializers
    # calling _get_repo_instructions).  A real build logger is created by
    # the orchestrator when actually generating repo metadata.
    class _NoopBuildLogger:
        def write(self, command, message="", loglevel="info", is_complete=True):
            class _Line:
                pass
            return _Line()
        def section(self, command, loglevel="info"):
            import contextlib
            @contextlib.contextmanager
            def _noop():
                class _Entry:
                    def set_message(self, m): pass
                    def set_loglevel(self, l): pass
                yield _Entry()
            return _noop()

    build_logger = _NoopBuildLogger()

    return adapter_cls(
        repo_uid=repo_obj.repo_uid,
        packages=packages,
        config=config,
        build_logger=build_logger,
        signing_key=signing_key,
        signer=None,
        base_url=f"<origin>/{repo_obj.repo_uid}",
        multi_arch=repo_obj.multi_arch,
    )
