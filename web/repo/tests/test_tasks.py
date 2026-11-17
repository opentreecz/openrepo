"""Tests for Celery tasks (repo/tasks.py) and the orchestrator."""
import os
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase

from repo.models import Build, Repository
from repo.tests.fixtures import make_signing_key, TempSettingsMixin


class ProcessUploadTaskTest(TestCase):
    """Tests for the process_upload_task Celery task."""

    def setUp(self):
        self.signing_key = make_signing_key(name="Task Key", fingerprint="TASK_FP_1")
        self.repo = Repository.objects.create(
            repo_uid="task-test-repo", repo_type="files", signing_key=self.signing_key,
        )

    @patch("repo.api.upload_processor.process_upload")
    def test_delegates_to_process_upload(self, mock_process):
        """process_upload_task calls process_upload with the task_id."""
        from repo.tasks import process_upload_task
        process_upload_task("some-uuid-string")
        mock_process.assert_called_once_with("some-uuid-string")


class DispatchUploadProcessingTest(TestCase):
    """dispatch_upload_processing falls back to a thread when the broker is down."""

    @patch("repo.tasks.process_upload_task.delay")
    def test_uses_celery_when_broker_available(self, mock_delay):
        from repo.tasks import dispatch_upload_processing
        self.assertEqual(dispatch_upload_processing("abc"), "celery")
        mock_delay.assert_called_once_with("abc")

    @patch("repo.tasks.threading.Thread")
    @patch("repo.tasks.process_upload_task.delay", side_effect=OSError("Connection refused"))
    def test_falls_back_to_thread_when_broker_down(self, _mock_delay, mock_thread):
        from repo.tasks import dispatch_upload_processing, _process_upload_in_thread
        self.assertEqual(dispatch_upload_processing("abc"), "thread")
        mock_thread.assert_called_once()
        kwargs = mock_thread.call_args.kwargs
        self.assertIs(kwargs["target"], _process_upload_in_thread)
        self.assertEqual(kwargs["args"], ("abc",))
        mock_thread.return_value.start.assert_called_once()

    @patch("repo.api.upload_processor.process_upload")
    def test_thread_target_runs_processor(self, mock_process):
        from repo.tasks import _process_upload_in_thread
        _process_upload_in_thread("abc")
        mock_process.assert_called_once_with("abc")


class RebuildRepoTaskTest(TempSettingsMixin, TestCase):
    """Tests for the rebuild_repo_task Celery task."""

    def setUp(self):
        super().setUp()
        for name, value in {
            "DEB_DB_PATH": os.path.join(self.test_dir, "debcache.db"),
            "RPM_CACHE_DIR": os.path.join(self.test_dir, "rpmcache"),
        }.items():
            self._saved_settings[name] = getattr(settings, name, None)
            setattr(settings, name, value)
        os.makedirs(settings.RPM_CACHE_DIR, exist_ok=True)

        self.signing_key = make_signing_key(name="Rebuild Key", fingerprint="REBUILD_FP_1")
        self.repo = Repository.objects.create(
            repo_uid="rebuild-task-repo", repo_type="files",
            signing_key=self.signing_key, is_stale=True,
        )

    @patch("repo.storage.signer.PGPSigner.ensure_key")
    def test_rebuild_clears_is_stale_on_success(self, mock_ensure):
        """rebuild_repo_task calls build_repo and clears is_stale."""
        from repo.tasks import rebuild_repo_task
        rebuild_repo_task(self.repo.repo_uid)
        self.repo.refresh_from_db()
        self.assertFalse(self.repo.is_stale)

    @patch("adapters.repo.orchestrator.build_repo")
    def test_rebuild_skips_when_already_running(self, mock_build):
        """A second rebuild of the same repo exits without building."""
        from repo.locks import repo_build_lock
        from repo.tasks import rebuild_repo_task
        with repo_build_lock(self.repo.repo_uid) as acquired:
            self.assertTrue(acquired)
            rebuild_repo_task(self.repo.repo_uid)
        mock_build.assert_not_called()
        self.repo.refresh_from_db()
        self.assertTrue(self.repo.is_stale)

    @patch("adapters.repo.orchestrator.build_repo", return_value=True)
    def test_rebuild_clears_stale_before_building(self, mock_build):
        """is_stale is cleared before the build so concurrent changes re-flag it."""
        from repo.tasks import rebuild_repo_task

        def build(uid):
            # Simulate a package arriving during the build.
            self.assertFalse(Repository.objects.get(repo_uid=uid).is_stale)
            Repository.objects.filter(repo_uid=uid).update(is_stale=True)
            return True

        mock_build.side_effect = build
        rebuild_repo_task(self.repo.repo_uid)
        self.repo.refresh_from_db()
        self.assertTrue(self.repo.is_stale)

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
        key = make_signing_key(name="Ret Key", fingerprint="RET_FP_1")
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

    def setUp(self):
        super().setUp()
        from repo.locks import clear_rebuild_queued
        for uid in ("stale-check-repo", "busy-repo"):
            clear_rebuild_queued(uid)

    def test_dispatches_rebuild_for_stale_repos(self):
        """check_stale_repos dispatches rebuild_repo_task for each stale repo."""
        key = make_signing_key(name="Stale Key", fingerprint="STALE_FP_1")
        Repository.objects.create(
            repo_uid="stale-check-repo", repo_type="files", signing_key=key, is_stale=True,
        )
        with patch("repo.tasks.rebuild_repo_task.apply_async") as mock_apply:
            from repo.tasks import check_stale_repos
            check_stale_repos()
            mock_apply.assert_called_once_with(
                args=["stale-check-repo"],
                task_id="rebuild-stale-check-repo",
                countdown=0,
            )
            # A second pass while the rebuild is still queued does not re-dispatch.
            check_stale_repos()
            mock_apply.assert_called_once()

    def test_skips_repo_whose_rebuild_is_running(self):
        """check_stale_repos does not queue a rebuild while one holds the lock."""
        from repo.locks import repo_build_lock
        key = make_signing_key(name="Busy Key", fingerprint="BUSY_FP_1")
        Repository.objects.create(
            repo_uid="busy-repo", repo_type="files", signing_key=key, is_stale=True,
        )
        with patch("repo.tasks.rebuild_repo_task.apply_async") as mock_apply:
            from repo.tasks import check_stale_repos
            with repo_build_lock("busy-repo") as acquired:
                self.assertTrue(acquired)
                check_stale_repos()
            mock_apply.assert_not_called()

    def tearDown(self):
        from repo.locks import clear_rebuild_queued
        for uid in ("stale-check-repo", "busy-repo"):
            clear_rebuild_queued(uid)
        super().tearDown()

    def test_does_nothing_when_no_stale_repos(self):
        """check_stale_repos does nothing when all repos are up to date."""
        with patch("repo.tasks.rebuild_repo_task.apply_async") as mock_apply:
            from repo.tasks import check_stale_repos
            check_stale_repos()
            mock_apply.assert_not_called()


