# Copyright 2022 by Open Kilt LLC. All rights reserved.
import os
import tempfile
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import TestCase

from repo.models import PGPSigningKey
from repo.storage.signer import PGPSigner


# ---------------------------------------------------------------------------
# Shared test base — mirrors _PGPKeyManagerBase in test_keyring.py.
# ---------------------------------------------------------------------------

class _PGPSignerBase(TestCase):
    """Sets up an isolated temp KEYRING_PATH for every PGPSigner test method.

    Subclasses that need the keyring directory to already exist (i.e. all
    tests except __init__ tests) should call ``os.makedirs(settings.KEYRING_PATH)``
    in their own ``setUp`` after ``super().setUp()``.
    """

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        settings.KEYRING_PATH = os.path.join(self.test_dir, "keyring")


# ---------------------------------------------------------------------------
# Unit tests — PGPSigner with mocked GPG
# ---------------------------------------------------------------------------

class PGPSignerInitTestCase(_PGPSignerBase):

    def test_creates_keyring_dir_if_missing(self):
        """PGPSigner creates the keyring directory when it does not exist"""
        with patch("gnupg.GPG") as mock_gpg_cls:
            mock_gpg_cls.return_value = MagicMock()
            PGPSigner()
            self.assertTrue(os.path.isdir(settings.KEYRING_PATH))

    def test_init_with_gnupghome_kwarg(self):
        """PGPSigner uses gnupghome kwarg on init"""
        os.makedirs(settings.KEYRING_PATH, exist_ok=True)
        mock_gpg = MagicMock()
        with patch("gnupg.GPG", return_value=mock_gpg) as mock_gpg_cls:
            PGPSigner()
            mock_gpg_cls.assert_called_with(gnupghome=settings.KEYRING_PATH)

    def test_init_fallback_to_homedir(self):
        """PGPSigner falls back to homedir= when gnupghome raises TypeError"""
        os.makedirs(settings.KEYRING_PATH, exist_ok=True)
        mock_gpg = MagicMock()
        with patch("gnupg.GPG", side_effect=[TypeError("no gnupghome"), mock_gpg]):
            signer = PGPSigner()
            self.assertEqual(signer.gpg, mock_gpg)


class PGPSignerEnsureKeyTestCase(_PGPSignerBase):

    def setUp(self):
        super().setUp()
        os.makedirs(settings.KEYRING_PATH)
        self.pgp_key = PGPSigningKey(
            fingerprint="ABCDEF12345",
            private_key_pem="-----PRIVATE-----",
            public_key_pem="-----PUBLIC-----",
            name="Key",
            email="key@example.com",
        )

    @patch("gnupg.GPG")
    def test_ensure_key_imports_when_not_found(self, mock_gpg_cls):
        """ensure_key imports and trusts the key when not already in keyring"""
        mock_gpg = MagicMock()
        mock_gpg_cls.return_value = mock_gpg
        mock_gpg.list_keys.return_value = []

        signer = PGPSigner()
        signer.ensure_key(self.pgp_key)

        mock_gpg.import_keys.assert_called_once_with(self.pgp_key.private_key_pem)
        mock_gpg.trust_keys.assert_called_once_with(self.pgp_key.fingerprint, "TRUST_ULTIMATE")

    @patch("gnupg.GPG")
    def test_ensure_key_skips_import_when_already_present(self, mock_gpg_cls):
        """ensure_key does not import when key already exists in keyring"""
        mock_gpg = MagicMock()
        mock_gpg_cls.return_value = mock_gpg
        mock_gpg.list_keys.return_value = [{"fingerprint": "ABCDEF12345"}]

        signer = PGPSigner()
        signer.ensure_key(self.pgp_key)

        mock_gpg.import_keys.assert_not_called()

    @patch("gnupg.GPG")
    def test_ensure_key_with_multiple_keys_finds_correct(self, mock_gpg_cls):
        """ensure_key correctly matches fingerprint among multiple keys"""
        mock_gpg = MagicMock()
        mock_gpg_cls.return_value = mock_gpg
        mock_gpg.list_keys.return_value = [
            {"fingerprint": "OTHER1"},
            {"fingerprint": "ABCDEF12345"},
        ]

        signer = PGPSigner()
        signer.ensure_key(self.pgp_key)

        mock_gpg.import_keys.assert_not_called()


class PGPSignerDetachSignTestCase(_PGPSignerBase):

    def setUp(self):
        super().setUp()
        os.makedirs(settings.KEYRING_PATH)

    @patch("gnupg.GPG")
    def test_detach_sign_file_calls_gpg_sign_file(self, mock_gpg_cls):
        """detach_sign_file calls gpg.sign_file with the correct arguments"""
        mock_gpg = MagicMock()
        mock_gpg_cls.return_value = mock_gpg

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False,
                                         dir=self.test_dir) as f:
            f.write("some content")
            input_path = f.name

        pgp_key = MagicMock()
        pgp_key.fingerprint = "MYFP123"

        signer = PGPSigner()
        signer.detach_sign_file(pgp_key, "/tmp/out.sig", input_path)

        mock_gpg.sign_file.assert_called_once()
        _, kwargs = mock_gpg.sign_file.call_args
        self.assertEqual(kwargs["keyid"], "MYFP123")
        self.assertTrue(kwargs["detach"])
        self.assertFalse(kwargs["clearsign"])
        self.assertEqual(kwargs["output"], "/tmp/out.sig")

    @patch("gnupg.GPG")
    def test_detach_sign_file_clearsign_param(self, mock_gpg_cls):
        """detach_sign_file passes clearsign=True when clear_sign=True"""
        mock_gpg = MagicMock()
        mock_gpg_cls.return_value = mock_gpg

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False,
                                         dir=self.test_dir) as f:
            f.write("content")
            input_path = f.name

        pgp_key = MagicMock()
        pgp_key.fingerprint = "FP"

        signer = PGPSigner()
        signer.detach_sign_file(pgp_key, "/tmp/out.sig", input_path, clear_sign=True)

        _, kwargs = mock_gpg.sign_file.call_args
        self.assertTrue(kwargs["clearsign"])


