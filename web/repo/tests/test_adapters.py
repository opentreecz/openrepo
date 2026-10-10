# Copyright 2022 by Open Kilt LLC. All rights reserved.
import gzip
import io
import os
import shutil
import tarfile
import tempfile
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import TestCase

from adapters.file.deb_adapter import DebFileAdapter
from adapters.file.rpm_adapter import RpmFileAdapter
from adapters.repo.deb_repo import DebRepoAdapter
from adapters.repo.fallback_tools import _read_deb_control
from adapters.repo.rpm_repo import RpmRepoAdapter
from repo.models import Build, Package, PGPSigningKey, Repository


def _make_test_deb(path):
    """Create a minimal .deb with control.tar.gz for testing _read_deb_control."""
    ctrl = b"Package: test-pkg\nVersion: 1.0\nArchitecture: all\nDescription: test\n"

    tar_buf = io.BytesIO()
    tar = tarfile.open(fileobj=tar_buf, mode="w")
    info = tarfile.TarInfo(name="./control")
    info.size = len(ctrl)
    tar.addfile(info, io.BytesIO(ctrl))
    tar.close()
    gz_bytes = gzip.compress(tar_buf.getvalue())

    with open(path, "wb") as f:
        f.write(b"!<arch>\n")
        # debian-binary member
        content = b"2.0\n"
        f.write(b"debian-binary   0           0     0     100644  ")
        f.write(str(len(content)).encode().ljust(10))
        f.write(b"\x60\n")
        f.write(content)
        if len(content) % 2:
            f.write(b"\n")
        # control.tar.gz member
        f.write(b"control.tar.gz  0           0     0     100644  ")
        f.write(str(len(gz_bytes)).encode().ljust(10))
        f.write(b"\x60\n")
        f.write(gz_bytes)
        if len(gz_bytes) % 2:
            f.write(b"\n")


