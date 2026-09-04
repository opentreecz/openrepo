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

"""
Tests for Phase 1.3 — Structured error responses.

Verifies that:
- All API errors return the standard envelope: {"code", "detail", "status"}
- Conflict situations return HTTP 409 with code PACKAGE_EXISTS / KEY_IN_USE
- The custom exception handler wraps DRF exceptions correctly
- UploadTask.error_code is set to PACKAGE_EXISTS on duplicate upload
"""

import os
import shutil
import tempfile
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase, APIClient
from django.test import TestCase

from repo.api.errors import ApiErrorCode
from repo.api.exception_handler import _flatten_detail, openrepo_exception_handler
from repo.api.upload_processor import process_upload
from repo.models import Package, PGPSigningKey, Repository, UploadTask


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_signing_key(suffix=""):
    return PGPSigningKey.objects.create(
        name=f"Test Key{suffix}",
        email=f"test{suffix}@example.com",
        fingerprint=f"TESTFP{suffix}1234567890",
        public_key_pem="pub",
        private_key_pem="priv",
    )


class StructuredErrorApiTestCase(APITestCase):
    """API-level tests that exercise the error envelope via real HTTP calls."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_superuser(
            username="errtest", email="errtest@test.com", password="password123"
        )
        token = Token.objects.get(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

        self.signing_key = _make_signing_key()
        self.repo = Repository.objects.create(
            repo_uid="err-test-repo",
            repo_type="files",
            signing_key=self.signing_key,
        )

        self.test_dir = tempfile.mkdtemp()
        settings.STORAGE_PATH = self.test_dir

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # ── Error envelope shape ────────────────────────────────────────────────

    def test_404_returns_error_envelope(self):
        """A missing resource returns the structured error envelope with code NOT_FOUND."""
        response = self.client.get("/api/nonexistent-repo/packages/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        data = response.json()
        self.assertIn("code", data)
        self.assertIn("detail", data)
        self.assertIn("status", data)
        self.assertEqual(data["status"], 404)

    def test_validation_error_returns_error_envelope(self):
        """A validation error (missing required field) returns the structured envelope."""
        response = self.client.post("/api/repos/", {"repo_uid": "x"}, format="json")
        self.assertIn(response.status_code, [400, 403])
        data = response.json()
        self.assertIn("code", data)
        self.assertIn("detail", data)
        self.assertIn("status", data)

    def test_unauthenticated_returns_error_envelope(self):
        """An unauthenticated request returns the structured envelope."""
        unauth_client = APIClient()
        response = unauth_client.get("/api/whoami")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        data = response.json()
        self.assertIn("code", data)
        self.assertEqual(data["code"], ApiErrorCode.AUTHENTICATION_FAILED)
        self.assertIn("detail", data)
        self.assertIn("status", data)

    # ── PGP key delete — KEY_IN_USE → 409 ──────────────────────────────────

    def test_delete_pgp_key_in_use_returns_409(self):
        """Deleting a PGP key that is referenced by a repo returns 409 KEY_IN_USE."""
        response = self.client.delete(f"/api/signingkeys/{self.signing_key.fingerprint}/")
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        data = response.json()
        self.assertEqual(data["code"], ApiErrorCode.KEY_IN_USE)
        self.assertIn("detail", data)
        self.assertEqual(data["status"], 409)

    def test_delete_pgp_key_not_in_use_succeeds(self):
        """Deleting a PGP key not referenced by any repo succeeds (204)."""
        unused_key = _make_signing_key(suffix="unused")
        with patch("repo.storage.keyring.PGPKeyring.delete"):
            response = self.client.delete(f"/api/signingkeys/{unused_key.fingerprint}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    # ── Copy — PACKAGE_EXISTS → 409 ────────────────────────────────────────

    def test_copy_duplicate_package_returns_409(self):
        """Copying a package that already exists in the destination returns 409 PACKAGE_EXISTS."""
        import uuid
        from datetime import datetime, timezone

        dst_repo = Repository.objects.create(
            repo_uid="err-dst-repo",
            repo_type="files",
            signing_key=self.signing_key,
        )
        # Create the same package in both repos
        pkg_uid = str(uuid.uuid4()).replace("-", "")
        for repo in [self.repo, dst_repo]:
            Package.objects.create(
                repo=repo,
                package_uid=pkg_uid,
                filename="tool-1.0.0.bin",
                package_name="tool",
                architecture="any",
                version="1.0.0",
                upload_date=datetime.now(tz=timezone.utc),
                checksum_sha512="a" * 128,
            )

        src_pkg = Package.objects.get(repo=self.repo, package_name="tool")
        response = self.client.post(
            f"/api/{self.repo.repo_uid}/pkg/{src_pkg.package_uid}/copy/",
            {"dest_repo_uid": dst_repo.repo_uid},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        data = response.json()
        self.assertEqual(data["code"], ApiErrorCode.PACKAGE_EXISTS)
        self.assertEqual(data["status"], 409)


# ---------------------------------------------------------------------------
# UploadTask.error_code tests (unit-level, via upload_processor)
# ---------------------------------------------------------------------------

class UploadTaskErrorCodeTestCase(TestCase):
    """Verify that error_code is set correctly on UploadTask after processing."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        settings.STORAGE_PATH = self.test_dir

        self.signing_key = _make_signing_key(suffix="proc")
        self.repo = Repository.objects.create(
            repo_uid="err-proc-repo",
            repo_type="files",
            signing_key=self.signing_key,
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _write_stored_file(self, content=b"data"):
        import uuid
        path = os.path.join(self.test_dir, str(uuid.uuid4()))
        with open(path, "wb") as f:
            f.write(content)
        return path

    def _make_task(self, overwrite=False, content=b"data"):
        return UploadTask.objects.create(
            repo=self.repo,
            status="stored",
            filename="pkg-1.0.0.bin",
            filesize=len(content),
            overwrite=overwrite,
            stored_path=self._write_stored_file(content),
        )

    def _mock_adapter(self, name="pkg", version="1.0.0", arch="any"):
        from unittest.mock import MagicMock
        adapter = MagicMock()
        adapter.get_name.return_value = name
        adapter.get_version.return_value = version
        adapter.get_architecture.return_value = arch
        adapter.get_builddate.return_value = None
        return adapter

    @patch("repo.api.upload_processor.create_adapter")
    def test_duplicate_upload_sets_error_code_package_exists(self, mock_create_adapter):
        """When a duplicate upload fails, error_code is set to PACKAGE_EXISTS."""
        mock_create_adapter.return_value = self._mock_adapter()

        # First upload succeeds
        process_upload(self._make_task().pk)

        # Second upload is a duplicate
        dup_task = self._make_task()
        process_upload(dup_task.pk)

        dup_task.refresh_from_db()
        self.assertEqual(dup_task.status, "failed")
        self.assertEqual(dup_task.error_code, ApiErrorCode.PACKAGE_EXISTS)
        self.assertIn("already exists", dup_task.error_message)

    @patch("repo.api.upload_processor.create_adapter")
    def test_generic_failure_has_empty_error_code(self, mock_create_adapter):
        """A non-conflict failure leaves error_code empty."""
        adapter = self._mock_adapter()
        adapter.get_version.side_effect = RuntimeError("unexpected error")
        mock_create_adapter.return_value = adapter

        task = self._make_task()
        process_upload(task.pk)

        task.refresh_from_db()
        self.assertEqual(task.status, "failed")
        self.assertEqual(task.error_code, "")

    @patch("repo.api.upload_processor.create_adapter")
    def test_successful_upload_has_empty_error_code(self, mock_create_adapter):
        """A successful upload leaves error_code empty."""
        mock_create_adapter.return_value = self._mock_adapter()
        task = self._make_task()
        process_upload(task.pk)

        task.refresh_from_db()
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.error_code, "")


# ---------------------------------------------------------------------------
# Exception handler unit tests
# ---------------------------------------------------------------------------

class FlattenDetailTestCase(TestCase):
    """Unit tests for the _flatten_detail helper."""

    def test_dict_with_detail_key(self):
        self.assertEqual(_flatten_detail({"detail": "Not found"}), "Not found")

    def test_dict_with_field_errors(self):
        result = _flatten_detail({"name": ["This field is required."]})
        self.assertIn("name", result)
        self.assertIn("This field is required.", result)

    def test_list_of_errors(self):
        result = _flatten_detail(["error one", "error two"])
        self.assertIn("error one", result)
        self.assertIn("error two", result)

    def test_plain_string(self):
        self.assertEqual(_flatten_detail("something went wrong"), "something went wrong")
