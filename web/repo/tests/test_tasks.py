"""Tests for Celery tasks (repo/tasks.py) and the orchestrator."""
import os
import shutil
import tempfile
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import TestCase, override_settings

from repo.models import Build, Package, PGPSigningKey, Repository, UploadTask


class ProcessUploadTaskTest(TestCase):
    """Tests for the process_upload_task Celery task."""

    def setUp(self):
        self.signing_key = PGPSigningKey.objects.create(
            name="Task Key", email="task@test.com", fingerprint="TASK_FP_1",
            public_key_pem="pub", private_key_pem="priv",
        )
        self.repo = Repository.objects.create(
            repo_uid="task-test-repo", repo_type="files", signing_key=self.signing_key,
        )

    @patch("repo.api.upload_processor.process_upload")
    def test_delegates_to_process_upload(self, mock_process):
        """process_upload_task calls process_upload with the task_id."""
        from repo.tasks import process_upload_task
        process_upload_task("some-uuid-string")
        mock_process.assert_called_once_with("some-uuid-string")


class RebuildRepoTaskTest(TestCase):
    """Tests for the rebuild_repo_task Celery task."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        settings.STORAGE_PATH = os.path.join(self.test_dir, "storage")
        settings.REPO_WWW_PATH = os.path.join(self.test_dir, "www")
        settings.KEYRING_PATH = os.path.join(self.test_dir, "keyring")
        settings.DEB_DB_PATH = os.path.join(self.test_dir, "debcache.db")
        settings.RPM_CACHE_DIR = os.path.join(self.test_dir, "rpmcache")
        for p in [settings.STORAGE_PATH, settings.REPO_WWW_PATH,
                  settings.KEYRING_PATH, settings.RPM_CACHE_DIR]:
            os.makedirs(p, exist_ok=True)

        self.signing_key = PGPSigningKey.objects.create(
            name="Rebuild Key", email="rebuild@test.com", fingerprint="REBUILD_FP_1",
            public_key_pem="pub", private_key_pem="priv",
        )
        self.repo = Repository.objects.create(
            repo_uid="rebuild-task-repo", repo_type="files",
            signing_key=self.signing_key, is_stale=True,
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    @patch("repo.storage.keyring.PGPKeyring.ensure_key")
    def test_rebuild_clears_is_stale_on_success(self, mock_ensure):
        """rebuild_repo_task calls build_repo and clears is_stale."""
        from repo.tasks import rebuild_repo_task
        rebuild_repo_task(self.repo.repo_uid)
        self.repo.refresh_from_db()
        self.assertFalse(self.repo.is_stale)

    def test_rebuild_handles_deleted_repo(self):
        """rebuild_repo_task exits cleanly if the repo was deleted."""
        from repo.tasks import rebuild_repo_task
        self.repo.delete()
        # Should not raise
        rebuild_repo_task("rebuild-task-repo")


class RetentionSweepTaskTest(TestCase):
    """Tests for the retention_sweep Celery task."""

    def test_runs_without_error_when_no_repos(self):
        """retention_sweep does nothing when no repos have retention policies."""
        from repo.tasks import retention_sweep
        retention_sweep()  # should not raise

    def test_sweeps_repos_with_retention(self):
        """retention_sweep calls apply_retention_policy_repo for each configured repo."""
        key = PGPSigningKey.objects.create(
            name="Ret Key", email="ret@test.com", fingerprint="RET_FP_1",
            public_key_pem="pub", private_key_pem="priv",
        )
        repo = Repository.objects.create(
            repo_uid="ret-sweep-repo", repo_type="files", signing_key=key,
            retention_policy=Repository.RETENTION_KEEP_LATEST_N, retention_keep_count=1,
        )
        with patch("repo.api.retention.apply_retention_policy_repo") as mock_apply:
            from repo.tasks import retention_sweep
            retention_sweep()
            mock_apply.assert_called_once()
            self.assertEqual(mock_apply.call_args[0][0].repo_uid, repo.repo_uid)


class CheckStaleReposTaskTest(TestCase):
    """Tests for the check_stale_repos Celery task."""

    def test_dispatches_rebuild_for_stale_repos(self):
        """check_stale_repos dispatches rebuild_repo_task for each stale repo."""
        key = PGPSigningKey.objects.create(
            name="Stale Key", email="stale@test.com", fingerprint="STALE_FP_1",
            public_key_pem="pub", private_key_pem="priv",
        )
        repo = Repository.objects.create(
            repo_uid="stale-check-repo", repo_type="files", signing_key=key, is_stale=True,
        )
        with patch("repo.tasks.rebuild_repo_task.apply_async") as mock_apply:
            from repo.tasks import check_stale_repos
            check_stale_repos()
            mock_apply.assert_called_once_with(
                args=["stale-check-repo"],
                task_id="rebuild-stale-check-repo",
            )

    def test_does_nothing_when_no_stale_repos(self):
        """check_stale_repos does nothing when all repos are up to date."""
        with patch("repo.tasks.rebuild_repo_task.apply_async") as mock_apply:
            from repo.tasks import check_stale_repos
            check_stale_repos()
            mock_apply.assert_not_called()


class OrchestratorTest(TestCase):
    """Tests for the orchestrator (adapters/repo/orchestrator.py)."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        settings.STORAGE_PATH = os.path.join(self.test_dir, "storage")
        settings.REPO_WWW_PATH = os.path.join(self.test_dir, "www")
        settings.KEYRING_PATH = os.path.join(self.test_dir, "keyring")
        settings.DEB_DB_PATH = os.path.join(self.test_dir, "debcache.db")
        settings.RPM_CACHE_DIR = os.path.join(self.test_dir, "rpmcache")
        for p in [settings.STORAGE_PATH, settings.REPO_WWW_PATH,
                  settings.KEYRING_PATH, settings.RPM_CACHE_DIR]:
            os.makedirs(p, exist_ok=True)

        self.signing_key = PGPSigningKey.objects.create(
            name="Orch Key", email="orch@test.com", fingerprint="ORCH_FP_1",
            public_key_pem="pub", private_key_pem="priv",
        )
        self.repo = Repository.objects.create(
            repo_uid="orch-test-repo", repo_type="files", signing_key=self.signing_key,
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    @patch("repo.storage.keyring.PGPKeyring.ensure_key")
    def test_build_repo_creates_build_record(self, mock_ensure):
        """build_repo creates a Build with STATUS_COMPLETE_SUCCESS."""
        from adapters.repo.orchestrator import build_repo
        result = build_repo(self.repo.repo_uid)
        self.assertTrue(result)
        build = Build.objects.get(repo=self.repo)
        self.assertEqual(build.completion_status, Build.STATUS_COMPLETE_SUCCESS)
        self.assertIsNotNone(build.total_duration_sec)

    @patch("repo.storage.keyring.PGPKeyring.ensure_key")
    def test_build_repo_increments_refresh_count(self, mock_ensure):
        """build_repo increments the repo's refresh_count."""
        from adapters.repo.orchestrator import build_repo
        build_repo(self.repo.repo_uid)
        self.repo.refresh_from_db()
        self.assertEqual(self.repo.refresh_count, 1)

    def test_build_repo_returns_false_for_unknown_type(self):
        """build_repo returns False for an unrecognized repo type."""
        self.repo.repo_type = "unknown"
        self.repo.save()
        from adapters.repo.orchestrator import build_repo
        result = build_repo(self.repo.repo_uid)
        self.assertFalse(result)

    def test_build_repo_raises_for_nonexistent_repo(self):
        """build_repo raises DoesNotExist for a missing repo."""
        from adapters.repo.orchestrator import build_repo
        with self.assertRaises(Repository.DoesNotExist):
            build_repo("nonexistent-repo-uid")
