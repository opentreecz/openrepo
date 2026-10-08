"""Django ORM implementation of BuildLogWriter.

This module contains the only Django-coupled build-log code.  The repo
adapters themselves use the ``BuildLogWriter`` protocol (from ``types.py``)
and never import Django models directly.
"""
import logging
import time

from repo.models import BuildLogLine

logger = logging.getLogger("openrepo_web")


class BuildLogEntry:
    """Context manager for timed build log sections (used by ``section()``)."""

    def __init__(self, command, log_line, repo_uid):
        self.start_timestamp = time.time()
        self.command = command
        self.log_line = log_line
        self.repo_uid = repo_uid

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.log_line.execution_time_sec = time.time() - self.start_timestamp
        self.log_line.exec_complete = True
        self.log_line.save()

    def set_message(self, message):
        self.log_line.message = message
        logger.info("build %s: %s", self.repo_uid, message)

    def set_loglevel(self, loglevel):
        self.log_line.loglevel = loglevel


class DjangoBuildLogger:
    """``BuildLogWriter`` implementation that persists to Django ORM."""

    def __init__(self, build, repo_uid):
        self.build = build
        self.repo_uid = repo_uid
        self._line_number = 0

    def write(self, command, message="", loglevel="info", is_complete=True):
        log_line = BuildLogLine(
            build=self.build,
            command=command,
            message=message,
            loglevel=loglevel,
            line_number=self._line_number,
            exec_complete=is_complete,
        )
        self._line_number += 1
        log_line.save()
        logger.info("build %s: %s %s %s", self.repo_uid, loglevel, command, message)
        return log_line

    def section(self, command, loglevel="info"):
        log_line = self.write(command, loglevel=loglevel, is_complete=False)
        return BuildLogEntry(command, log_line, self.repo_uid)
