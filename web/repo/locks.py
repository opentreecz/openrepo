"""Cross-process coordination for repository rebuilds.

Repository rebuilds must never run concurrently for the same repo: builds
pick the next ``<repo>.<N>`` directory from a listing and remove older
directories when done, so two overlapping builds collide on the same
directory or delete the one the other is still writing (``No such file or
directory: .../dists/stable/main/Contents-any``).

The lock is an ``flock`` on a file in ``OPENREPO_VAR_DIR/locks``.  That
directory lives on the shared data volume, so the lock is honoured by every
worker process and by every container that mounts the volume.
"""
import contextlib
import fcntl
import logging
import os
import re
import time

from django.conf import settings

logger = logging.getLogger("openrepo_web")

# A queued-rebuild marker older than this is considered stale (e.g. the
# worker died before picking the task up) and no longer blocks dispatch.
QUEUED_MARKER_TTL_SEC = int(os.getenv("OPENREPO_REBUILD_QUEUED_TTL", "300"))


def _locks_dir():
    path = os.path.join(settings.OPENREPO_VAR_DIR, "locks")
    os.makedirs(path, exist_ok=True)
    return path


def _safe_name(repo_uid):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(repo_uid))


def _lock_path(repo_uid):
    return os.path.join(_locks_dir(), f"rebuild-{_safe_name(repo_uid)}.lock")


def _queued_path(repo_uid):
    return os.path.join(_locks_dir(), f"rebuild-{_safe_name(repo_uid)}.queued")


@contextlib.contextmanager
def repo_build_lock(repo_uid, blocking=False, timeout=None):
    """Hold the exclusive rebuild lock for *repo_uid*.

    Yields ``True`` when the lock was acquired, ``False`` otherwise.

    * ``blocking=False`` (default): try once.
    * ``timeout=N``: keep trying for up to *N* seconds.
    * ``blocking=True`` without a timeout: wait indefinitely.
    """
    fd = os.open(_lock_path(repo_uid), os.O_RDWR | os.O_CREAT, 0o644)
    acquired = False
    try:
        if blocking and timeout is None:
            fcntl.flock(fd, fcntl.LOCK_EX)
            acquired = True
        else:
            deadline = time.monotonic() + (timeout or 0)
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        break
                    time.sleep(0.2)
        yield acquired
    finally:
        if acquired:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def is_build_running(repo_uid):
    """Return True if a rebuild of *repo_uid* currently holds the lock."""
    with repo_build_lock(repo_uid) as acquired:
        return not acquired


def mark_rebuild_queued(repo_uid):
    """Record that a rebuild is queued.

    Returns ``False`` if a fresh marker already exists (a rebuild is
    already waiting in the queue), ``True`` if the caller should dispatch.
    """
    path = _queued_path(repo_uid)
    try:
        age = time.time() - os.path.getmtime(path)
        if age < QUEUED_MARKER_TTL_SEC:
            return False
    except FileNotFoundError:
        pass
    with open(path, "w") as f:
        f.write(str(time.time()))
    return True


def clear_rebuild_queued(repo_uid):
    try:
        os.remove(_queued_path(repo_uid))
    except FileNotFoundError:
        pass