class OrchestratorTest(TempSettingsMixin, TestCase):
    """Tests for the orchestrator (adapters/repo/orchestrator.py)."""

    def setUp(self):
        super().setUp()
        for name, value in {
            "DEB_DB_PATH": os.path.join(self.test_dir, "debcache.db"),
            "RPM_CACHE_DIR": os.path.join(self.test_dir, "rpmcache"),
        }.items():
            self._saved_settings[name] = getattr(settings, name, None)
            setattr(settings, name, value)
        os.makedirs(settings.RPM_CACHE_DIR, exist_ok=True)

        self.signing_key = make_signing_key(name="Orch Key", fingerprint="ORCH_FP_1")
        self.repo = Repository.objects.create(
            repo_uid="orch-test-repo", repo_type="files", signing_key=self.signing_key,
        )

    @patch("repo.storage.signer.PGPSigner.ensure_key")
    def test_build_repo_creates_build_record(self, mock_ensure):
        """build_repo creates a Build with STATUS_COMPLETE_SUCCESS."""
        from adapters.repo.orchestrator import build_repo
        result = build_repo(self.repo.repo_uid)
        self.assertTrue(result)
        build = Build.objects.get(repo=self.repo)
        self.assertEqual(build.completion_status, Build.STATUS_COMPLETE_SUCCESS)
        self.assertIsNotNone(build.total_duration_sec)

    @patch("repo.storage.signer.PGPSigner.ensure_key")
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


class RepoBuildLockTest(TestCase):
    """repo.locks: exclusive per-repo rebuild lock and queued markers."""

    def test_lock_is_exclusive(self):
        from repo.locks import is_build_running, repo_build_lock
        self.assertFalse(is_build_running("lock-test"))
        with repo_build_lock("lock-test") as first:
            self.assertTrue(first)
            self.assertTrue(is_build_running("lock-test"))
            with repo_build_lock("lock-test") as second:
                self.assertFalse(second)
        self.assertFalse(is_build_running("lock-test"))

    def test_queued_marker_dedupes(self):
        from repo.locks import clear_rebuild_queued, mark_rebuild_queued
        clear_rebuild_queued("queue-test")
        self.assertTrue(mark_rebuild_queued("queue-test"))
        self.assertFalse(mark_rebuild_queued("queue-test"))
        clear_rebuild_queued("queue-test")
        self.assertTrue(mark_rebuild_queued("queue-test"))
        clear_rebuild_queued("queue-test")


class KeyringPermissionsTest(TempSettingsMixin, TestCase):
    """The GPG homedir is created/tightened to 0700."""

    def test_keyring_dir_is_private(self):
        import stat
        from repo.storage.keyring import ensure_keyring_dir
        os.makedirs(settings.KEYRING_PATH, exist_ok=True)
        os.chmod(settings.KEYRING_PATH, 0o755)
        ensure_keyring_dir()
        mode = stat.S_IMODE(os.stat(settings.KEYRING_PATH).st_mode)
        self.assertEqual(mode, 0o700)
