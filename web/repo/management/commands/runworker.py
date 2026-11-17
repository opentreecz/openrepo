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
import os
import subprocess
import sys
import tempfile

from django.conf import settings
from django.core.management.base import BaseCommand

logger = logging.getLogger("openrepo_web")


class Command(BaseCommand):
    help = (
        "Start background workers for repo rebuilds, upload processing, and "
        "retention sweeps.  This is a convenience wrapper around Celery."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "-n",
            "--num_threads",
            type=int,
            default=4,
            required=False,
            help="Number of simultaneous worker threads (Celery concurrency)",
        )
        parser.add_argument(
            "--no-beat",
            action="store_true",
            default=False,
            help="Do not embed the Celery Beat scheduler (use when a separate beat process runs)",
        )

    def handle(self, *args, **options):
        concurrency = options["num_threads"]
        if concurrency < 1 or concurrency > 100:
            self.stdout.write(f"Invalid concurrency ({concurrency})")
            return

        embed_beat = not options.get("no_beat", False)
        if os.getenv("OPENREPO_WORKER_BEAT", "1").strip().lower() in ("0", "false", "no"):
            embed_beat = False

        self.stdout.write(
            self.style.SUCCESS(
                f"Starting Celery worker with concurrency={concurrency}"
                + ("  (also starts Beat scheduler in the same process)" if embed_beat else "")
            )
        )

        loglevel = os.getenv("OPENREPO_LOGLEVEL", "INFO").lower()
        cmd = [
            sys.executable, "-m", "celery",
            "-A", "openrepo",
            "worker",
            "-l", loglevel,
            f"--concurrency={concurrency}",
        ]
        if embed_beat:
            schedule = os.path.join(tempfile.gettempdir(), "celerybeat-schedule")
            cmd += ["--beat", f"--schedule={schedule}"]

        # The Celery app lives in the ``openrepo`` package next to manage.py.
        # ``python -m celery`` only puts the *current directory* on sys.path,
        # so run it from the Django project directory and export PYTHONPATH,
        # otherwise "The module openrepo was not found" when the command is
        # launched from elsewhere (e.g. ``/app/django/manage.py runworker``
        # with cwd=/app in Docker).
        project_dir = str(settings.BASE_DIR)
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(
            p for p in (project_dir, env.get("PYTHONPATH", "")) if p
        )
        env.setdefault("DJANGO_SETTINGS_MODULE", "openrepo.settings")

        try:
            subprocess.run(cmd, check=True, cwd=project_dir, env=env)
        except KeyboardInterrupt:
            pass

        self.stdout.write(self.style.SUCCESS("Worker exited"))
