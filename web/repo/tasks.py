"""Celery tasks for OpenRepo background processing.

These tasks replace the homegrown threading-based worker (``bgworker.py``)
with Celery's managed task queue, providing retry logic, rate limiting,
monitoring, and horizontal scaling.
"""
import logging

from celery import shared_task
from django.db import close_old_connections

logger = logging.getLogger("openrepo_web")


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def process_upload_task(self, task_id):
    """Process an uploaded package file.

    Replaces: ``threading.Thread(target=process_upload)`` in ``views.py``.
    """
    close_old_connections()
    from repo.api.upload_processor import process_upload
    process_upload(task_id)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def rebuild_repo_task(self, repo_uid):
    """Rebuild repository metadata.

    Replaces: ``BackgroundWorker.run()`` logic in ``bgworker.py``.
    Deduplication: use ``task_id=f"rebuild-{repo_uid}"`` when dispatching
    to prevent concurrent rebuilds of the same repo.
    """
    close_old_connections()
    from adapters.repo.orchestrator import build_repo
    from repo.models import Repository

    try:
        success = build_repo(repo_uid)
        if success:
            Repository.objects.filter(repo_uid=repo_uid).update(is_stale=False)
        else:
            logger.warning("Repo rebuild failed for '%s'", repo_uid)
            raise self.retry(exc=RuntimeError(f"Repo build failed: {repo_uid}"))
    except Repository.DoesNotExist:
        logger.info("Repo '%s' was deleted before rebuild. Skipping.", repo_uid)


@shared_task
def retention_sweep():
    """Nightly retention policy sweep across all repos.

    Replaces: ``BackgroundWorker._run_retention_sweep()`` in ``bgworker.py``.
    """
    close_old_connections()
    from repo.api.retention import apply_retention_policy_repo
    from repo.models import Repository

    repos = Repository.objects.exclude(retention_policy=Repository.RETENTION_NONE)
    count = repos.count()
    if count == 0:
        return
    logger.info("Retention sweep: checking %d repo(s)", count)
    for repo in repos:
        try:
            apply_retention_policy_repo(repo)
        except Exception:
            logger.exception("Retention sweep failed for repo %s", repo.repo_uid)


@shared_task
def check_stale_repos():
    """Poll for stale repos and dispatch rebuild tasks.

    Replaces: the polling loop in ``runworker.py``.
    """
    close_old_connections()
    from repo.models import Repository

    stale_repos = Repository.objects.filter(is_stale=True).values_list(
        "repo_uid", flat=True
    )
    for repo_uid in stale_repos:
        rebuild_repo_task.apply_async(
            args=[repo_uid],
            task_id=f"rebuild-{repo_uid}",
        )
