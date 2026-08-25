"""
Tests for multi-architecture repository handling.

These tests verify that:
1. Multiple packages with same name/version but different architectures can coexist
2. Multi-arch deb repos generate per-architecture binary directories
3. Architecture filtering works in the API
4. Architecture validation warnings are logged for unknown architectures
5. Retention policies apply per-architecture independently
"""
import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from repo.constants import (
    ALL_KNOWN_ARCHITECTURES,
    DEB_ARCHITECTURES,
    RPM_ARCHITECTURES,
    get_known_architectures,
    is_known_architecture,
)
from repo.models import Package, PGPSigningKey, Repository


class ArchitectureConstantsTest(APITestCase):
    """Test the architecture constants and validation utilities."""

    def test_deb_architectures_includes_common_values(self):
        self.assertIn("amd64", DEB_ARCHITECTURES)
        self.assertIn("arm64", DEB_ARCHITECTURES)
        self.assertIn("armhf", DEB_ARCHITECTURES)
        self.assertIn("i386", DEB_ARCHITECTURES)
        self.assertIn("all", DEB_ARCHITECTURES)

    def test_rpm_architectures_includes_common_values(self):
        self.assertIn("x86_64", RPM_ARCHITECTURES)
        self.assertIn("aarch64", RPM_ARCHITECTURES)
        self.assertIn("noarch", RPM_ARCHITECTURES)
        self.assertIn("armv7hl", RPM_ARCHITECTURES)

    def test_all_known_includes_both(self):
        self.assertTrue(DEB_ARCHITECTURES.issubset(ALL_KNOWN_ARCHITECTURES))
        self.assertTrue(RPM_ARCHITECTURES.issubset(ALL_KNOWN_ARCHITECTURES))
        self.assertIn("any", ALL_KNOWN_ARCHITECTURES)
        self.assertIn("src", ALL_KNOWN_ARCHITECTURES)

    def test_get_known_architectures_by_repo_type(self):
        self.assertEqual(get_known_architectures("deb"), DEB_ARCHITECTURES)
        self.assertEqual(get_known_architectures("rpm"), RPM_ARCHITECTURES)
        self.assertEqual(get_known_architectures("files"), ALL_KNOWN_ARCHITECTURES)

    def test_is_known_architecture(self):
        self.assertTrue(is_known_architecture("amd64", "deb"))
        self.assertTrue(is_known_architecture("arm64", "deb"))
        self.assertTrue(is_known_architecture("x86_64", "rpm"))
        self.assertTrue(is_known_architecture("noarch", "rpm"))
        self.assertFalse(is_known_architecture("x86_64", "deb"))
        self.assertFalse(is_known_architecture("amd64", "rpm"))
        self.assertFalse(is_known_architecture("unknown_arch", "deb"))
        self.assertFalse(is_known_architecture("unknown_arch", "rpm"))