class AdapterTestCase(TestCase):
    def setUp(self):
        self.repo_uid = "test-deb-repo"
        self.signing_key = PGPSigningKey.objects.create(
            name="Test Key",
            email="test@example.com",
            fingerprint="8EC5273D32F78A238F54CBEB66633B39A053B24A",
            public_key_pem="dummy public",
            private_key_pem="dummy private",
        )
        self.repo = Repository.objects.create(repo_uid=self.repo_uid, repo_type="deb", signing_key=self.signing_key)

        # Setup paths
        self.test_dir = tempfile.mkdtemp()
        settings.STORAGE_PATH = os.path.join(self.test_dir, "storage")
        settings.REPO_WWW_PATH = os.path.join(self.test_dir, "www")
        settings.KEYRING_PATH = os.path.join(self.test_dir, "keyring")
        settings.DEB_DB_PATH = os.path.join(self.test_dir, "debcache.db")
        settings.RPM_CACHE_DIR = os.path.join(self.test_dir, "rpmcache")

        for p in [settings.STORAGE_PATH, settings.REPO_WWW_PATH, settings.KEYRING_PATH, settings.RPM_CACHE_DIR]:
            if not os.path.exists(p):
                os.makedirs(p)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_deb_file_adapter_metadata(self):
        """Test that DebFileAdapter extracts correct metadata from a .deb file"""
        cur_dir = os.path.dirname(os.path.realpath(__file__))
        deb_path = os.path.join(cur_dir, "unittest_files/hello-world_1.0.0_all.deb")

        adapter = DebFileAdapter(deb_path)
        self.assertEqual(adapter.get_name(), "hello-world")
        self.assertEqual(adapter.get_version(), "1.0.0")
        self.assertEqual(adapter.get_architecture(), "all")

    @patch("subprocess.run")
    @patch("repo.storage.signer.PGPSigner.ensure_key")
    def test_deb_repo_generation(self, mock_ensure_key, mock_run):
        """Test that DebRepoAdapter triggers the correct commands for repo generation"""
        # Mock successful subprocess execution
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Command output"
        mock_run.return_value = mock_proc

        # Add a package to the repo
        Package.objects.create(
            repo=self.repo,
            package_uid="test-pkg-uid",
            filename="hello-world_1.0.0_all.deb",
            package_name="hello-world",
            version="1.0.0",
            architecture="all",
            upload_date="2022-01-01T00:00:00Z",
            checksum_sha512="dummy",
        )

        # Create a dummy file for symlinking
        pkg_file_path = os.path.join(settings.STORAGE_PATH, "test/pkg/uid")
        os.makedirs(os.path.dirname(pkg_file_path), exist_ok=True)
        with open(pkg_file_path, "w") as f:
            f.write("dummy package content")

        adapter = DebRepoAdapter(self.repo)
        # Create a build object as BaseRepoAdapter needs it for logging
        adapter.build = Build.objects.create(repo=self.repo, build_number=1)
        adapter.packages = Package.objects.filter(repo=self.repo)

        repo_path = os.path.join(settings.REPO_WWW_PATH, "test_repo_dir")
        os.makedirs(repo_path, exist_ok=True)

        success = adapter._generate_repo_structure(repo_path)

        self.assertTrue(success)

        # Check if key commands were called (apt-ftparchive, gpg)
        # Commands are now passed as lists (shell=False), so args[0] is a list of strings
        called_commands = [call.args[0] for call in mock_run.call_args_list]
        self.assertTrue(any("apt-ftparchive" in cmd for cmd in called_commands if isinstance(cmd, list)))
        self.assertTrue(any("gpg" in cmd for cmd in called_commands if isinstance(cmd, list)))
        self.assertTrue(any(
            "--local-user" in cmd and "8EC5273D32F78A238F54CBEB66633B39A053B24A" in cmd
            for cmd in called_commands if isinstance(cmd, list)
        ))

    def test_repo_instructions(self):
        """Test that repo instructions are correctly generated"""
        adapter = DebRepoAdapter(self.repo)
        instructions = adapter._get_repo_instructions()
        self.assertIn("apt update", instructions)
        self.assertIn(f"openrepo-{self.repo_uid}.list", instructions)
        self.assertIn("signed-by=/usr/share/keyrings/openrepo-test-deb-repo.gpg", instructions)

    @patch("rpmfile.open")
    def test_rpm_file_adapter_metadata(self, mock_rpm_open):
        """Test that RpmFileAdapter extracts correct metadata from a mocked RPM file"""
        mock_rpm = MagicMock()
        mock_rpm.headers.get.side_effect = lambda x: {
            "name": b"test-pkg",
            "version": b"1.2.3",
            "release": b"1",
            "arch": b"x86_64",
            "buildtime": 1600000000,
            "description": b"Test description",
        }.get(x)

        # Configure the context manager mock
        mock_rpm_open.return_value.__enter__.return_value = mock_rpm

        settings.RPM_VERSION_IGNORE_BUILD_NUM = False
        adapter = RpmFileAdapter("dummy.rpm")

        self.assertEqual(adapter.get_name(), "test-pkg")
        self.assertEqual(adapter.get_version(), "1.2.3.1")
        self.assertEqual(adapter.get_architecture(), "x86_64")

    @patch("subprocess.run")
    @patch("repo.storage.signer.PGPSigner.ensure_key")
    def test_rpm_repo_generation(self, mock_ensure_key, mock_run):
        """Test that RpmRepoAdapter triggers the correct commands (createrepo, gpg)"""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Command output"
        mock_run.return_value = mock_proc

        repo_rpm = Repository.objects.create(repo_uid="test-rpm-repo", repo_type="rpm", signing_key=self.signing_key)

        adapter = RpmRepoAdapter(repo_rpm)
        # Create a build object as BaseRepoAdapter needs it for logging
        adapter.build = Build.objects.create(repo=repo_rpm, build_number=1)
        adapter.packages = []  # No packages for this simple test

        repo_path = os.path.join(settings.REPO_WWW_PATH, "test_rpm_dir")
        os.makedirs(repo_path, exist_ok=True)

        success = adapter._generate_repo_structure(repo_path)

        self.assertTrue(success)
        called_commands = [call.args[0] for call in mock_run.call_args_list]
        self.assertTrue(any("createrepo" in cmd for cmd in called_commands if isinstance(cmd, list)))
        self.assertTrue(
            any("gpg" in cmd and "--detach-sign" in cmd for cmd in called_commands if isinstance(cmd, list))
        )


class FallbackToolsTarfileFilterTestCase(TestCase):
    """Test that _read_deb_control sets tarfile.extraction_filter when available."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.deb_path = os.path.join(self.test_dir, "test.deb")
        _make_test_deb(self.deb_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_read_deb_control_returns_valid_control(self):
        """_read_deb_control successfully reads control data from a .deb"""
        control = _read_deb_control(self.deb_path)
        self.assertIn("Package:", control)
        self.assertIn("test-pkg", control)

    def test_read_deb_control_sets_extraction_filter_when_available(self):
        """When tarfile.data_filter exists (Python 3.12+), extraction_filter is set."""
        sentinel = lambda member, path: member  # noqa: E731
        with patch.object(tarfile, "data_filter", sentinel, create=True):
            original_open = tarfile.open
            captured_tar = []

            def capturing_open(*args, **kwargs):
                tar = original_open(*args, **kwargs)
                captured_tar.append(tar)
                return tar

            with patch("tarfile.open", side_effect=capturing_open):
                _read_deb_control(self.deb_path)

            self.assertTrue(len(captured_tar) > 0)
            self.assertIs(captured_tar[0].extraction_filter, sentinel)

    def test_read_deb_control_works_without_data_filter(self):
        """On Python < 3.12 (no tarfile.data_filter), the function still works."""
        had_attr = hasattr(tarfile, "data_filter")
        if had_attr:
            saved = tarfile.data_filter
            delattr(tarfile, "data_filter")
        try:
            control = _read_deb_control(self.deb_path)
        finally:
            if had_attr:
                tarfile.data_filter = saved

        self.assertIn("Package:", control)
        self.assertIn("test-pkg", control)
