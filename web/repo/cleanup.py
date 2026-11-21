# SPDX-License-Identifier: AGPL-3.0-only
"""Storage and database cleanup ("garbage collection") for OpenRepo.

Package files are normally removed by the ``post_delete`` signal on
:class:`repo.models.Package`, but several paths leave unused data behind:

* uploads whose background processing was lost (task stuck in
  ``uploading``/``stored``/``processing``) keep their stored file forever;
* files written before a crash, or left by older releases, are referenced
  by nothing at all;
* builds killed mid-run stay ``running`` in the database;
* failed builds leave ``<repo>.<N>`` directories in the publish tree,
  because old directories are only removed after a *successful* build;
* upload-task and build history grows without bound.

:func:`run_cleanup` handles all of these.  It is dry-run by default and only
ever deletes data that nothing references:

* a storage file is kept if any ``Package`` row, any in-flight upload task or
  any published pool symlink points at it, or if it is younger than the
  grace period (an upload writes its file *before* creating the task row);
* a publish directory is kept if its repo symlink points at it, if a build of
  that repo is running, or if it is younger than the grace period; publish
  trees of repos that no longer exist in the database are only reported;
* the latest build of every repo is always kept.

Entry points: ``manage.py cleanup``, the periodic ``repo.tasks.cleanup_task``
and ``POST /api/cleanup/``.
"""
import contextlib
import fcntl
import logging
import os
import re
import shutil
import time
from dataclasses import asdict, dataclass, field
from datetime import timedelta

from django.conf import settings
from django.db.models import Max
from django.utils import timezone

logger = logging.getLogger("openrepo_web")

ACTIVE_UPLOAD_STATUSES = ("uploading", "stored", "processing")
ABANDONED_UPLOAD_MESSAGE = "Abandoned: upload was never processed; stored file removed by cleanup"
STALE_BUILD_MESSAGE = "Marked failed by cleanup: build was no longer running"

_PUBLISH_DIR_RE = re.compile(r"^(?P<uid>.+)\.(?P<num>\d+)$")


def _env_int(name, default):
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass
class CleanupOptions:
    dry_run: bool = True
    # Minimum age before files, upload tasks, builds and publish dirs are
    # considered abandoned.
    grace_hours: int = field(default_factory=lambda: _env_int("OPENREPO_CLEANUP_GRACE_HOURS", 24))
    # Finished upload tasks and builds older than this are deleted (0 = keep).
    history_days: int = field(default_factory=lambda: _env_int("OPENREPO_CLEANUP_HISTORY_DAYS", 90))


@dataclass
class CleanupReport:
    dry_run: bool = True
    abandoned_uploads: int = 0
    stale_builds: int = 0
    orphan_files: int = 0
    orphan_bytes: int = 0
    empty_dirs: int = 0
    stale_publish_dirs: list = field(default_factory=list)
    unmanaged_publish_dirs: list = field(default_factory=list)
    old_upload_tasks: int = 0
    old_builds: int = 0
    skipped: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    def as_dict(self):
        return asdict(self)

    def summary(self):
        verb = "would remove" if self.dry_run else "removed"
        return (
            f"cleanup ({'dry-run' if self.dry_run else 'apply'}): {verb} "
            f"{self.orphan_files} orphan file(s) ({self.orphan_bytes / 1e9:.2f} GB), "
            f"{len(self.stale_publish_dirs)} stale publish dir(s), "
            f"{self.empty_dirs} empty dir(s); "
            f"abandoned uploads={self.abandoned_uploads}, stale builds={self.stale_builds}, "
            f"old upload tasks={self.old_upload_tasks}, old builds={self.old_builds}, "
            f"unmanaged publish dirs={len(self.unmanaged_publish_dirs)}, errors={len(self.errors)}"
        )


class CleanupBusy(Exception):
    """Another cleanup run holds the cleanup lock."""