class MultiArchRepoCreationTest(APITestCase):
    """Test creating repos with multi_arch settings."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username="arch-admin", password="p")
        self.token = Token.objects.get(user=self.admin).key
        self.auth = f"Token {self.token}"
        self.signing_key = PGPSigningKey.objects.create(
            name="Test Key",
            email="test@test.com",
            fingerprint="A" * 40,
            public_key_pem="pub",
            private_key_pem="priv",
        )

    def test_create_deb_repo_defaults_multi_arch_true(self):
        """New deb repos should default to multi_arch=True when not specified."""
        response = self.client.post(
            "/api/repos/",
            {
                "repo_uid": "test-deb-default",
                "repo_type": "deb",
                "signing_key": "A" * 40,
            },
            HTTP_AUTHORIZATION=self.auth,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        repo = Repository.objects.get(repo_uid="test-deb-default")
        self.assertTrue(repo.multi_arch)

    def test_create_deb_repo_explicit_multi_arch_false(self):
        """Can explicitly create a deb repo with multi_arch=False."""
        response = self.client.post(
            "/api/repos/",
            {
                "repo_uid": "test-deb-legacy",
                "repo_type": "deb",
                "signing_key": "A" * 40,
                "multi_arch": False,
            },
            HTTP_AUTHORIZATION=self.auth,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        repo = Repository.objects.get(repo_uid="test-deb-legacy")
        self.assertFalse(repo.multi_arch)

    def test_create_rpm_repo_defaults_multi_arch_true(self):
        """New RPM repos should default to multi_arch=True."""
        response = self.client.post(
            "/api/repos/",
            {
                "repo_uid": "test-rpm",
                "repo_type": "rpm",
                "signing_key": "A" * 40,
            },
            HTTP_AUTHORIZATION=self.auth,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        repo = Repository.objects.get(repo_uid="test-rpm")
        self.assertTrue(repo.multi_arch)

    def test_create_rpm_repo_explicit_multi_arch_false(self):
        """Can explicitly create an RPM repo with multi_arch=False."""
        response = self.client.post(
            "/api/repos/",
            {
                "repo_uid": "test-rpm-legacy",
                "repo_type": "rpm",
                "signing_key": "A" * 40,
                "multi_arch": False,
            },
            HTTP_AUTHORIZATION=self.auth,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        repo = Repository.objects.get(repo_uid="test-rpm-legacy")
        self.assertFalse(repo.multi_arch)


class MultiArchPackageCoexistenceTest(APITestCase):
    """Test that packages with same name/version but different architectures can coexist."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username="coexist-admin", password="p")
        self.token = Token.objects.get(user=self.admin).key
        self.auth = f"Token {self.token}"
        self.signing_key = PGPSigningKey.objects.create(
            name="Test Key",
            email="test@test.com",
            fingerprint="B" * 40,
            public_key_pem="pub",
            private_key_pem="priv",
        )
        self.repo = Repository.objects.create(
            repo_uid="multi-arch-repo",
            repo_type="deb",
            signing_key=self.signing_key,
            multi_arch=True,
        )

    def test_same_package_different_architectures(self):
        """Same package_name + version with different architectures should coexist."""
        now = datetime.now(tz=timezone.utc)

        # Create amd64 version
        Package.objects.create(
            package_uid="aa-pkg-amd64",
            repo=self.repo,
            filename="myapp_1.0_amd64.deb",
            package_name="myapp",
            architecture="amd64",
            version="1.0",
            upload_date=now,
            checksum_sha512="aaa",
        )

        # Create arm64 version
        Package.objects.create(
            package_uid="aa-pkg-arm64",
            repo=self.repo,
            filename="myapp_1.0_arm64.deb",
            package_name="myapp",
            architecture="arm64",
            version="1.0",
            upload_date=now,
            checksum_sha512="bbb",
        )

        # Create architecture-independent version
        Package.objects.create(
            package_uid="aa-pkg-all",
            repo=self.repo,
            filename="myapp-doc_1.0_all.deb",
            package_name="myapp-doc",
            architecture="all",
            version="1.0",
            upload_date=now,
            checksum_sha512="ccc",
        )

        # All three should exist
        self.assertEqual(Package.objects.filter(repo=self.repo).count(), 3)
        self.assertEqual(
            Package.objects.filter(repo=self.repo, package_name="myapp").count(), 2
        )

    def test_duplicate_package_same_arch_rejected(self):
        """Same package_name + version + architecture should be rejected."""
        now = datetime.now(tz=timezone.utc)

        Package.objects.create(
            package_uid="aa-dup1",
            repo=self.repo,
            filename="myapp_1.0_amd64.deb",
            package_name="myapp",
            architecture="amd64",
            version="1.0",
            upload_date=now,
            checksum_sha512="xxx",
        )

        from django.db import IntegrityError

        with self.assertRaises(IntegrityError):
            Package.objects.create(
                package_uid="aa-dup2",
                repo=self.repo,
                filename="myapp_1.0_amd64-v2.deb",
                package_name="myapp",
                architecture="amd64",
                version="1.0",
                upload_date=now,
                checksum_sha512="yyy",
            )


