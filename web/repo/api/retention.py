import logging
from datetime import datetime, timedelta, timezone

from repo.models import Package, Repository

logger = logging.getLogger("openrepo_web")


def apply_retention_policy(repo, package_name, architecture):
    """
    Enforce the repository's retention policy for a single (package_name, architecture) group.

    Called after every upload and during nightly sweeps.  Packages are only
    deleted from *this* repo; the underlying file is removed from disk only
    when no other repo still references the same package_uid (handled by the
    existing post_delete signal on Package).

    Q4 A: packages that exist in at least one other repo are left untouched —
    we never delete a package that another repo depends on.
    """
    policy = repo.retention_policy

    if policy == Repository.RETENTION_NONE:
        return

    # Full queryset for this (repo, package_name, architecture) group,
    # newest first by upload_date.
    candidates = list(
        Package.objects.filter(
            repo=repo,
            package_name=package_name,
            architecture=architecture,
        ).order_by("-upload_date")
    )

    if not candidates:
        return

    to_delete = _packages_to_delete(repo, policy, candidates)

    # Q4 A: never delete a package whose package_uid is referenced by another repo.
    safe_to_delete = [
        pkg for pkg in to_delete
        if not Package.objects.filter(package_uid=pkg.package_uid)
        .exclude(repo=repo)
        .exists()
    ]

    if safe_to_delete:
        uids = [p.package_uid for p in safe_to_delete]
        logger.info(
            f"Retention policy '{policy}' removing {len(safe_to_delete)} package(s) "
            f"from repo '{repo.repo_uid}': {uids}"
        )
        for pkg in safe_to_delete:
            pkg.delete()


def apply_retention_policy_repo(repo):
    """
    Apply retention policy across every (package_name, architecture) group in a repo.
    Used by the nightly background sweep.
    """
    if repo.retention_policy == Repository.RETENTION_NONE:
        return

    groups = (
        Package.objects.filter(repo=repo)
        .values_list("package_name", "architecture")
        .distinct()
    )
    for package_name, architecture in groups:
        apply_retention_policy(repo, package_name, architecture)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _packages_to_delete(repo, policy, candidates):
    """
    Return the subset of *candidates* (sorted newest-first) that should be
    removed according to *policy*.  Candidates must all belong to the same
    (repo, package_name, architecture) group.
    """
    if policy == Repository.RETENTION_KEEP_LATEST_N:
        return _over_count(candidates, repo.retention_keep_count)

    if policy == Repository.RETENTION_MAX_AGE_DAYS:
        return _over_age(candidates, repo.retention_max_age_days)

    if policy == Repository.RETENTION_KEEP_LATEST_N_AND_AGE:
        # Union: delete if over count OR over age.
        by_count = set(_over_count(candidates, repo.retention_keep_count))
        by_age = set(_over_age(candidates, repo.retention_max_age_days))
        return list(by_count | by_age)

    return []


def _over_count(candidates, keep_count):
    """Return packages beyond the first *keep_count* (candidates sorted newest-first)."""
    if not keep_count or keep_count < 1:
        return []
    return candidates[keep_count:]


def _over_age(candidates, max_age_days):
    """Return packages whose upload_date is older than *max_age_days* days ago."""
    if not max_age_days or max_age_days < 1:
        return []
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=max_age_days)
    return [p for p in candidates if p.upload_date < cutoff]
