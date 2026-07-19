# Copyright 2022 by Open Kilt LLC. All rights reserved.
import os
import shutil
import tempfile
from io import StringIO
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import TestCase

from repo.models import PGPSigningKey


class ImportPGPPrivateKeyCommandTestCase(TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        settings.KEYRING_PATH = os.path.join(self.test_dir, "keyring")
        os.makedirs(settings.KEYRING_PATH, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_command_file_not_found(self):
        """Command prints error and returns when file does not exist"""
        from django.core.management import call_command

        out = StringIO()
        call_command("import_pgp_private_key", "/nonexistent/path/key.gpg", stdout=out)
        self.assertIn("Cannot find file", out.getvalue())
        self.assertEqual(PGPSigningKey.objects.count(), 0)

    @patch("gnupg.GPG")
    def test_command_imports_key_from_file(self, mock_gpg_cls):
        """Command reads PGP key from file and saves to DB"""
        from django.core.management import call_command

        mock_gpg = MagicMock()
        mock_gpg_cls.return_value = mock_gpg

        # The command does: private_key = gpg.scan_keys(path)
        #   keyinfo = private_key[0]         -> dict-like access
        #   fingerprint = keyinfo["fingerprint"]
        #   parts = keyinfo["uids"][0].split(...)
        #   public_key = gpg.export_keys(private_key.fingerprints[0], False)
        key_dict = {
            "fingerprint": "FAKEFP1234567890",
            "uids": ["Test User <testuser@example.com>"],
        }

        mock_scan_result = MagicMock()
        mock_scan_result.__getitem__ = MagicMock(return_value=key_dict)
        mock_scan_result.fingerprints = ["FAKEFP1234567890"]
        mock_gpg.scan_keys.return_value = mock_scan_result
        mock_gpg.export_keys.return_value = "-----PUBLIC KEY-----"

        # Create a dummy key file
        key_file = os.path.join(self.test_dir, "test_key.gpg")
        with open(key_file, "w") as f:
            f.write("-----BEGIN PGP PRIVATE KEY BLOCK-----\ndummy\n-----END PGP PRIVATE KEY BLOCK-----\n")

        out = StringIO()
        call_command("import_pgp_private_key", key_file, stdout=out)

        self.assertIn("Successfully imported key", out.getvalue())
        self.assertEqual(PGPSigningKey.objects.count(), 1)
        saved = PGPSigningKey.objects.get()
        self.assertEqual(saved.fingerprint, "FAKEFP1234567890")
        self.assertEqual(saved.name, "Test User")
        self.assertEqual(saved.email, "testuser@example.com")


class RefreshKeychainCommandTestCase(TestCase):
    """Test the refresh_keychain management command."""

    def test_command_ensures_every_key_in_keyring(self):
        """refresh_keychain calls PGPKeyring.ensure_key for every stored key"""
        from django.core.management import call_command

        key_a = PGPSigningKey.objects.create(
            name="Key A",
            email="a@example.com",
            fingerprint="FPA1234567890",
            public_key_pem="pub-a",
            private_key_pem="priv-a",
        )
        key_b = PGPSigningKey.objects.create(
            name="Key B",
            email="b@example.com",
            fingerprint="FPB1234567890",
            public_key_pem="pub-b",
            private_key_pem="priv-b",
        )

        out = StringIO()
        with patch("repo.management.commands.refresh_keychain.PGPKeyring") as mock_keyring_cls:
            mock_keyring = MagicMock()
            mock_keyring_cls.return_value = mock_keyring

            call_command("refresh_keychain", stdout=out)

            mock_keyring.ensure_key.assert_any_call(key_a)
            mock_keyring.ensure_key.assert_any_call(key_b)
            self.assertEqual(mock_keyring.ensure_key.call_count, 2)
        self.assertIn("Refreshed 2 PGP key(s) in keyring", out.getvalue())

    def test_command_with_no_keys(self):
        """refresh_keychain runs cleanly when there are no keys to sync"""
        from django.core.management import call_command

        out = StringIO()
        with patch("repo.management.commands.refresh_keychain.PGPKeyring") as mock_keyring_cls:
            mock_keyring = MagicMock()
            mock_keyring_cls.return_value = mock_keyring

            call_command("refresh_keychain", stdout=out)

            mock_keyring.ensure_key.assert_not_called()
        self.assertIn("Refreshed 0 PGP key(s) in keyring", out.getvalue())


class StartupChecksCommandTestCase(TestCase):
    """Test the startup_checks management command."""

    def test_command_calls_refresh_keychain_and_succeeds(self):
        """startup_checks invokes refresh_keychain and reports success"""
        from django.core.management import call_command

        out = StringIO()
        with patch("repo.management.commands.startup_checks.call_command") as mock_call_command:
            call_command("startup_checks", stdout=out)

            mock_call_command.assert_called_once_with("refresh_keychain")
        self.assertIn("Completed startup checks", out.getvalue())


class RunWorkerCommandTestCase(TestCase):
    """Test the runworker management command."""

    def test_command_invalid_thread_count_too_low(self):
        """runworker rejects 0 threads"""
        from django.core.management import call_command

        out = StringIO()
        call_command("runworker", num_threads=0, stdout=out)
        self.assertIn("Invalid number of threads", out.getvalue())

    def test_command_invalid_thread_count_too_high(self):
        """runworker rejects > 100 threads"""
        from django.core.management import call_command

        out = StringIO()
        call_command("runworker", num_threads=101, stdout=out)
        self.assertIn("Invalid number of threads", out.getvalue())

    @patch("repo.management.commands.runworker.BackgroundWorker")
    @patch("repo.management.commands.runworker.time.sleep", side_effect=KeyboardInterrupt)
    def test_command_starts_workers_and_exits_cleanly(self, mock_sleep, mock_worker_cls):
        """runworker starts N worker threads and exits on KeyboardInterrupt"""
        from django.core.management import call_command

        mock_worker = MagicMock()
        mock_worker_cls.return_value = mock_worker

        out = StringIO()
        call_command("runworker", num_threads=2, stdout=out)

        self.assertEqual(mock_worker_cls.call_count, 2)
        self.assertEqual(mock_worker.start.call_count, 2)
        self.assertEqual(mock_worker.stop.call_count, 2)
        self.assertEqual(mock_worker.join.call_count, 2)
        self.assertIn("Worker exited", out.getvalue())

    @patch("repo.management.commands.runworker.BackgroundWorker")
    @patch("repo.management.commands.runworker.time.sleep", side_effect=[None, KeyboardInterrupt])
    def test_command_queues_stale_repos_each_loop(self, mock_sleep, mock_worker_cls):
        """runworker scans for stale repos and queues them for cleaning each iteration"""
        from django.core.management import call_command

        from repo.models import PGPSigningKey, Repository

        signing_key = PGPSigningKey.objects.create(
            name="Worker Key",
            email="worker@example.com",
            fingerprint="RUNWORKER_FP_1",
            public_key_pem="pub",
            private_key_pem="priv",
        )
        stale_repo = Repository.objects.create(
            repo_uid="runworker-stale-repo", repo_type="deb", signing_key=signing_key, is_stale=True
        )

        mock_worker = MagicMock()
        mock_worker_cls.return_value = mock_worker

        with patch("repo.management.commands.runworker.ChoreList") as mock_chore_list_cls:
            mock_chores = MagicMock()
            mock_chore_list_cls.return_value = mock_chores

            out = StringIO()
            call_command("runworker", num_threads=1, stdout=out)

            mock_chores.set_needs_clean.assert_called_once_with(stale_repo.repo_uid)
        self.assertIn("Worker exited", out.getvalue())

    @patch("repo.management.commands.runworker.BackgroundWorker")
    @patch("repo.management.commands.runworker.Repository.objects.filter", side_effect=RuntimeError("db blip"))
    @patch("repo.management.commands.runworker.time.sleep", side_effect=[None, KeyboardInterrupt])
    def test_command_survives_unexpected_exception_in_loop(self, mock_sleep, mock_filter, mock_worker_cls):
        """runworker logs and continues (rather than crashing) on an unexpected error in the loop"""
        from django.core.management import call_command

        mock_worker = MagicMock()
        mock_worker_cls.return_value = mock_worker

        out = StringIO()
        call_command("runworker", num_threads=1, stdout=out)

        self.assertIn("Worker exited", out.getvalue())
