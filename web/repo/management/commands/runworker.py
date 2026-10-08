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
import subprocess
import sys

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

    def handle(self, *args, **options):
        concurrency = options["num_threads"]
        if concurrency < 1 or concurrency > 100:
            self.stdout.write(f"Invalid concurrency ({concurrency})")
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Starting Celery worker with concurrency={concurrency}  "
                "(also starts Beat scheduler in the same process)"
            )
        )

        cmd = [
            sys.executable, "-m", "celery",
            "-A", "openrepo",
            "worker",
            "--beat",
            "-l", "info",
            f"--concurrency={concurrency}",
        ]

        try:
            subprocess.run(cmd, check=True)
        except KeyboardInterrupt:
            pass

        self.stdout.write(self.style.SUCCESS("Worker exited"))
