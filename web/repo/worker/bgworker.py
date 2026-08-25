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
import signal
import threading
import time

from django.conf import settings
from django.db import close_old_connections

from adapters.repo import get_repo_adapter
from repo.api.retention import apply_retention_policy_repo
from repo.models import Repository

logger = logging.getLogger("openrepo_web")


class BackgroundWorker(threading.Thread):

    RETENTION_SWEEP_INTERVAL_SEC = 86400  # 24 hours
    FAILURE_BACKOFF_SEC = 60  # Skip a repo for 60s after repeated failures
    MAX_CONSECUTIVE_FAILURES = 3  # Number of failures before applying backoff

    def __init__(self, chore_list):
        self.stay_alive = True
        self._chore_list = chore_list
        self._last_retention_sweep = 0
        self._failure_counts = {}  # {repo_uid: {"count": int, "backoff_until": float}}
        threading.Thread.__init__(self)

    def stop(self):
        self.stay_alive = False

    def _setup_signal_handlers(self):
        """Register signal handlers for graceful shutdown (SIGTERM, SIGINT)."""
        def _handle_signal(signum, frame):
            sig_name = signal.Signals(signum).name
            logger.info(f"Received {sig_name}, initiating graceful shutdown...")
            self.stay_alive = False

        try:
            signal.signal(signal.SIGTERM, _handle_signal)
            signal.signal(signal.SIGINT, _handle_signal)
        except (ValueError, OSError):
            # Signal handling can only be set in the main thread.
            # If this is not the main thread, skip (e.g., during testing).
            pass

    def _should_skip_repo(self, repo_uid):
        """Check if a repo should be skipped due to failure backoff."""
        if repo_uid not in self._failure_counts:
            return False
        entry = self._failure_counts[repo_uid]
        if entry["count"] >= self.MAX_CONSECUTIVE_FAILURES:
            if time.time() < entry["backoff_until"]:
                return True
            # Backoff expired — allow retry
            del self._failure_counts[repo_uid]
        return False

    def _record_failure(self, repo_uid):
        """Record a failure for a repo and apply backoff if threshold reached."""
        if repo_uid not in self._failure_counts:
            self._failure_counts[repo_uid] = {"count": 0, "backoff_until": 0}
        self._failure_counts[repo_uid]["count"] += 1
        if self._failure_counts[repo_uid]["count"] >= self.MAX_CONSECUTIVE_FAILURES:
            self._failure_counts[repo_uid]["backoff_until"] = time.time() + self.FAILURE_BACKOFF_SEC
            logger.warning(
                f"Repo '{repo_uid}' has failed {self.MAX_CONSECUTIVE_FAILURES} times consecutively. "
                f"Backing off for {self.FAILURE_BACKOFF_SEC}s."
            )

    def _record_success(self, repo_uid):
        """Clear failure count on success."""
        self._failure_counts.pop(repo_uid, None)

    def _run_retention_sweep(self):
        """Apply retention policies across all repos that have a non-none policy."""
        close_old_connections()
        repos = Repository.objects.exclude(retention_policy=Repository.RETENTION_NONE)
        count = repos.count()
        if count == 0:
            return
        logger.info(f"Retention sweep: checking {count} repo(s)")
        for repo in repos:
            try:
                apply_retention_policy_repo(repo)
            except Exception:
                logger.exception(f"Retention sweep failed for repo {repo.repo_uid}")

    def run(self):
        self._setup_signal_handlers()
        logger.info(f"Starting bg worker thread {threading.current_thread().ident}")
        next_task_repo_uid = ""

        while self.stay_alive:

            try:
                # Nightly retention sweep
                if time.time() - self._last_retention_sweep >= self.RETENTION_SWEEP_INTERVAL_SEC:
                    self._run_retention_sweep()
                    self._last_retention_sweep = time.time()

                # Close stale DB connections before accessing the database
                close_old_connections()

                next_task_repo_uid = self._chore_list.get_next_task()

                if next_task_repo_uid is not None:

                    # Check if this repo is in backoff due to repeated failures
                    if self._should_skip_repo(next_task_repo_uid):
                        logger.debug(f"Skipping repo '{next_task_repo_uid}' (in backoff)")
                        self._chore_list.cleaning_done(next_task_repo_uid)
                        time.sleep(1.0)
                        continue

                    try:
                        logger.info(f"Worker triggering update of repo {next_task_repo_uid}")

                        repo = Repository.objects.get(repo_uid=next_task_repo_uid)
                        adapter = get_repo_adapter(repo)
                        adapter.setup_repo()

                        repo.is_stale = False
                        repo.save()
                        self._record_success(next_task_repo_uid)

                    except Repository.DoesNotExist:
                        logger.info(
                            f"Repo '{next_task_repo_uid}' was deleted before worker could process it. Skipping."
                        )
                    finally:
                        self._chore_list.cleaning_done(next_task_repo_uid)

            except Exception:
                logger.exception(f"Unhandled exception while processing repo {next_task_repo_uid}")
                if next_task_repo_uid:
                    self._record_failure(next_task_repo_uid)
            time.sleep(1.0)

        logger.info("Background worker shutting down gracefully.")


