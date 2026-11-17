"""Celery application configuration for OpenRepo."""
import logging
import os
import warnings

from celery import Celery
from celery.exceptions import SecurityWarning

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "openrepo.settings")

# The Docker image runs every service as root (it owns the shared data
# volume), so Celery's "running the worker with superuser privileges"
# warning is expected noise there.
warnings.filterwarnings("ignore", category=SecurityWarning)

app = Celery("openrepo")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Periodic housekeeping tasks that would otherwise log three INFO lines
# ("Sending due task", "received", "succeeded") on every run.
QUIET_PERIODIC_TASKS = ("check_stale_repos", "check-stale-repos")


class _QuietPeriodicTasksFilter(logging.Filter):
    def filter(self, record):
        if record.levelno > logging.INFO:
            return True
        try:
            message = record.getMessage()
        except Exception:
            return True
        return not any(name in message for name in QUIET_PERIODIC_TASKS)


if os.getenv("OPENREPO_LOG_PERIODIC_TASKS", "0").strip().lower() not in ("1", "true", "yes"):
    _quiet_filter = _QuietPeriodicTasksFilter()
    for _name in ("celery.beat", "celery.app.trace", "celery.worker.strategy"):
        logging.getLogger(_name).addFilter(_quiet_filter)
