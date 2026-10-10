# Copyright 2022 by Open Kilt LLC. All rights reserved.
import os
import tempfile
from unittest.mock import MagicMock, call, patch

from django.conf import settings
from django.test import TestCase

from repo.models import PGPSigningKey
from repo.storage.keyring import PGPKeyManager


# ---------------------------------------------------------------------------
# Shared test base — sets up a temporary KEYRING_PATH for every test method.
# ---------------------------------------------------------------------------

class _PGPKeyManagerBase(TestCase):
    """Minimal shared setUp for all PGPKeyManager test cases.

    Creates an isolated temp directory and points ``settings.KEYRING_PATH``
    at a ``keyring/`` subdirectory inside it.  Subclasses that need the
    directory to already exist before the code under test runs must call
    ``os.makedirs(settings.KEYRING_PATH)`` in their own ``setUp`` (after
    calling ``super().setUp()``).

    Tests for ``__init__`` deliberately *don't* pre-create the directory so
    they can verify that ``PGPKeyManager`` creates it on demand.
    """

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        settings.KEYRING_PATH = os.path.join(self.test_dir, "keyring")


# ---------------------------------------------------------------------------
# __init__ tests — directory must NOT pre-exist so creation can be asserted.
# ---------------------------------------------------------------------------

class PGPKeyManagerInitTestCase(_PGPKeyManagerBase):

    def test_creates_keyring_dir_if_missing(self):
        """PGPKeyManager creates keyring directory when it does not exist"""
        with patch("gnupg.GPG") as mock_gpg_cls:
            mock_gpg_cls.return_value = MagicMock()
            PGPKeyManager()
            self.assertTrue(os.path.isdir(settings.KEYRING_PATH))

    def test_init_with_gnupghome_kwarg(self):
        """PGPKeyManager tries gnupghome first, falls back to homedir"""
        os.makedirs(settings.KEYRING_PATH, exist_ok=True)
        mock_gpg = MagicMock()
        with patch("gnupg.GPG", return_value=mock_gpg) as mock_gpg_cls:
            PGPKeyManager()
            mock_gpg_cls.assert_called_with(gnupghome=settings.KEYRING_PATH)

    def test_init_fallback_to_homedir(self):
        """PGPKeyManager falls back to homedir= kwarg when gnupghome raises TypeError"""
        os.makedirs(settings.KEYRING_PATH, exist_ok=True)
        mock_gpg = MagicMock()
        with patch("gnupg.GPG", side_effect=[TypeError("no gnupghome"), mock_gpg]):
            mgr = PGPKeyManager()
            self.assertEqual(mgr.gpg, mock_gpg)


# ---------------------------------------------------------------------------
# generate_key tests — keyring dir must exist before PGPKeyManager is built.
# ---------------------------------------------------------------------------

class PGPKeyManagerGenerateKeyTestCase(_PGPKeyManagerBase):

    def setUp(self):
        super().setUp()
        os.makedirs(settings.KEYRING_PATH)

    @patch("gnupg.GPG")
    def test_generate_key_creates_db_entry(self, mock_gpg_cls):
        """generate_key saves a new PGPSigningKey to the database"""
        mock_gpg = MagicMock()
        mock_gpg_cls.return_value = mock_gpg

        fake_key = MagicMock()
        fake_key.fingerprint = "ABCDEF1234567890ABCDEF1234567890ABCDEF12"
        mock_gpg.gen_key.return_value = fake_key
        mock_gpg.export_keys.side_effect = ["-----PUBLIC KEY-----", "-----PRIVATE KEY-----"]

        mgr = PGPKeyManager()
        result = mgr.generate_key("Test User", "test@example.com")

        self.assertEqual(PGPSigningKey.objects.count(), 1)
        saved = PGPSigningKey.objects.get()
        self.assertEqual(saved.fingerprint, fake_key.fingerprint)
        self.assertEqual(saved.name, "Test User")
        self.assertEqual(saved.email, "test@example.com")
        self.assertEqual(result, saved)

    @patch("gnupg.GPG")
    def test_generate_key_calls_gen_key_input(self, mock_gpg_cls):
        """generate_key builds RSA-4096 key input with correct parameters"""
        mock_gpg = MagicMock()
        mock_gpg_cls.return_value = mock_gpg
        fake_key = MagicMock()
        fake_key.fingerprint = "FP123"
        mock_gpg.gen_key.return_value = fake_key
        mock_gpg.export_keys.side_effect = ["pub", "priv"]

        mgr = PGPKeyManager()
        mgr.generate_key("Alice", "alice@example.com")

        mock_gpg.gen_key_input.assert_called_once_with(
            key_type="RSA",
            key_length=4096,
            expire_date="50y",
            name_real="Alice",
            name_email="alice@example.com",
            no_protection=True,
        )


# ---------------------------------------------------------------------------
# delete tests — keyring dir must exist before PGPKeyManager is built.
# ---------------------------------------------------------------------------

class PGPKeyManagerDeleteTestCase(_PGPKeyManagerBase):

    def setUp(self):
        super().setUp()
        os.makedirs(settings.KEYRING_PATH)

    @patch("gnupg.GPG")
    def test_delete_calls_gpg_delete_keys_twice(self, mock_gpg_cls):
        """delete() removes private then public key from the keyring"""
        mock_gpg = MagicMock()
        mock_gpg_cls.return_value = mock_gpg

        mgr = PGPKeyManager()
        mgr.delete("FINGERPRINT123")

        expected = [
            call("FINGERPRINT123", secret=True, passphrase=""),
            call("FINGERPRINT123", secret=False),
        ]
        mock_gpg.delete_keys.assert_has_calls(expected)

    @patch("gnupg.GPG")
    def test_delete_passes_passphrase_to_secret_key_removal(self, mock_gpg_cls):
        """delete() forwards the passphrase when removing a protected private key"""
        mock_gpg = MagicMock()
        mock_gpg_cls.return_value = mock_gpg

        mgr = PGPKeyManager()
        mgr.delete("FP456", passphrase="s3cr3t")

        mock_gpg.delete_keys.assert_any_call("FP456", secret=True, passphrase="s3cr3t")
