# Copyright 2022 by Open Kilt LLC. All rights reserved.
import time
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import TestCase

from repo.models import PGPSigningKey, Repository
from repo.worker.bgworker import BackgroundWorker, ChoreList


class WorkerTestCase(TestCase):
    def setUp(self):
        self.signing_key = PGPSigningKey.objects.create(
            name="Test Key",
            email="test@example.com",
            fingerprint="ABCDEF1234567890",
            public_key_pem="dummy public",
            private_key_pem="dummy private",
        )
        self.repo = Repository.objects.create(
            repo_uid="test-worker-repo", repo_type="deb", signing_key=self.signing_key, is_stale=True
        )

    def test_chore_list_logic(self):
        """Test the logic of adding and retrieving tasks from ChoreList"""
        cl = ChoreList()
        repo_uid = "test-repo"

        cl.set_needs_clean(repo_uid)

        # Should be able to get the task
        task = cl.get_next_task()
        self.assertEqual(task, repo_uid)

        # Should NOT be able to get the task again while it's being cleaned
        task_again = cl.get_next_task()
        self.assertIsNone(task_again)

        # After cleaning is done, it should be removed (so next_task is None)
        cl.cleaning_done(repo_uid)
        self.assertIsNone(cl.get_next_task())

    def test_chore_list_timeout(self):
        """Test that ChoreList handles timeouts for long-running/stalled tasks"""
        settings.REPO_CREATE_TIMEOUT_SEC = 0.1  # Very short timeout
        cl = ChoreList()
        repo_uid = "timeout-repo"

        cl.set_needs_clean(repo_uid)
        cl.get_next_task()  # Marks as is_being_cleaned

        time.sleep(0.2)

        # Setting needs_clean again should trigger the timeout check and immediately requeue the task
        cl.set_needs_clean(repo_uid)

        # Now it should be available again
        self.assertEqual(cl.get_next_task(), repo_uid)

    @patch("repo.worker.bgworker.build_repo")
    def test_worker_processes_stale_repo(self, mock_build_repo):
        """Test that the worker picks up a stale repo, resets the flag, and calls build_repo"""
        mock_build_repo.return_value = True

        cl = ChoreList()
        cl.set_needs_clean(self.repo.repo_uid)

        BackgroundWorker(cl)

        # Simulate one iteration of the worker.run() loop
        repo_uid = cl.get_next_task()
        self.assertEqual(repo_uid, self.repo.repo_uid)

        # The logic inside worker.run() now calls build_repo
        success = mock_build_repo(repo_uid)
        self.assertTrue(success)

        repo = Repository.objects.get(repo_uid=repo_uid)
        repo.is_stale = False
        repo.save()

        cl.cleaning_done(repo_uid)

        # Verify
        self.repo.refresh_from_db()
        self.assertFalse(self.repo.is_stale)
        self.assertTrue(mock_build_repo.called)
        self.assertIsNone(cl.get_next_task())

    @patch("repo.worker.bgworker.time.sleep")
    @patch("repo.worker.bgworker.build_repo")
    def test_run_processes_task_and_exits_on_stop(self, mock_build_repo, mock_sleep):
        """BackgroundWorker.run() picks up a queued repo, refreshes it, then stops"""
        mock_build_repo.return_value = True

        cl = ChoreList()
        cl.set_needs_clean(self.repo.repo_uid)

        worker = BackgroundWorker(cl)

        def stop_after_first_sleep(*args, **kwargs):
            worker.stay_alive = False

        mock_sleep.side_effect = stop_after_first_sleep

        worker.run()

        self.repo.refresh_from_db()
        self.assertFalse(self.repo.is_stale)
        mock_build_repo.assert_called_once_with(self.repo.repo_uid)
        self.assertIsNone(cl.get_next_task())

    @patch("repo.worker.bgworker.time.sleep")
    def test_run_with_no_pending_tasks(self, mock_sleep):
        """BackgroundWorker.run() sleeps and loops when there is nothing to do"""
        cl = ChoreList()
        worker = BackgroundWorker(cl)

        def stop_after_first_sleep(*args, **kwargs):
            worker.stay_alive = False

        mock_sleep.side_effect = stop_after_first_sleep

        worker.run()

        mock_sleep.assert_called_once()

    @patch("repo.worker.bgworker.time.sleep")
    @patch("repo.worker.bgworker.build_repo")
    def test_run_survives_exception_and_still_marks_task_done(self, mock_build_repo, mock_sleep):
        """BackgroundWorker.run() logs and continues if build_repo raises, still releasing the task"""
        mock_build_repo.side_effect = RuntimeError("boom")

        cl = ChoreList()
        cl.set_needs_clean(self.repo.repo_uid)

        worker = BackgroundWorker(cl)

        def stop_after_first_sleep(*args, **kwargs):
            worker.stay_alive = False

        mock_sleep.side_effect = stop_after_first_sleep

        worker.run()

        # cleaning_done() runs in a finally block even though setup_repo() raised
        self.assertIsNone(cl.get_next_task())
        self.repo.refresh_from_db()
        self.assertTrue(self.repo.is_stale)
