# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for the storage/database cleanup (repo.cleanup)."""
import json
import os
import time
from datetime import timedelta
from io import StringIO

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from repo.cleanup import (
    ABANDONED_UPLOAD_MESSAGE,
    CleanupBusy,
    CleanupOptions,
    _cleanup_lock,
    run_cleanup,
)
from repo.locks import repo_build_lock
from repo.models import Build, Package, Repository, UploadTask
from repo.tests.fixtures import TempSettingsMixin, make_admin, make_signing_key

OLD = time.time() - 3 * 86400


class CleanupFixtureMixin(TempSettingsMixin):
    def setUp(self):
        super().setUp()
        self.var_dir = os.path.join(self.test_dir, "var")
        os.makedirs(self.var_dir)
        self._saved_var_dir = settings.OPENREPO_VAR_DIR
        settings.OPENREPO_VAR_DIR = self.var_dir
        self.repo = Repository.objects.create(
            repo_uid="deb", repo_type="deb", signing_key=make_signing_key()
        )

    def tearDown(self):
        settings.OPENREPO_VAR_DIR = self._saved_var_dir
        super().tearDown()

    def storage_file(self, rel, age=OLD, size=10):
        path = os.path.join(self.storage_path, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"x" * size)
        os.utime(path, (age, age))
        return path

    def package(self, uid):
        return Package.objects.create(
            package_uid=uid, repo=self.repo, filename=f"{uid}.deb", package_name=uid,
            architecture="amd64", version="1.0", upload_date=timezone.now(), checksum_sha512="0",
        )

    def upload_task(self, rel, task_status="stored", age_hours=48):
        task = UploadTask.objects.create(
            repo=self.repo, status=task_status, filename="x.deb",
            stored_path=os.path.join(self.storage_path, rel),
        )
        UploadTask.objects.filter(pk=task.pk).update(
            created_at=timezone.now() - timedelta(hours=age_hours)
        )
        return task

    def publish_dir(self, name, age=OLD):
        path = os.path.join(self.www_path, name)
        os.makedirs(path)
        os.utime(path, (age, age))
        return path

    def apply(self, **kwargs):
        return run_cleanup(CleanupOptions(dry_run=False, grace_hours=24, history_days=90, **kwargs))


class OrphanFileTests(CleanupFixtureMixin, TestCase):
    def test_removes_unreferenced_files_and_keeps_referenced(self):
        orphan = self.storage_file("aa/orphan")
        kept = self.storage_file("bb/kept")
        self.package("bb-kept")

        report = self.apply()

        self.assertFalse(os.path.exists(orphan))
        self.assertTrue(os.path.exists(kept))
        self.assertEqual(report.orphan_files, 1)
        self.assertEqual(report.orphan_bytes, 10)
        self.assertFalse(os.path.isdir(os.path.join(self.storage_path, "aa")))
        self.assertEqual(report.empty_dirs, 1)

    def test_keeps_files_younger_than_grace_period(self):
        young = self.storage_file("aa/young", age=time.time())
        report = self.apply()
        self.assertTrue(os.path.exists(young))
        self.assertEqual(report.orphan_files, 0)

    def test_keeps_files_linked_from_publish_tree(self):
        target = self.storage_file("cc/published")
        pool = os.path.join(self.www_path, "old.000000001", "pool")
        os.makedirs(pool)
        os.symlink(target, os.path.join(pool, "pkg.deb"))
        self.apply()
        self.assertTrue(os.path.exists(target))

    def test_dry_run_changes_nothing(self):
        orphan = self.storage_file("aa/orphan")
        task = self.upload_task("dd/abandoned")
        self.storage_file("dd/abandoned")

        report = run_cleanup(CleanupOptions(dry_run=True, grace_hours=24))

        self.assertTrue(report.dry_run)
        self.assertEqual(report.orphan_files, 2)
        self.assertEqual(report.abandoned_uploads, 1)
        self.assertTrue(os.path.exists(orphan))
        task.refresh_from_db()
        self.assertEqual(task.status, "stored")


