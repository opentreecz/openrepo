# Copyright 2022 by Open Kilt LLC. All rights reserved.
import datetime
import os
import tempfile
import threading
import uuid
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from repo.models import Package, PGPSigningKey, Repository, UploadTask


class CopyViewSetTestCase(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username="copy_admin", password="password123")
        self.admin_token = Token.objects.get(user=self.admin).key

        self.signing_key = PGPSigningKey.objects.create(
            name="CopyKey",
            email="copy@example.com",
            fingerprint="COPY_FP_12345678",
            public_key_pem="pub",
            private_key_pem="priv",
        )
        self.repo_deb = Repository.objects.create(
            repo_uid="copy-src-deb", repo_type="deb", signing_key=self.signing_key
        )
        self.repo_deb2 = Repository.objects.create(
            repo_uid="copy-dst-deb", repo_type="deb", signing_key=self.signing_key
        )
        self.repo_rpm = Repository.objects.create(
            repo_uid="copy-dst-rpm", repo_type="rpm", signing_key=self.signing_key
        )
        self.repo_files = Repository.objects.create(
            repo_uid="copy-dst-files", repo_type="files", signing_key=self.signing_key
        )
        self.pkg = Package.objects.create(
            repo=self.repo_deb,
            package_uid="copy-test-pkg",
            filename="hello.deb",
            package_name="hello",
            version="1.0",
            architecture="all",
            upload_date=datetime.datetime.now(tz=datetime.timezone.utc),
            checksum_sha512="copy_hash",
        )

    def test_copy_deb_to_deb_succeeds(self):
        """Copying a deb package to another deb repo succeeds"""
        response = self.client.post(
            f"/api/{self.repo_deb.repo_uid}/pkg/{self.pkg.package_uid}/copy/",
            {"dest_repo_uid": self.repo_deb2.repo_uid},
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(Package.objects.filter(repo=self.repo_deb2, package_uid=self.pkg.package_uid).exists())

    def test_copy_deb_to_rpm_fails(self):
        """Copying a deb package to an rpm repo fails with 400"""
        response = self.client.post(
            f"/api/{self.repo_deb.repo_uid}/pkg/{self.pkg.package_uid}/copy/",
            {"dest_repo_uid": self.repo_rpm.repo_uid},
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Incompatible destination repository", response.data["detail"])

    def test_copy_deb_to_generic_succeeds(self):
        """Copying any package to a generic 'files' repo succeeds"""
        response = self.client.post(
            f"/api/{self.repo_deb.repo_uid}/pkg/{self.pkg.package_uid}/copy/",
            {"dest_repo_uid": self.repo_files.repo_uid},
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_copy_to_nonexistent_repo_fails(self):
        """Copying to a non-existent destination returns 404"""
        response = self.client.post(
            f"/api/{self.repo_deb.repo_uid}/pkg/{self.pkg.package_uid}/copy/",
            {"dest_repo_uid": "nonexistent-repo"},
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_copy_duplicate_version_fails(self):
        """Copying a package that already exists in destination (same package_uid) fails"""
        # First copy succeeds
        self.client.post(
            f"/api/{self.repo_deb.repo_uid}/pkg/{self.pkg.package_uid}/copy/",
            {"dest_repo_uid": self.repo_deb2.repo_uid},
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
        )
        # Copying the exact same package_uid again should fail (already exists)
        response = self.client.post(
            f"/api/{self.repo_deb.repo_uid}/pkg/{self.pkg.package_uid}/copy/",
            {"dest_repo_uid": self.repo_deb2.repo_uid},
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_copy_from_nonexistent_source_repo_fails(self):
        """Copying from a non-existent source repo returns 404"""
        response = self.client.post(
            f"/api/nonexistent-src-repo/pkg/{self.pkg.package_uid}/copy/",
            {"dest_repo_uid": self.repo_deb2.repo_uid},
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn("Source repo_uid", response.data["detail"])

    def test_copy_nonexistent_package_fails(self):
        """Copying a package_uid that doesn't exist in the source repo returns 404"""
        response = self.client.post(
            f"/api/{self.repo_deb.repo_uid}/pkg/nonexistent-pkg-uid/copy/",
            {"dest_repo_uid": self.repo_deb2.repo_uid},
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn("not found in repo", response.data["detail"])

    def test_copy_identical_package_uid_with_different_metadata_fails(self):
        """A pre-existing Package with the same package_uid but different name/version still blocks the copy"""
        Package.objects.create(
            repo=self.repo_deb2,
            package_uid=self.pkg.package_uid,
            filename="other.deb",
            package_name="totally-different-name",
            version="9.9",
            architecture="all",
            upload_date=datetime.datetime.now(tz=datetime.timezone.utc),
            checksum_sha512="other_hash",
        )

        response = self.client.post(
            f"/api/{self.repo_deb.repo_uid}/pkg/{self.pkg.package_uid}/copy/",
            {"dest_repo_uid": self.repo_deb2.repo_uid},
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("identical package already exists", response.data["detail"])

    def test_copy_same_name_version_different_architecture_succeeds(self):
        """Same package/version can be copied when destination only has a different architecture."""
        self.pkg.architecture = "amd64"
        self.pkg.save()
        Package.objects.create(
            repo=self.repo_deb2,
            package_uid="copy-test-pkg-arm64",
            filename="hello-arm64.deb",
            package_name="hello",
            version="1.0",
            architecture="arm64",
            upload_date=datetime.datetime.now(tz=datetime.timezone.utc),
            checksum_sha512="arm64_hash",
        )

        response = self.client.post(
            f"/api/{self.repo_deb.repo_uid}/pkg/{self.pkg.package_uid}/copy/",
            {"dest_repo_uid": self.repo_deb2.repo_uid},
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(
            Package.objects.filter(
                repo=self.repo_deb2,
                package_name="hello",
                version="1.0",
                architecture="amd64",
            ).exists()
        )


class KeepOnlyLatestTestCase(APITestCase):
    """Test keep_only_latest flag behavior during upload and copy."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username="latest_admin", password="password123")
        self.admin_token = Token.objects.get(user=self.admin).key

        self.signing_key = PGPSigningKey.objects.create(
            name="LatestKey",
            email="latest@example.com",
            fingerprint="LATEST_FP_1234",
            public_key_pem="pub",
            private_key_pem="priv",
        )
        self.src_repo = Repository.objects.create(
            repo_uid="latest-src", repo_type="deb", signing_key=self.signing_key
        )
        self.dst_repo = Repository.objects.create(
            repo_uid="latest-dst",
            repo_type="deb",
            signing_key=self.signing_key,
            retention_policy=Repository.RETENTION_KEEP_LATEST_N,
            retention_keep_count=1,
        )

    def test_copy_with_keep_only_latest_removes_older(self):
        """retention_policy=keep_latest_n/count=1 on dst removes older versions after copy"""
        # Create an old package in dst
        old_pkg = Package.objects.create(
            repo=self.dst_repo,
            package_uid="latest-old-pkg",
            filename="myapp-0.9.deb",
            package_name="myapp",
            version="0.9",
            architecture="all",
            upload_date=datetime.datetime.now(tz=datetime.timezone.utc),
            checksum_sha512="old_hash",
        )
        # Create a new package in src
        new_pkg = Package.objects.create(
            repo=self.src_repo,
            package_uid="latest-new-pkg",
            filename="myapp-1.0.deb",
            package_name="myapp",
            version="1.0",
            architecture="all",
            upload_date=datetime.datetime.now(tz=datetime.timezone.utc),
            checksum_sha512="new_hash",
        )
        response = self.client.post(
            f"/api/{self.src_repo.repo_uid}/pkg/{new_pkg.package_uid}/copy/",
            {"dest_repo_uid": self.dst_repo.repo_uid},
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Old package should be gone
        self.assertFalse(Package.objects.filter(pk=old_pkg.pk).exists())
        # New package should exist
        self.assertTrue(Package.objects.filter(repo=self.dst_repo, package_name="myapp", version="1.0").exists())


class RepoDetailApiTestCase(APITestCase):
    """Test repo detail endpoint."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username="detail_admin", password="password123")
        self.admin_token = Token.objects.get(user=self.admin).key

        self.signing_key = PGPSigningKey.objects.create(
            name="DetailKey",
            email="detail@example.com",
            fingerprint="DETAIL_FP_1234",
            public_key_pem="pub",
            private_key_pem="priv",
        )
        self.repo = Repository.objects.create(
            repo_uid="detail-repo",
            repo_type="deb",
            signing_key=self.signing_key,
        )

    def test_get_repo_detail(self):
        """GET /api/<repo>/ returns repo details"""
        response = self.client.get(f"/api/{self.repo.repo_uid}/", HTTP_AUTHORIZATION=f"Token {self.admin_token}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["repo_uid"], self.repo.repo_uid)
        self.assertIn("repo_instructions", response.data)
        self.assertIn("signing_key", response.data)

    def test_repo_instructions_contain_apt_update(self):
        """repo_instructions for deb type contain apt commands"""
        response = self.client.get(f"/api/{self.repo.repo_uid}/", HTTP_AUTHORIZATION=f"Token {self.admin_token}")
        self.assertIn("apt update", response.data["repo_instructions"])

    def test_list_repos(self):
        """GET /api/repos/ returns a list"""
        response = self.client.get("/api/repos/", HTTP_AUTHORIZATION=f"Token {self.admin_token}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.data)

    def test_update_signing_key_marks_stale(self):
        """Updating a repo's signing key marks it as stale"""
        new_key = PGPSigningKey.objects.create(
            name="New Key",
            email="new@example.com",
            fingerprint="NEW_FP_5678",
            public_key_pem="pub2",
            private_key_pem="priv2",
        )
        response = self.client.put(
            f"/api/{self.repo.repo_uid}/",
            {
                "repo_uid": self.repo.repo_uid,
                "repo_type": self.repo.repo_type,
                "signing_key": new_key.fingerprint,
                "retention_policy": "none",
            },
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.repo.refresh_from_db()
        self.assertTrue(self.repo.is_stale)


class BuildApiTestCase(APITestCase):
    """Test build and build log API endpoints."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username="build_admin", password="password123")
        self.admin_token = Token.objects.get(user=self.admin).key

        self.signing_key = PGPSigningKey.objects.create(
            name="BuildKey",
            email="build@example.com",
            fingerprint="BUILD_FP_1234",
            public_key_pem="pub",
            private_key_pem="priv",
        )
        self.repo = Repository.objects.create(
            repo_uid="build-test-repo",
            repo_type="deb",
            signing_key=self.signing_key,
        )
        from repo.models import Build, BuildLogLine

        self.build = Build.objects.create(
            repo=self.repo,
            build_number=1,
            completion_status=Build.STATUS_COMPLETE_SUCCESS,
        )
        self.log_line = BuildLogLine.objects.create(
            build=self.build,
            command="createrepo",
            message="OK",
            loglevel="info",
            line_number=0,
            execution_time_sec=1.5,
            exec_complete=True,
        )

    def test_list_builds(self):
        """GET /api/builds/ returns a list"""
        response = self.client.get("/api/builds/", HTTP_AUTHORIZATION=f"Token {self.admin_token}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["build_number"], 1)

    def test_list_build_logs(self):
        """GET /api/buildlogs/ returns a list"""
        response = self.client.get("/api/buildlogs/", HTTP_AUTHORIZATION=f"Token {self.admin_token}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["command"], "createrepo")


class FilenameSanitizationTestCase(APITestCase):
    """Test that uploaded filenames are sanitized against path traversal and control characters."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username="san_admin", password="password123")
        self.admin_token = Token.objects.get(user=self.admin).key

        self.test_dir = tempfile.mkdtemp()
        settings.STORAGE_PATH = self.test_dir

        self.signing_key = PGPSigningKey.objects.create(
            name="SanKey",
            email="san@example.com",
            fingerprint="SAN_FP_12345678",
            public_key_pem="pub",
            private_key_pem="priv",
        )
        self.repo = Repository.objects.create(
            repo_uid="san-repo", repo_type="files", signing_key=self.signing_key
        )

    def _upload(self, filename, content=b"dummy package content"):
        upload_file = SimpleUploadedFile(filename, content, content_type="application/octet-stream")
        return self.client.post(
            f"/api/{self.repo.repo_uid}/upload/",
            data={"package_file": upload_file},
            format="multipart",
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
        )

    @patch.object(threading.Thread, "start", lambda self: None)
    def test_path_traversal_filename_is_stripped(self):
        """Filenames with path traversal sequences are reduced to the basename."""
        response = self._upload("../../etc/evil.deb")
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        task = UploadTask.objects.get(pk=response.data["task_id"])
        self.assertEqual(task.filename, "evil.deb")

    @patch.object(threading.Thread, "start", lambda self: None)
    def test_absolute_path_filename_is_stripped(self):
        """Absolute path filenames are reduced to the basename."""
        response = self._upload("/tmp/secret/payload.rpm")
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        task = UploadTask.objects.get(pk=response.data["task_id"])
        self.assertEqual(task.filename, "payload.rpm")

    @patch.object(threading.Thread, "start", lambda self: None)
    def test_normal_filename_unchanged(self):
        """A plain filename without path components is stored as-is."""
        response = self._upload("my-package-1.0.deb")
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        task = UploadTask.objects.get(pk=response.data["task_id"])
        self.assertEqual(task.filename, "my-package-1.0.deb")

    def test_null_byte_in_filename_sanitized_by_django(self):
        """Django's multipart parser strips null bytes — the resulting filename is still valid."""
        response = self._upload("evil\x00.deb")
        # Django strips null bytes before our code runs, so the upload succeeds
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        task = UploadTask.objects.get(pk=response.data["task_id"])
        self.assertNotIn("\x00", task.filename)

    def test_control_char_in_filename_sanitized_by_django(self):
        """Django's multipart parser strips control characters — filename still valid."""
        response = self._upload("evil\x0a.deb")
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        task = UploadTask.objects.get(pk=response.data["task_id"])
        self.assertNotIn("\x0a", task.filename)


class OverwriteUploadTestCase(APITestCase):
    """Test the overwrite=true/false behavior during package upload."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username="ow_admin", password="password123")
        self.admin_token = Token.objects.get(user=self.admin).key

        self.test_dir = tempfile.mkdtemp()
        settings.STORAGE_PATH = self.test_dir

        self.signing_key = PGPSigningKey.objects.create(
            name="OWKey",
            email="ow@example.com",
            fingerprint="OW_FP_12345678",
            public_key_pem="pub",
            private_key_pem="priv",
        )
        self.repo = Repository.objects.create(repo_uid="ow-repo", repo_type="deb", signing_key=self.signing_key)

    def _upload_deb(self, overwrite="0"):
        cur_dir = os.path.dirname(os.path.realpath(__file__))
        deb_path = os.path.join(cur_dir, "unittest_files/hello-world_1.0.0_all.deb")
        with open(deb_path, "rb") as f:
            response = self.client.post(
                f"/api/{self.repo.repo_uid}/upload/",
                data={"package_file": f, "overwrite": overwrite},
                format="multipart",
                HTTP_AUTHORIZATION=f"Token {self.admin_token}",
            )
        return response

    @patch.object(threading.Thread, "start", lambda self: self.run())
    def test_upload_duplicate_without_overwrite_fails(self):
        """Uploading the same package twice without overwrite fails"""
        self._upload_deb()
        response = self._upload_deb()
        # Async upload returns 202; the UploadTask status will be 'failed' with an error
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        task_id = response.data["task_id"]
        status_response = self.client.get(
            f"/api/upload-status/{task_id}/",
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
        )
        self.assertEqual(status_response.data["status"], "failed")
        self.assertIn("already exists", status_response.data["error_message"])

    @patch.object(threading.Thread, "start", lambda self: self.run())
    def test_upload_duplicate_with_overwrite_succeeds(self):
        """Uploading the same package twice with overwrite=true replaces it"""
        self._upload_deb()
        response = self._upload_deb(overwrite="true")
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        task_id = response.data["task_id"]
        status_response = self.client.get(
            f"/api/upload-status/{task_id}/",
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
        )
        self.assertEqual(status_response.data["status"], "completed")
        # Should still only have one package
        self.assertEqual(Package.objects.filter(repo=self.repo, package_name="hello-world").count(), 1)

    @patch.object(threading.Thread, "start", lambda self: self.run())
    def test_upload_overwrite_yes_string(self):
        """overwrite='yes' is treated as True"""
        self._upload_deb()
        response = self._upload_deb(overwrite="yes")
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        task_id = response.data["task_id"]
        status_response = self.client.get(
            f"/api/upload-status/{task_id}/",
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
        )
        self.assertEqual(status_response.data["status"], "completed")

    def test_upload_without_package_file_returns_400(self):
        """Missing package_file is reported as validation error instead of server error."""
        response = self.client.post(
            f"/api/{self.repo.repo_uid}/upload/",
            data={"overwrite": "0"},
            format="multipart",
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # Structured error envelope wraps field errors into "detail" string
        self.assertIn("package_file", response.data.get("detail", response.data))


class PGPKeyApiTestCase(APITestCase):
    """Test PGP key management API."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username="pgp_admin", password="password123")
        self.admin_token = Token.objects.get(user=self.admin).key

        self.signing_key = PGPSigningKey.objects.create(
            name="PGPKey",
            email="pgp@example.com",
            fingerprint="PGP_FP_12345678",
            public_key_pem="pub",
            private_key_pem="priv",
        )

    def test_list_signing_keys(self):
        """GET /api/signingkeys/ returns the keys"""
        response = self.client.get("/api/signingkeys/", HTTP_AUTHORIZATION=f"Token {self.admin_token}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

    def test_delete_signing_key_referenced_by_repo_fails(self):
        """Deleting a signing key used by a repo returns 400"""
        Repository.objects.create(
            repo_uid="pgp-ref-repo",
            repo_type="deb",
            signing_key=self.signing_key,
        )
        response = self.client.delete(
            f"/api/signingkeys/{self.signing_key.fingerprint}/",
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("Unable to delete", response.data["detail"])


class UploadStatusAuthorizationTestCase(APITestCase):
    """Test upload-status authorization for non-superusers."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username="authz_admin", password="password123")
        self.admin_token = Token.objects.get(user=self.admin).key

        self.regular_user = User.objects.create_user(username="authz_regular", password="password123")
        self.regular_token = Token.objects.get(user=self.regular_user).key

        self.signing_key = PGPSigningKey.objects.create(
            name="AuthzKey", email="authz@example.com",
            fingerprint="AUTHZ_FP_12345678", public_key_pem="pub", private_key_pem="priv",
        )
        self.repo = Repository.objects.create(
            repo_uid="authz-repo", repo_type="files", signing_key=self.signing_key,
        )
        self.task = UploadTask.objects.create(
            repo=self.repo, status="completed", filename="test.deb",
            filesize=100, stored_path="/tmp/fake",
        )

    def test_superuser_can_see_any_upload_status(self):
        """Superuser can poll any upload task."""
        response = self.client.get(
            f"/api/upload-status/{self.task.pk}/",
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_user_without_write_access_gets_404(self):
        """Non-superuser without write access gets 404 (not 403, to avoid leaking task existence)."""
        response = self.client.get(
            f"/api/upload-status/{self.task.pk}/",
            HTTP_AUTHORIZATION=f"Token {self.regular_token}",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_user_with_write_access_can_see_upload_status(self):
        """Non-superuser with write access to the repo can poll the task."""
        self.repo.write_access.add(self.regular_user)
        response = self.client.get(
            f"/api/upload-status/{self.task.pk}/",
            HTTP_AUTHORIZATION=f"Token {self.regular_token}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_nonexistent_task_returns_404(self):
        """Polling a non-existent task ID returns 404."""
        response = self.client.get(
            f"/api/upload-status/{uuid.uuid4()}/",
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class MaxUploadSizeTestCase(APITestCase):
    """Test that MAX_UPLOAD_SIZE is enforced."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username="size_admin", password="password123")
        self.admin_token = Token.objects.get(user=self.admin).key

        self.test_dir = tempfile.mkdtemp()
        settings.STORAGE_PATH = self.test_dir

        self.signing_key = PGPSigningKey.objects.create(
            name="SizeKey", email="size@example.com",
            fingerprint="SIZE_FP_12345678", public_key_pem="pub", private_key_pem="priv",
        )
        self.repo = Repository.objects.create(
            repo_uid="size-repo", repo_type="files", signing_key=self.signing_key,
        )

    def test_oversized_upload_rejected(self):
        """Uploading a file exceeding MAX_UPLOAD_SIZE returns 400."""
        original_max = settings.MAX_UPLOAD_SIZE
        settings.MAX_UPLOAD_SIZE = 10  # 10 bytes
        try:
            upload_file = SimpleUploadedFile(
                "big.deb", b"x" * 100, content_type="application/octet-stream",
            )
            response = self.client.post(
                f"/api/{self.repo.repo_uid}/upload/",
                data={"package_file": upload_file},
                format="multipart",
                HTTP_AUTHORIZATION=f"Token {self.admin_token}",
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        finally:
            settings.MAX_UPLOAD_SIZE = original_max


class VersionHeaderMiddlewareTestCase(APITestCase):
    """Test that the X-OpenRepo-Version header is present on API responses."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username="ver_admin", password="password123")
        self.admin_token = Token.objects.get(user=self.admin).key

    def test_api_response_has_version_header(self):
        """All API responses include X-OpenRepo-Version header."""
        response = self.client.get("/api/health/")
        self.assertIn("X-OpenRepo-Version", response)

    def test_version_header_on_authenticated_endpoint(self):
        """Authenticated endpoints also include the version header."""
        response = self.client.get("/api/repos/", HTTP_AUTHORIZATION=f"Token {self.admin_token}")
        self.assertIn("X-OpenRepo-Version", response)


class V1PrefixRoutingTestCase(APITestCase):
    """Test that /api/v1/ prefix works as an alias for /api/."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username="v1_admin", password="password123")
        self.admin_token = Token.objects.get(user=self.admin).key

    def test_v1_repos_returns_same_as_api_repos(self):
        """GET /api/v1/repos/ returns the same data as GET /api/repos/."""
        resp_api = self.client.get("/api/repos/", HTTP_AUTHORIZATION=f"Token {self.admin_token}")
        resp_v1 = self.client.get("/api/v1/repos/", HTTP_AUTHORIZATION=f"Token {self.admin_token}")
        self.assertEqual(resp_api.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_v1.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_api.data["count"], resp_v1.data["count"])

    def test_v1_health_endpoint(self):
        """GET /api/v1/health/ works."""
        response = self.client.get("/api/v1/health/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "ok")


class PackagesSearchFilterTestCase(APITestCase):
    """Test package search and filter functionality."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username="search_admin", password="password123")
        self.admin_token = Token.objects.get(user=self.admin).key

        self.signing_key = PGPSigningKey.objects.create(
            name="SearchKey", email="search@example.com",
            fingerprint="SEARCH_FP_12345678", public_key_pem="pub", private_key_pem="priv",
        )
        self.repo = Repository.objects.create(
            repo_uid="search-repo", repo_type="deb", signing_key=self.signing_key,
        )
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        Package.objects.create(
            repo=self.repo, package_uid="pkg-nginx-amd64",
            filename="nginx_1.0_amd64.deb", package_name="nginx",
            version="1.0", architecture="amd64",
            upload_date=now, checksum_sha512="hash1",
        )
        Package.objects.create(
            repo=self.repo, package_uid="pkg-nginx-arm64",
            filename="nginx_1.0_arm64.deb", package_name="nginx",
            version="1.0", architecture="arm64",
            upload_date=now, checksum_sha512="hash2",
        )
        Package.objects.create(
            repo=self.repo, package_uid="pkg-curl-amd64",
            filename="curl_2.0_amd64.deb", package_name="curl",
            version="2.0", architecture="amd64",
            upload_date=now, checksum_sha512="hash3",
        )

    def test_search_by_package_name(self):
        """?search=nginx returns only nginx packages."""
        response = self.client.get(
            f"/api/{self.repo.repo_uid}/packages/?search=nginx",
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)

    def test_filter_by_architecture(self):
        """?architecture=amd64 returns only amd64 packages."""
        response = self.client.get(
            f"/api/{self.repo.repo_uid}/packages/?architecture=amd64",
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        for pkg in response.data["results"]:
            self.assertEqual(pkg["architecture"], "amd64")

    def test_filter_by_package_name_exact(self):
        """?package_name=curl returns only curl packages."""
        response = self.client.get(
            f"/api/{self.repo.repo_uid}/packages/?package_name=curl",
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["package_name"], "curl")

    def test_combined_filter_and_search(self):
        """?package_name=nginx&architecture=arm64 narrows to one result."""
        response = self.client.get(
            f"/api/{self.repo.repo_uid}/packages/?package_name=nginx&architecture=arm64",
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["architecture"], "arm64")


class RepoFilteringTestCase(APITestCase):
    """Test repository filtering and search."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username="rf_admin", password="password123")
        self.admin_token = Token.objects.get(user=self.admin).key

        self.signing_key = PGPSigningKey.objects.create(
            name="RFKey", email="rf@example.com",
            fingerprint="RF_FP_12345678", public_key_pem="pub", private_key_pem="priv",
        )
        Repository.objects.create(repo_uid="rf-deb", repo_type="deb", signing_key=self.signing_key)
        Repository.objects.create(repo_uid="rf-rpm", repo_type="rpm", signing_key=self.signing_key)
        Repository.objects.create(repo_uid="rf-files", repo_type="files", signing_key=self.signing_key)

    def test_filter_repos_by_type(self):
        """?repo_type=deb returns only deb repos."""
        response = self.client.get(
            "/api/repos/?repo_type=deb",
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(all(r["repo_type"] == "deb" for r in response.data["results"]))

    def test_search_repos_by_uid(self):
        """?search=rpm returns repos with 'rpm' in the UID."""
        response = self.client.get(
            "/api/repos/?search=rpm",
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(all("rpm" in r["repo_uid"] for r in response.data["results"]))


class PatchSupportTestCase(APITestCase):
    """Test PATCH (partial update) support on repos and packages."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username="patch_admin", password="password123")
        self.admin_token = Token.objects.get(user=self.admin).key

        self.signing_key = PGPSigningKey.objects.create(
            name="PatchKey", email="patch@example.com",
            fingerprint="PATCH_FP_12345678", public_key_pem="pub", private_key_pem="priv",
        )
        self.repo = Repository.objects.create(
            repo_uid="patch-repo", repo_type="deb", signing_key=self.signing_key,
        )

    def test_patch_repo_multi_arch(self):
        """PATCH /api/<repo_uid>/ can toggle multi_arch without sending all fields."""
        response = self.client.patch(
            f"/api/{self.repo.repo_uid}/",
            data={"multi_arch": False},
            format="json",
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.repo.refresh_from_db()
        self.assertFalse(self.repo.multi_arch)


class UploadTaskSerializerFieldsTestCase(APITestCase):
    """Test that UploadTaskSerializer includes repo_uid and sha512."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username="field_admin", password="password123")
        self.admin_token = Token.objects.get(user=self.admin).key

        self.signing_key = PGPSigningKey.objects.create(
            name="FieldKey", email="field@example.com",
            fingerprint="FIELD_FP_12345678", public_key_pem="pub", private_key_pem="priv",
        )
        self.repo = Repository.objects.create(
            repo_uid="field-repo", repo_type="files", signing_key=self.signing_key,
        )
        self.task = UploadTask.objects.create(
            repo=self.repo, status="completed", filename="test.deb",
            filesize=100, stored_path="/tmp/fake", sha512="abc123hash",
        )

    def test_upload_status_includes_repo_uid(self):
        """Upload status response includes repo_uid field."""
        response = self.client.get(
            f"/api/upload-status/{self.task.pk}/",
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["repo_uid"], "field-repo")

    def test_upload_status_includes_sha512(self):
        """Upload status response includes sha512 field."""
        response = self.client.get(
            f"/api/upload-status/{self.task.pk}/",
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["sha512"], "abc123hash")