class ArchitectureFilterAPITest(APITestCase):
    """Test the architecture query parameter filter in the packages API."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username="filter-admin", password="p")
        self.token = Token.objects.get(user=self.admin).key
        self.auth = f"Token {self.token}"
        self.signing_key = PGPSigningKey.objects.create(
            name="Test Key",
            email="test@test.com",
            fingerprint="C" * 40,
            public_key_pem="pub",
            private_key_pem="priv",
        )
        self.repo = Repository.objects.create(
            repo_uid="filter-repo",
            repo_type="deb",
            signing_key=self.signing_key,
            multi_arch=True,
        )
        now = datetime.now(tz=timezone.utc)

        Package.objects.create(
            package_uid="ff-amd64",
            repo=self.repo,
            filename="pkg_1.0_amd64.deb",
            package_name="pkg",
            architecture="amd64",
            version="1.0",
            upload_date=now,
            checksum_sha512="a1",
        )
        Package.objects.create(
            package_uid="ff-arm64",
            repo=self.repo,
            filename="pkg_1.0_arm64.deb",
            package_name="pkg",
            architecture="arm64",
            version="1.0",
            upload_date=now,
            checksum_sha512="a2",
        )
        Package.objects.create(
            package_uid="ff-all",
            repo=self.repo,
            filename="pkg-doc_1.0_all.deb",
            package_name="pkg-doc",
            architecture="all",
            version="1.0",
            upload_date=now,
            checksum_sha512="a3",
        )

    def test_filter_by_architecture_amd64(self):
        response = self.client.get(
            "/api/filter-repo/packages/?architecture=amd64",
            HTTP_AUTHORIZATION=self.auth,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["architecture"], "amd64")

    def test_filter_by_architecture_arm64(self):
        response = self.client.get(
            "/api/filter-repo/packages/?architecture=arm64",
            HTTP_AUTHORIZATION=self.auth,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["architecture"], "arm64")

    def test_filter_by_architecture_all(self):
        response = self.client.get(
            "/api/filter-repo/packages/?architecture=all",
            HTTP_AUTHORIZATION=self.auth,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["package_name"], "pkg-doc")

    def test_no_filter_returns_all(self):
        response = self.client.get(
            "/api/filter-repo/packages/",
            HTTP_AUTHORIZATION=self.auth,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 3)

    def test_filter_nonexistent_architecture(self):
        response = self.client.get(
            "/api/filter-repo/packages/?architecture=sparc",
            HTTP_AUTHORIZATION=self.auth,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)


class ArchitectureValidationWarningTest(APITestCase):
    """Test that unknown architectures produce warning logs during upload."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username="warn-admin", password="p")
        self.token = Token.objects.get(user=self.admin).key
        self.auth = f"Token {self.token}"
        self.signing_key = PGPSigningKey.objects.create(
            name="Test Key",
            email="test@test.com",
            fingerprint="D" * 40,
            public_key_pem="pub",
            private_key_pem="priv",
        )
        self.repo = Repository.objects.create(
            repo_uid="warn-repo",
            repo_type="deb",
            signing_key=self.signing_key,
            multi_arch=True,
        )

    @patch("threading.Thread.start", lambda self: self.run())
    def test_unknown_architecture_logs_warning(self):
        """Uploading a package with unknown architecture should log a warning."""
        # We'll mock the adapter to return an unusual architecture
        mock_adapter_class = patch("repo.api.upload_processor.create_adapter")
        mock_create = mock_adapter_class.start()
        mock_adapter = mock_create.return_value
        mock_adapter.get_name.return_value = "test-pkg"
        mock_adapter.get_version.return_value = "1.0"
        mock_adapter.get_architecture.return_value = "sparc64"
        mock_adapter.get_builddate.return_value = None

        content = b"fake package content"
        upload_file = SimpleUploadedFile(
            "test-pkg_1.0_sparc64.deb", content, content_type="application/octet-stream"
        )

        with self.assertLogs("openrepo_web", level="WARNING") as log_cm:
            response = self.client.post(
                "/api/warn-repo/upload/",
                {"package_file": upload_file},
                HTTP_AUTHORIZATION=self.auth,
            )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

        # Check warning was logged
        warning_messages = [m for m in log_cm.output if "unknown architecture" in m]
        self.assertTrue(len(warning_messages) > 0)
        self.assertIn("sparc64", warning_messages[0])

        mock_adapter_class.stop()