# ---------------------------------------------------------------------------
# Integration test — build_repo() → PGPSigner.ensure_key() path
#
# Verifies that the orchestrator correctly instantiates PGPSigner and that
# ensure_key() is called before the adapter runs, using a real (mocked-GPG)
# PGPSigner — the path that was previously untested at this level.
# ---------------------------------------------------------------------------

class BuildRepoSignerIntegrationTestCase(_PGPSignerBase):
    """Verify orchestrator wires PGPSigner into the build pipeline correctly.

    Uses a real Repository/Package/PGPSigningKey DB setup but mocks the GPG
    layer (gnupg.GPG) and the repo adapter to avoid filesystem/subprocess
    dependencies.  The goal is to prove that:

    1. ``build_repo()`` creates a ``PGPSigner`` when a signing key is set.
    2. ``PGPSigner.ensure_key()`` is called with the repo's signing key before
       the adapter's ``setup_repo()`` runs.
    3. No ``PGPKeyManager`` instance is created by
       ``build_repo()`` — that responsibility now belongs solely to
       ``PGPKeysViewSet``.
    """

    def setUp(self):
        from django.contrib.auth import get_user_model
        from repo.models import Repository

        super().setUp()
        settings.STORAGE_PATH = os.path.join(self.test_dir, "storage")
        settings.REPO_WWW_PATH = os.path.join(self.test_dir, "www")
        os.makedirs(settings.KEYRING_PATH)
        os.makedirs(settings.STORAGE_PATH)
        os.makedirs(settings.REPO_WWW_PATH)

        User = get_user_model()
        self.admin = User.objects.create_superuser(username="signer-test-admin", password="p")

        self.signing_key = PGPSigningKey.objects.create(
            name="Build Test Key",
            email="build@example.com",
            fingerprint="BUILDFP1234567890ABCDEF",
            public_key_pem="-----BEGIN PGP PUBLIC KEY BLOCK-----\nfake\n-----END PGP PUBLIC KEY BLOCK-----",
            private_key_pem="-----BEGIN PGP PRIVATE KEY BLOCK-----\nfake\n-----END PGP PRIVATE KEY BLOCK-----",
        )

        self.repo = Repository.objects.create(
            repo_uid="signer-test-repo",
            repo_type="deb",
            signing_key=self.signing_key,
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch("gnupg.GPG")
    @patch("adapters.repo.orchestrator.PGPSigner")
    def test_build_repo_creates_pgpsigner_not_pgpkeymanager(
        self, mock_signer_cls, mock_gpg_cls
    ):
        """build_repo() instantiates PGPSigner (not PGPKeyManager) for signing"""
        from adapters.repo.orchestrator import build_repo

        mock_signer = MagicMock()
        mock_signer_cls.return_value = mock_signer

        # Patch the adapter so it doesn't touch the filesystem
        with patch("adapters.repo.orchestrator._get_adapter_class") as mock_adapter_cls_fn:
            mock_adapter_cls = MagicMock()
            mock_adapter = MagicMock()
            mock_adapter.setup_repo.return_value = True
            mock_adapter_cls.return_value = mock_adapter
            mock_adapter_cls_fn.return_value = mock_adapter_cls

            result = build_repo("signer-test-repo")

        self.assertTrue(result)
        mock_signer_cls.assert_called_once()

    @patch("gnupg.GPG")
    @patch("adapters.repo.orchestrator.PGPSigner")
    def test_build_repo_passes_signer_to_adapter(
        self, mock_signer_cls, mock_gpg_cls
    ):
        """build_repo() passes the PGPSigner instance to the adapter constructor"""
        from adapters.repo.orchestrator import build_repo

        mock_signer = MagicMock()
        mock_signer_cls.return_value = mock_signer

        with patch("adapters.repo.orchestrator._get_adapter_class") as mock_adapter_cls_fn:
            mock_adapter_cls = MagicMock()
            mock_adapter = MagicMock()
            mock_adapter.setup_repo.return_value = True
            mock_adapter_cls.return_value = mock_adapter
            mock_adapter_cls_fn.return_value = mock_adapter_cls

            build_repo("signer-test-repo")

        _, kwargs = mock_adapter_cls.call_args
        self.assertIs(kwargs["signer"], mock_signer)

    @patch("gnupg.GPG")
    @patch("adapters.repo.orchestrator.PGPSigner")
    def test_build_repo_no_signer_when_no_signing_key(
        self, mock_signer_cls, mock_gpg_cls
    ):
        """build_repo() does not create a PGPSigner when the repo has no signing key"""
        from repo.models import Repository
        from adapters.repo.orchestrator import build_repo

        unsigned_repo = Repository.objects.create(
            repo_uid="unsigned-repo",
            repo_type="deb",
            signing_key=None,
        )

        with patch("adapters.repo.orchestrator._get_adapter_class") as mock_adapter_cls_fn:
            mock_adapter_cls = MagicMock()
            mock_adapter = MagicMock()
            mock_adapter.setup_repo.return_value = True
            mock_adapter_cls.return_value = mock_adapter
            mock_adapter_cls_fn.return_value = mock_adapter_cls

            build_repo("unsigned-repo")

        mock_signer_cls.assert_not_called()

        _, kwargs = mock_adapter_cls.call_args
        self.assertIsNone(kwargs["signer"])
