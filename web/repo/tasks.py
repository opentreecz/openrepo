"""Celery tasks for OpenRepo background processing.

These tasks replace the homegrown threading-based worker (``bgworker.py``)
with Celery's managed task queue, providing retry logic, rate limiting,
monitoring, and horizontal scaling.
"""
import logging
import threading

from celery import shared_task
from django.db import close_old_connections

logger = logging.getLogger("openrepo_web")


def _process_upload_in_thread(task_id):
    from repo.api.upload_processor import process_upload
    try:
        process_upload(task_id)
    finally:
        close_old_connections()


def dispatch_upload_processing(task_id):
    """Queue background processing of a stored upload.

    Normally the work is handed to a Celery worker through the broker
    (Redis).  If the broker cannot be reached (Redis not running, wrong
    ``OPENREPO_REDIS_URL``, ...) the upload is processed in a local
    background thread instead of failing the request with HTTP 500, so the
    client can still poll ``/api/upload-status/<task_id>/``.

    Returns ``"celery"`` or ``"thread"`` depending on the path taken.
    """
    try:
        process_upload_task.delay(task_id)
        return "celery"
    except Exception as exc:  # kombu.exceptions.OperationalError, redis errors, DNS errors
        logger.warning(
            "Celery broker unavailable (%s); processing upload %s in-process. "
            "Check OPENREPO_REDIS_URL and that the redis and worker services are running.",
            exc, task_id,
        )
        threading.Thread(
            target=_process_upload_in_thread,
            args=(task_id,),
            name=f"upload-{task_id}",
            daemon=True,
        ).start()
        return "thread"


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def process_upload_task(self, task_id):
    """Process an uploaded package file.

    Replaces: ``threading.Thread(target=process_upload)`` in ``views.py``.
    """
    close_old_connections()
    from repo.api.upload_processor import process_upload
    process_upload(task_id)


def enqueue_rebuild(repo_uid, countdown=0):
    """Dispatch a rebuild of *repo_uid* unless one is already queued.

    Returns ``True`` if a task was dispatched.  Duplicate dispatches are
    cheap anyway (the task skips when the repo is already being rebuilt),
    but de-duplicating here keeps the queue from filling with redundant
    rebuilds that delay upload processing.
    """
    from repo.locks import clear_rebuild_queued, mark_rebuild_queued

    if not mark_rebuild_queued(repo_uid):
        return False
    try:
        rebuild_repo_task.apply_async(
            args=[repo_uid],
            task_id=f"rebuild-{repo_uid}",
            countdown=countdown,
        )
    except Exception:
        clear_rebuild_queued(repo_uid)
        raise
    return True


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def rebuild_repo_task(self, repo_uid):
    """Rebuild repository metadata.

    Only one rebuild per repo runs at a time (``repo.locks``).  If another
    rebuild is in progress this task exits immediately; the repo keeps its
    ``is_stale`` flag and ``check_stale_repos`` dispatches a fresh rebuild
    once the running one has finished.
    """
    close_old_connections()
    from adapters.repo.orchestrator import build_repo
    from repo.locks import clear_rebuild_queued, repo_build_lock
    from repo.models import Repository

    clear_rebuild_queued(repo_uid)
    with repo_build_lock(repo_uid) as acquired:
        if not acquired:
            logger.info("Rebuild of '%s' already in progress; skipping duplicate", repo_uid)
            return
        if not Repository.objects.filter(repo_uid=repo_uid).exists():
            logger.info("Repo '%s' was deleted before rebuild. Skipping.", repo_uid)
            return
        # Clear the flag *before* building: packages added while the build
        # runs set it again, so their changes trigger another rebuild.
        Repository.objects.filter(repo_uid=repo_uid).update(is_stale=False)
        try:
            success = build_repo(repo_uid)
        except Repository.DoesNotExist:
            logger.info("Repo '%s' was deleted before rebuild. Skipping.", repo_uid)
            return
        except Exception:
            logger.exception("Repo rebuild crashed for '%s'", repo_uid)
            success = False

    if not success:
        logger.warning("Repo rebuild failed for '%s'", repo_uid)
        if self.request.retries >= self.max_retries:
            # Give up for now; leave it stale so a later pass retries.
            Repository.objects.filter(repo_uid=repo_uid).update(is_stale=True)
            return
        raise self.retry(exc=RuntimeError(f"Repo build failed: {repo_uid}"))


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
    from repo.locks import is_build_running

    for repo_uid in stale_repos:
        if is_build_running(repo_uid):
            continue
        enqueue_rebuild(repo_uid)