class UploadTaskTests(CleanupFixtureMixin, TestCase):
    def test_abandoned_upload_is_failed_and_its_file_removed(self):
        path = self.storage_file("dd/abandoned")
        task = self.upload_task("dd/abandoned", age_hours=48)

        report = self.apply()

        task.refresh_from_db()
        self.assertEqual(task.status, "failed")
        self.assertEqual(task.error_message, ABANDONED_UPLOAD_MESSAGE)
        self.assertIsNotNone(task.completed_at)
        self.assertFalse(os.path.exists(path))
        self.assertEqual(report.abandoned_uploads, 1)

    def test_recent_in_flight_upload_is_untouched(self):
        path = self.storage_file("ee/inflight")
        task = self.upload_task("ee/inflight", task_status="processing", age_hours=1)

        self.apply()

        task.refresh_from_db()
        self.assertEqual(task.status, "processing")
        self.assertTrue(os.path.exists(path))


class BuildTests(CleanupFixtureMixin, TestCase):
    def build(self, number, build_status=Build.STATUS_RUNNING, age_hours=48):
        b = Build.objects.create(repo=self.repo, build_number=number, completion_status=build_status)
        Build.objects.filter(pk=b.pk).update(timestamp=timezone.now() - timedelta(hours=age_hours))
        return b

    def test_running_build_superseded_by_newer_build_is_failed(self):
        stuck = self.build(1)
        self.build(2, Build.STATUS_COMPLETE_SUCCESS)
        report = self.apply()
        stuck.refresh_from_db()
        self.assertEqual(stuck.completion_status, Build.STATUS_COMPLETE_ERROR)
        self.assertEqual(report.stale_builds, 1)

    def test_build_holding_the_lock_is_kept(self):
        running = self.build(1)
        with repo_build_lock("deb") as acquired:
            self.assertTrue(acquired)
            report = self.apply()
        running.refresh_from_db()
        self.assertEqual(running.completion_status, Build.STATUS_RUNNING)
        self.assertEqual(report.stale_builds, 0)

    def test_history_keeps_latest_build_per_repo(self):
        old = self.build(1, Build.STATUS_COMPLETE_SUCCESS, age_hours=24 * 200)
        latest = self.build(2, Build.STATUS_COMPLETE_ERROR, age_hours=24 * 200)
        task = self.upload_task("ff/x", task_status="completed", age_hours=24 * 200)

        report = self.apply()

        self.assertFalse(Build.objects.filter(pk=old.pk).exists())
        self.assertTrue(Build.objects.filter(pk=latest.pk).exists())
        self.assertFalse(UploadTask.objects.filter(pk=task.pk).exists())
        self.assertEqual(report.old_builds, 1)
        self.assertEqual(report.old_upload_tasks, 1)

    def test_history_days_zero_keeps_history(self):
        self.build(1, Build.STATUS_COMPLETE_SUCCESS, age_hours=24 * 200)
        self.build(2, Build.STATUS_COMPLETE_SUCCESS, age_hours=24 * 200)
        report = run_cleanup(CleanupOptions(dry_run=False, history_days=0))
        self.assertEqual(Build.objects.count(), 2)
        self.assertEqual(report.old_builds, 0)


