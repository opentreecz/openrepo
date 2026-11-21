# SPDX-License-Identifier: AGPL-3.0-only
import json

from django.core.management.base import BaseCommand, CommandError

from repo.cleanup import CleanupBusy, CleanupOptions, run_cleanup


class Command(BaseCommand):
    help = (
        "Remove unused package files, abandoned uploads, stale builds and leftover "
        "publish directories. Dry-run unless --apply is given."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Actually delete (default: dry-run)")
        parser.add_argument("--grace-hours", type=int, default=None,
                            help="Minimum age of data considered abandoned "
                                 "(default: OPENREPO_CLEANUP_GRACE_HOURS or 24)")
        parser.add_argument("--history-days", type=int, default=None,
                            help="Delete finished upload tasks/builds older than this, 0 = keep "
                                 "(default: OPENREPO_CLEANUP_HISTORY_DAYS or 90)")
        parser.add_argument("--json", action="store_true", help="Print the report as JSON")

    def handle(self, *args, **options):
        opts = CleanupOptions(dry_run=not options["apply"])
        if options["grace_hours"] is not None:
            opts.grace_hours = options["grace_hours"]
        if options["history_days"] is not None:
            opts.history_days = options["history_days"]

        try:
            report = run_cleanup(opts)
        except CleanupBusy as exc:
            raise CommandError(str(exc))

        if options["json"]:
            self.stdout.write(json.dumps(report.as_dict(), indent=2))
            return

        self.stdout.write(report.summary())
        for name in report.stale_publish_dirs:
            self.stdout.write(f"  stale publish dir: {name}")
        for name in report.unmanaged_publish_dirs:
            self.stdout.write(f"  unmanaged publish dir (repo not in database, kept): {name}")
        for line in report.skipped:
            self.stdout.write(f"  skipped: {line}")
        for line in report.errors:
            self.stderr.write(f"  error: {line}")
        if report.dry_run:
            self.stdout.write("Dry-run: nothing was changed. Re-run with --apply to clean up.")