class ChoreList:
    """
    Keeps track of all repos that need to be refreshed.  We need to use this rather than a simple queue because
    while a repo is being recreated, we don't want to queue up multiple refreshes.  Only one is necessary at the end.
    For example, if 20 deb files are added in succession to a repo, we would refresh after the first one is added, and while the
    repo is being refreshed, the other 19 are added, we would then do another refresh again (i.e., 2 total refreshes instead of 20)

    The threads will ask the class for the next item on the list by oldest timestamp that is not being cleaned.

    The manager will add new items to the list, but if something is already on the list, it won't modify

    When the job first starts, it will signal the repo as no longer dirty and start refreshing.
    If a new file comes in, it will flag the repo as dirty so that refresh can happen again.
     After the job is complete, the thread will notify the list to remove the entry so subsequent refreshes can be added for that repo
    """

    def __init__(self):
        # Map will be:
        # {repo_uid: {is_being_cleaned, insert_timestamp}
        self._repo_state = {}
        self._lock = threading.Lock()

    def set_needs_clean(self, repo_uid):

        try:
            self._lock.acquire()

            if repo_uid not in self._repo_state:
                self._repo_state[repo_uid] = {
                    "is_being_cleaned": False,
                    "clean_time_start": -1,
                    "insert_time": time.time(),
                }
            else:
                # Check if this task has been set to "is_being_cleaned" for a very long time.
                # If so, remove it and allow it to be reset.)
                if self._repo_state[repo_uid]["is_being_cleaned"]:
                    delta_sec = time.time() - self._repo_state[repo_uid]["clean_time_start"]
                    if delta_sec > settings.REPO_CREATE_TIMEOUT_SEC:
                        logger.info(f"Timeout on repo refresh of {repo_uid} after {delta_sec} seconds.  Allowing retry")
                        self._repo_state[repo_uid] = {
                            "is_being_cleaned": False,
                            "clean_time_start": -1,
                            "insert_time": time.time(),
                        }
        finally:
            self._lock.release()

    def get_next_task(self):
        try:
            self._lock.acquire()
            sorted_list = sorted(self._repo_state.items(), key=lambda item: item[1]["insert_time"])
            for repo_uid, state in sorted_list:
                if not state["is_being_cleaned"]:
                    self._repo_state[repo_uid]["is_being_cleaned"] = True
                    self._repo_state[repo_uid]["clean_time_start"] = time.time()
                    return repo_uid

            return None

        finally:
            self._lock.release()

    def cleaning_done(self, repo_uid):
        try:
            self._lock.acquire()
            if repo_uid in self._repo_state:
                del self._repo_state[repo_uid]
            else:
                logger.warning(f"cleaning_done called for unknown repo_uid '{repo_uid}' — ignoring")
        finally:
            self._lock.release()