@contextlib.contextmanager
def _cleanup_lock():
    locks_dir = os.path.join(settings.OPENREPO_VAR_DIR, "locks")
    os.makedirs(locks_dir, exist_ok=True)
    fd = os.open(os.path.join(locks_dir, "cleanup.lock"), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise CleanupBusy("A cleanup run is already in progress")
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _storage_relpath(path):
    """Return *path* relative to STORAGE_PATH, or ``None`` if it is outside."""
    storage = os.path.realpath(settings.STORAGE_PATH)
    real = os.path.realpath(path) if os.path.isabs(path) else os.path.realpath(
        os.path.join(storage, path)
    )
    if real == storage or not real.startswith(storage + os.sep):
        return None
    return os.path.relpath(real, storage)


def _older_than(path, cutoff_ts):
    try:
        return os.lstat(path).st_mtime < cutoff_ts
    except FileNotFoundError:
        return False


def _published_targets():
    """Storage paths referenced by symlinks anywhere in the publish tree."""
    targets = set()
    www = settings.REPO_WWW_PATH
    if not os.path.isdir(www):
        return targets
    for root, dirs, files in os.walk(www):
        for name in files + dirs:
            path = os.path.join(root, name)
            if os.path.islink(path) and os.path.normpath(root) != os.path.normpath(www):
                rel = _storage_relpath(os.path.join(root, os.readlink(path)))
                if rel:
                    targets.add(rel)
    return targets


def _referenced_files(cutoff):
    """Storage paths that must be kept.

    Upload tasks older than *cutoff* are abandoned and no longer protect
    their stored file.
    """
    from repo.models import Package, UploadTask

    referenced = {
        uid.replace("-", "/")
        for uid in Package.objects.values_list("package_uid", flat=True).distinct()
    }
    for stored_path in UploadTask.objects.filter(
        status__in=ACTIVE_UPLOAD_STATUSES, created_at__gte=cutoff
    ).values_list("stored_path", flat=True):
        rel = _storage_relpath(stored_path)
        if rel:
            referenced.add(rel)
    referenced |= _published_targets()
    return referenced


def _abandoned_uploads(opts, report, cutoff):
    """Mark upload tasks that never finished as failed.

    Their stored files are removed by :func:`_orphan_files`.
    """
    from repo.models import UploadTask

    stale = UploadTask.objects.filter(status__in=ACTIVE_UPLOAD_STATUSES, created_at__lt=cutoff)
    for task in stale:
        report.abandoned_uploads += 1
        if opts.dry_run:
            continue
        task.status = "failed"
        task.error_message = ABANDONED_UPLOAD_MESSAGE
        task.completed_at = timezone.now()
        task.save(update_fields=["status", "error_message", "completed_at"])


def _stale_builds(opts, report, cutoff):
    from repo.locks import is_build_running
    from repo.models import Build

    running = Build.objects.filter(
        completion_status=Build.STATUS_RUNNING, timestamp__lt=cutoff
    ).select_related("repo")
    for build in running:
        newer_exists = Build.objects.filter(repo=build.repo, id__gt=build.id).exists()
        if not newer_exists and is_build_running(build.repo.repo_uid):
            continue
        report.stale_builds += 1
        if not opts.dry_run:
            build.completion_status = Build.STATUS_COMPLETE_ERROR
            build.save(update_fields=["completion_status"])
            logger.info("cleanup: %s build #%s: %s", build.repo.repo_uid, build.build_number,
                        STALE_BUILD_MESSAGE)


def _orphan_files(opts, report, cutoff, cutoff_ts):
    storage = settings.STORAGE_PATH
    if not os.path.isdir(storage):
        return
    referenced = _referenced_files(cutoff)
    for root, _dirs, files in os.walk(storage):
        for name in files:
            path = os.path.join(root, name)
            if os.path.islink(path):
                continue
            rel = os.path.relpath(path, storage)
            if rel in referenced or not _older_than(path, cutoff_ts):
                continue
            try:
                size = os.path.getsize(path)
                if not opts.dry_run:
                    os.remove(path)
            except FileNotFoundError:
                continue
            except OSError as exc:
                report.errors.append(f"{rel}: {exc}")
                continue
            report.orphan_files += 1
            report.orphan_bytes += size

    # Remove empty prefix directories left behind (bottom-up, never the root).
    for root, dirs, files in os.walk(storage, topdown=False):
        if os.path.normpath(root) == os.path.normpath(storage):
            continue
        if not files and not any(os.path.exists(os.path.join(root, d)) for d in dirs):
            report.empty_dirs += 1
            if not opts.dry_run:
                with contextlib.suppress(OSError):
                    os.rmdir(root)


def _publish_dirs(opts, report, cutoff_ts):
    from repo.locks import repo_build_lock
    from repo.models import Repository

    www = settings.REPO_WWW_PATH
    if not os.path.isdir(www):
        return
    known = set(Repository.objects.values_list("repo_uid", flat=True))
    entries = sorted(os.listdir(www))
    live = {}
    for name in entries:
        path = os.path.join(www, name)
        if os.path.islink(path):
            live[name] = os.path.basename(os.path.normpath(os.readlink(path)))

    for name in entries:
        path = os.path.join(www, name)
        if os.path.islink(path) or not os.path.isdir(path):
            continue
        match = _PUBLISH_DIR_RE.match(name)
        if not match:
            continue
        uid = match.group("uid")
        if uid not in known:
            report.unmanaged_publish_dirs.append(name)
            continue
        if live.get(uid) == name or not _older_than(path, cutoff_ts):
            continue
        # Hold the repo's build lock so a build starting right now cannot
        # pick this directory up while it is being removed.
        with repo_build_lock(uid) as acquired:
            if not acquired:
                report.skipped.append(f"{name}: build of '{uid}' in progress")
                continue
            report.stale_publish_dirs.append(name)
            if not opts.dry_run:
                try:
                    shutil.rmtree(path)
                except OSError as exc:
                    report.errors.append(f"{name}: {exc}")


def _history(opts, report):
    from repo.models import Build, UploadTask

    if opts.history_days <= 0:
        return
    cutoff = timezone.now() - timedelta(days=opts.history_days)
    old_tasks = UploadTask.objects.exclude(status__in=ACTIVE_UPLOAD_STATUSES).filter(
        created_at__lt=cutoff
    )
    latest_ids = Build.objects.values("repo").annotate(latest=Max("id")).values_list(
        "latest", flat=True
    )
    old_builds = Build.objects.exclude(completion_status=Build.STATUS_RUNNING).exclude(
        id__in=list(latest_ids)
    ).filter(timestamp__lt=cutoff)
    report.old_upload_tasks = old_tasks.count()
    report.old_builds = old_builds.count()
    if not opts.dry_run:
        old_tasks.delete()
        old_builds.delete()


def run_cleanup(options=None):
    """Run every cleanup step and return a :class:`CleanupReport`.

    Raises :class:`CleanupBusy` if another cleanup run is in progress.
    """
    opts = options or CleanupOptions()
    report = CleanupReport(dry_run=opts.dry_run)
    grace = timedelta(hours=max(opts.grace_hours, 0))
    cutoff = timezone.now() - grace
    cutoff_ts = time.time() - grace.total_seconds()

    with _cleanup_lock():
        for step in (
            lambda: _abandoned_uploads(opts, report, cutoff),
            lambda: _stale_builds(opts, report, cutoff),
            lambda: _orphan_files(opts, report, cutoff, cutoff_ts),
            lambda: _publish_dirs(opts, report, cutoff_ts),
            lambda: _history(opts, report),
        ):
            try:
                step()
            except Exception as exc:  # keep going; report what failed
                logger.exception("cleanup step failed")
                report.errors.append(str(exc))

    logger.info(report.summary())
    return report