class MultiArchRetentionTest(APITestCase):
    """Test that retention policies apply per-architecture independently."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username="ret-admin", password="p")
        self.token = Token.objects.get(user=self.admin).key
        self.auth = f"Token {self.token}"
        self.signing_key = PGPSigningKey.objects.create(
            name="Test Key",
            email="test@test.com",
            fingerprint="E" * 40,
            public_key_pem="pub",
            private_key_pem="priv",
        )

        self.storage = tempfile.mkdtemp()
        self._old_storage = settings.STORAGE_PATH
        settings.STORAGE_PATH = self.storage

        self.repo = Repository.objects.create(
            repo_uid="ret-repo",
            repo_type="deb",
            signing_key=self.signing_key,
            multi_arch=True,
            retention_policy="keep_latest_n",
            retention_keep_count=1,
        )

    def tearDown(self):
        settings.STORAGE_PATH = self._old_storage
        shutil.rmtree(self.storage, ignore_errors=True)

    def test_retention_keeps_latest_per_architecture(self):
        """Retention 'keep latest 1' should keep 1 per (name, arch) group."""
        from repo.api.retention import apply_retention_policy

        now = datetime.now(tz=timezone.utc)
        older = now - timedelta(days=5)

        # amd64 - version 1.0 (older)
        pkg1 = Package.objects.create(
            package_uid="rr-amd64-v1",
            repo=self.repo,
            filename="app_1.0_amd64.deb",
            package_name="app",
            architecture="amd64",
            version="1.0",
            upload_date=older,
            checksum_sha512="r1",
        )
        # Create dummy file
        fp1 = os.path.join(self.storage, pkg1.relative_path())
        os.makedirs(os.path.dirname(fp1), exist_ok=True)
        with open(fp1, "w") as f:
            f.write("x")

        # amd64 - version 2.0 (newer)
        pkg2 = Package.objects.create(
            package_uid="rr-amd64-v2",
            repo=self.repo,
            filename="app_2.0_amd64.deb",
            package_name="app",
            architecture="amd64",
            version="2.0",
            upload_date=now,
            checksum_sha512="r2",
        )
        fp2 = os.path.join(self.storage, pkg2.relative_path())
        os.makedirs(os.path.dirname(fp2), exist_ok=True)
        with open(fp2, "w") as f:
            f.write("x")

        # arm64 - version 1.0 (only version for this arch)
        pkg3 = Package.objects.create(
            package_uid="rr-arm64-v1",
            repo=self.repo,
            filename="app_1.0_arm64.deb",
            package_name="app",
            architecture="arm64",
            version="1.0",
            upload_date=now,
            checksum_sha512="r3",
        )
        fp3 = os.path.join(self.storage, pkg3.relative_path())
        os.makedirs(os.path.dirname(fp3), exist_ok=True)
        with open(fp3, "w") as f:
            f.write("x")

        # Apply retention for amd64
        apply_retention_policy(self.repo, "app", "amd64")

        # amd64 v1.0 should be deleted, v2.0 kept
        self.assertFalse(Package.objects.filter(pk=pkg1.pk).exists())
        self.assertTrue(Package.objects.filter(pk=pkg2.pk).exists())

        # arm64 should be unaffected
        self.assertTrue(Package.objects.filter(pk=pkg3.pk).exists())

        # Apply retention for arm64
        apply_retention_policy(self.repo, "app", "arm64")

        # arm64 v1.0 should still be kept (it's the only one)
        self.assertTrue(Package.objects.filter(pk=pkg3.pk).exists())


class RpmMultiArchRepoTest(APITestCase):
    """Test RPM multi-architecture repository generation."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username="rpm-arch-admin", password="p")
        self.token = Token.objects.get(user=self.admin).key
        self.auth = f"Token {self.token}"
        self.signing_key = PGPSigningKey.objects.create(
            name="Test Key",
            email="test@test.com",
            fingerprint="F" * 40,
            public_key_pem="pub",
            private_key_pem="priv",
        )

    def test_rpm_multi_arch_instructions_contain_basearch(self):
        """RPM multi_arch repo instructions should use $basearch in baseurl."""
        repo = Repository.objects.create(
            repo_uid="rpm-multi",
            repo_type="rpm",
            signing_key=self.signing_key,
            multi_arch=True,
        )
        from adapters.repo import get_repo_adapter
        adapter = get_repo_adapter(repo)
        instructions = adapter._get_repo_instructions()
        self.assertIn("$basearch", instructions)

    def test_rpm_legacy_instructions_no_basearch(self):
        """RPM legacy mode instructions should NOT use $basearch."""
        repo = Repository.objects.create(
            repo_uid="rpm-legacy",
            repo_type="rpm",
            signing_key=self.signing_key,
            multi_arch=False,
        )
        from adapters.repo import get_repo_adapter
        adapter = get_repo_adapter(repo)
        instructions = adapter._get_repo_instructions()
        self.assertNotIn("$basearch", instructions)

    def test_rpm_get_architectures_multi_arch(self):
        """_get_architectures() should return distinct arches (excl noarch) when multi_arch=True."""
        repo = Repository.objects.create(
            repo_uid="rpm-arches",
            repo_type="rpm",
            signing_key=self.signing_key,
            multi_arch=True,
        )
        now = datetime.now(tz=timezone.utc)
        Package.objects.create(
            package_uid="rr-x86",
            repo=repo,
            filename="app-1.0-1.x86_64.rpm",
            package_name="app",
            architecture="x86_64",
            version="1.0",
            upload_date=now,
            checksum_sha512="x1",
        )
        Package.objects.create(
            package_uid="rr-aarch",
            repo=repo,
            filename="app-1.0-1.aarch64.rpm",
            package_name="app",
            architecture="aarch64",
            version="1.0",
            upload_date=now,
            checksum_sha512="x2",
        )
        Package.objects.create(
            package_uid="rr-noarch",
            repo=repo,
            filename="common-1.0-1.noarch.rpm",
            package_name="common",
            architecture="noarch",
            version="1.0",
            upload_date=now,
            checksum_sha512="x3",
        )

        from adapters.repo import get_repo_adapter
        adapter = get_repo_adapter(repo)
        arches = adapter._get_architectures()
        self.assertEqual(arches, ["aarch64", "x86_64"])
        self.assertNotIn("noarch", arches)

    def test_rpm_get_architectures_legacy_returns_none(self):
        """_get_architectures() should return None when multi_arch=False."""
        repo = Repository.objects.create(
            repo_uid="rpm-legacy-arch",
            repo_type="rpm",
            signing_key=self.signing_key,
            multi_arch=False,
        )
        from adapters.repo import get_repo_adapter
        adapter = get_repo_adapter(repo)
        arches = adapter._get_architectures()
        self.assertIsNone(arches)

    def test_rpm_get_architectures_empty_repo_defaults(self):
        """Empty multi_arch RPM repo should fallback to [x86_64]."""
        repo = Repository.objects.create(
            repo_uid="rpm-empty-arch",
            repo_type="rpm",
            signing_key=self.signing_key,
            multi_arch=True,
        )
        from adapters.repo import get_repo_adapter
        adapter = get_repo_adapter(repo)
        arches = adapter._get_architectures()
        self.assertEqual(arches, ["x86_64"])