class PublishDirTests(CleanupFixtureMixin, TestCase):
    def test_removes_stale_dirs_keeps_live_young_and_unmanaged(self):
        live = self.publish_dir("deb.000000003")
        os.symlink("deb.000000003", os.path.join(self.www_path, "deb"))
        stale = self.publish_dir("deb.000000002")
        young = self.publish_dir("deb.000000004", age=time.time())
        unmanaged = self.publish_dir("gone.000000001")

        report = self.apply()

        self.assertTrue(os.path.isdir(live))
        self.assertFalse(os.path.exists(stale))
        self.assertTrue(os.path.isdir(young))
        self.assertTrue(os.path.isdir(unmanaged))
        self.assertEqual(report.stale_publish_dirs, ["deb.000000002"])
        self.assertEqual(report.unmanaged_publish_dirs, ["gone.000000001"])

    def test_skips_repo_while_building(self):
        stale = self.publish_dir("deb.000000002")
        with repo_build_lock("deb"):
            report = self.apply()
        self.assertTrue(os.path.isdir(stale))
        self.assertEqual(report.stale_publish_dirs, [])
        self.assertEqual(len(report.skipped), 1)


class LockAndCommandTests(CleanupFixtureMixin, TestCase):
    def test_concurrent_run_raises_busy(self):
        with _cleanup_lock():
            with self.assertRaises(CleanupBusy):
                run_cleanup(CleanupOptions(dry_run=True))

    def test_command_defaults_to_dry_run(self):
        orphan = self.storage_file("aa/orphan")
        out = StringIO()
        call_command("cleanup", stdout=out)
        self.assertTrue(os.path.exists(orphan))
        self.assertIn("Dry-run", out.getvalue())

    def test_command_apply_json(self):
        orphan = self.storage_file("aa/orphan")
        out = StringIO()
        call_command("cleanup", "--apply", "--json", stdout=out)
        self.assertFalse(os.path.exists(orphan))
        self.assertEqual(json.loads(out.getvalue())["orphan_files"], 1)


class CleanupApiTests(CleanupFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        _user, _key, self.admin_auth = make_admin("cleanup-admin")

    def test_requires_superuser(self):
        from django.contrib.auth.models import User
        from rest_framework.authtoken.models import Token

        user = User.objects.create_user("plain", password="pw")
        auth = f"Token {Token.objects.get(user=user).key}"
        response = self.client.post("/api/cleanup/", {}, HTTP_AUTHORIZATION=auth, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_default_is_dry_run(self):
        orphan = self.storage_file("aa/orphan")
        response = self.client.post("/api/cleanup/", {}, HTTP_AUTHORIZATION=self.admin_auth, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["dry_run"])
        self.assertEqual(response.data["orphan_files"], 1)
        self.assertTrue(os.path.exists(orphan))

    def test_apply(self):
        orphan = self.storage_file("aa/orphan")
        response = self.client.post(
            "/api/cleanup/", {"dry_run": False, "grace_hours": 24},
            HTTP_AUTHORIZATION=self.admin_auth, format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["dry_run"])
        self.assertFalse(os.path.exists(orphan))

    def test_busy_returns_409(self):
        with _cleanup_lock():
            response = self.client.post("/api/cleanup/", {}, HTTP_AUTHORIZATION=self.admin_auth, format="json")
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["code"], "CLEANUP_BUSY")

    def test_cleanup_is_a_reserved_repo_uid(self):
        response = self.client.post(
            "/api/repos/",
            {"repo_uid": "cleanup", "repo_name": "x", "repo_type": "deb",
             "signing_key": self.repo.signing_key.fingerprint},
            HTTP_AUTHORIZATION=self.admin_auth, format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class CleanupTaskTests(CleanupFixtureMixin, TestCase):
    def test_task_applies_by_default(self):
        from repo.tasks import cleanup_task

        orphan = self.storage_file("aa/orphan")
        cleanup_task()
        self.assertFalse(os.path.exists(orphan))

    def test_task_respects_dry_run_env(self):
        from unittest.mock import patch

        from repo.tasks import cleanup_task

        orphan = self.storage_file("aa/orphan")
        with patch.dict(os.environ, {"OPENREPO_CLEANUP_DRY_RUN": "1"}):
            cleanup_task()
        self.assertTrue(os.path.exists(orphan))

    def test_task_skips_when_busy(self):
        from repo.tasks import cleanup_task

        with _cleanup_lock():
            cleanup_task()  # must not raise
