"""Orchestrates repo generation — bridges Django ORM and the adapter layer.

This is the *only* module that touches both the Django ORM **and** the repo
adapters.  It assembles the injected dependencies (``PackageInfo`` list,
``RepoConfig``, ``DjangoBuildLogger``, ``PGPSigner``) and calls the
adapter's ``setup_repo()`` method.
"""
import logging
import time

from django.conf import settings
from django.db.models import F

from repo.models import Build, Package, Repository
from repo.storage.signer import PGPSigner

from .django_build_logger import DjangoBuildLogger
from .types import PackageInfo, RepoConfig, SigningKeyInfo

logger = logging.getLogger("openrepo_web")


def build_repo(repo_uid: str) -> bool:
    """Full repo rebuild: query packages, create build record, run adapter.

    Returns ``True`` on success, ``False`` on failure.
    """
    repo = Repository.objects.get(repo_uid=repo_uid)

    adapter_cls = _get_adapter_class(repo.repo_type)
    if adapter_cls is None:
        logger.error("No adapter for repo type '%s'", repo.repo_type)
        return False

    # Snapshot package data — no lazy QuerySet leaking into the adapter
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
        for p in Package.objects.filter(repo__repo_uid=repo_uid)
    ]

    config = RepoConfig(
        storage_path=settings.STORAGE_PATH,
        repo_www_path=settings.REPO_WWW_PATH,
        keyring_path=settings.KEYRING_PATH,
        deb_db_path=getattr(settings, "DEB_DB_PATH", ""),
        rpm_cache_dir=getattr(settings, "RPM_CACHE_DIR", ""),
    )

    # Signing key
    signing_key = None
    signer = None
    if repo.signing_key:
        signing_key = SigningKeyInfo(
            fingerprint=repo.signing_key.fingerprint,
            public_key_pem=repo.signing_key.public_key_pem,
            passphrase=repo.signing_key.passphrase,
            private_key_pem=repo.signing_key.private_key_pem,
        )
        signer = PGPSigner()

    # Atomically increment refresh_count
    Repository.objects.filter(repo_uid=repo_uid).update(
        refresh_count=F("refresh_count") + 1,
    )
    repo.refresh_from_db()

    # Create Build record
    build = Build.objects.create(
        repo=repo,
        build_number=repo.refresh_count,
        completion_status=Build.STATUS_RUNNING,
    )
    build_logger = DjangoBuildLogger(build, repo_uid)

    # Instantiate and run adapter
    adapter = adapter_cls(
        repo_uid=repo_uid,
        packages=packages,
        config=config,
        build_logger=build_logger,
        signing_key=signing_key,
        signer=signer,
        base_url=f"<origin>/{repo_uid}",
        multi_arch=repo.multi_arch,
    )

    start = time.time()
    success = adapter.setup_repo()

    build.completion_status = (
        Build.STATUS_COMPLETE_SUCCESS if success
        else Build.STATUS_COMPLETE_ERROR
    )
    build.total_duration_sec = time.time() - start
    build.save()

    return success


def _get_adapter_class(repo_type):
    from adapters.registry import REPO_ADAPTERS
    return REPO_ADAPTERS.get(repo_type)
