# Copyright 2022 by Open Kilt LLC. All rights reserved.
import os
import shutil
import tempfile
import uuid
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import TestCase

from repo.api.upload_processor import process_upload
from repo.models import Package, PGPSigningKey, Repository, UploadTask


class ProcessUploadTestCase(TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        settings.STORAGE_PATH = self.test_dir

        self.signing_key = PGPSigningKey.objects.create(
            name="Upload Key",
            email="upload@example.com",
            fingerprint="UPLOAD_FP_1234567890",
            public_key_pem="pub",
            private_key_pem="priv",
        )
        self.repo = Repository.objects.create(
            repo_uid="upload-proc-repo", repo_type="files", signing_key=self.signing_key
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _write_stored_file(self, content=b"package contents"):
        path = os.path.join(self.test_dir, str(uuid.uuid4()))
        with open(path, "wb") as f:
            f.write(content)
        return path

    def _make_task(self, filename="pkg-1.0.0.bin", overwrite=False, content=b"package contents"):
        return UploadTask.objects.create(
            repo=self.repo,
            status="stored",
            filename=filename,
            filesize=len(content),
            overwrite=overwrite,
            stored_path=self._write_stored_file(content),
        )

    def _mock_adapter(self, name="mypkg", version="1.0.0", arch="any"):
        adapter = MagicMock()
        adapter.get_name.return_value = name
        adapter.get_version.return_value = version
        adapter.get_architecture.return_value = arch
        adapter.get_builddate.return_value = None
        return adapter

    def test_task_not_found_logs_and_returns(self):
        """process_upload exits cleanly (no crash) when the task row doesn't exist"""
        with self.assertLogs("openrepo_web", level="ERROR") as logs:
            process_upload(uuid.uuid4())
        self.assertIn("not found for background processing", logs.output[0])

    @patch("repo.api.upload_processor.create_adapter")
    def test_unrecognized_repo_type_marks_task_failed(self, mock_create_adapter):
        """When create_adapter can't determine a file type, the task is marked failed"""
        mock_create_adapter.return_value = None
        task = self._make_task()

        process_upload(task.pk)

        task.refresh_from_db()
        self.assertEqual(task.status, "failed")
        self.assertIn("Error determining file type", task.error_message)

    @patch("repo.api.upload_processor.create_adapter")
    def test_successful_upload_marks_task_completed(self, mock_create_adapter):
        """A normal upload creates a Package and marks the task completed"""
        mock_create_adapter.return_value = self._mock_adapter()
        task = self._make_task()

        process_upload(task.pk)

        task.refresh_from_db()
        self.assertEqual(task.status, "completed")
        self.assertIsNotNone(task.completed_at)
        self.assertEqual(Package.objects.filter(repo=self.repo, package_name="mypkg").count(), 1)

    @patch("repo.api.upload_processor.create_adapter")
    def test_duplicate_without_overwrite_marks_task_failed(self, mock_create_adapter):
        """Uploading a duplicate package without overwrite fails the task and keeps one Package"""
        mock_create_adapter.return_value = self._mock_adapter()

        process_upload(self._make_task().pk)
        dup_task = self._make_task()
        process_upload(dup_task.pk)

        dup_task.refresh_from_db()
        self.assertEqual(dup_task.status, "failed")
        self.assertIn("already exists", dup_task.error_message)
        self.assertEqual(Package.objects.filter(repo=self.repo, package_name="mypkg").count(), 1)

    @patch("repo.api.upload_processor.create_adapter")
    def test_duplicate_with_overwrite_replaces_package(self, mock_create_adapter):
        """Uploading a duplicate package with overwrite=True replaces the existing Package"""
        mock_create_adapter.return_value = self._mock_adapter()

        process_upload(self._make_task().pk)
        first_uid = Package.objects.get(repo=self.repo, package_name="mypkg").package_uid

        overwrite_task = self._make_task(overwrite=True, content=b"different bytes this time")
        process_upload(overwrite_task.pk)

        overwrite_task.refresh_from_db()
        self.assertEqual(overwrite_task.status, "completed")
        packages = Package.objects.filter(repo=self.repo, package_name="mypkg")
        self.assertEqual(packages.count(), 1)
        self.assertNotEqual(packages.get().package_uid, first_uid)

    @patch("repo.api.upload_processor.create_adapter")
    def test_matching_checksum_in_other_repo_reuses_stored_file(self, mock_create_adapter):
        """Uploading bytes identical to a package already stored (in any repo) dedupes on disk"""
        mock_create_adapter.return_value = self._mock_adapter()

        # First upload creates the on-disk copy.
        first_task = self._make_task(content=b"shared bytes")
        process_upload(first_task.pk)
        existing_package = Package.objects.get(repo=self.repo, package_name="mypkg")

        other_repo = Repository.objects.create(
            repo_uid="upload-proc-repo-2", repo_type="files", signing_key=self.signing_key
        )
        self.repo_backup = self.repo
        self.repo = other_repo
        second_task = self._make_task(content=b"shared bytes")
        stored_path = second_task.stored_path
        self.repo = self.repo_backup

        process_upload(second_task.pk)

        second_task.refresh_from_db()
        self.assertEqual(second_task.status, "completed")
        # The newly-uploaded file is deleted since we reuse the existing on-disk copy.
        self.assertFalse(os.path.exists(stored_path))
        new_package = Package.objects.get(repo=other_repo, package_name="mypkg")
        self.assertEqual(new_package.package_uid, existing_package.package_uid)

    @patch("repo.api.upload_processor.create_adapter")
    def test_keep_only_latest_deletes_older_versions(self, mock_create_adapter):
        """When keep_only_latest is set, uploading a new version removes older ones"""
        self.repo.keep_only_latest = True
        self.repo.save()

        mock_create_adapter.return_value = self._mock_adapter(version="1.0.0")
        process_upload(self._make_task(filename="mypkg-1.0.0.bin").pk)
        self.assertEqual(Package.objects.filter(repo=self.repo, package_name="mypkg").count(), 1)

        mock_create_adapter.return_value = self._mock_adapter(version="2.0.0")
        process_upload(self._make_task(filename="mypkg-2.0.0.bin", content=b"v2 bytes").pk)

        packages = Package.objects.filter(repo=self.repo, package_name="mypkg")
        self.assertEqual(packages.count(), 1)
        self.assertEqual(packages.get().version, "2.0.0")

    @patch("repo.api.upload_processor.create_adapter")
    def test_exception_during_processing_marks_task_failed_and_removes_file(self, mock_create_adapter):
        """An unexpected error during processing fails the task and cleans up the stored file"""
        adapter = self._mock_adapter()
        adapter.get_version.side_effect = RuntimeError("adapter blew up")
        mock_create_adapter.return_value = adapter

        task = self._make_task()
        stored_path = task.stored_path

        process_upload(task.pk)

        task.refresh_from_db()
        self.assertEqual(task.status, "failed")
        self.assertIn("adapter blew up", task.error_message)
        self.assertFalse(os.path.exists(stored_path))

    @patch("os.remove", side_effect=OSError("permission denied"))
    @patch("repo.api.upload_processor.create_adapter")
    def test_exception_cleanup_swallows_remove_failure(self, mock_create_adapter, mock_remove):
        """If removing the stored file during failure cleanup itself errors, that's swallowed"""
        adapter = self._mock_adapter()
        adapter.get_version.side_effect = RuntimeError("adapter blew up")
        mock_create_adapter.return_value = adapter

        task = self._make_task()

        process_upload(task.pk)

        task.refresh_from_db()
        self.assertEqual(task.status, "failed")
        mock_remove.assert_called_once()
