import os
import shutil
import tempfile

from django.conf import settings
from django.test import TestCase

from adapters.repo.generic_repo import GenericRepoAdapter, _file_md5, _html_page, _human_size
from repo.models import Build, Package, Repository


class GenericRepoHelperTests(TestCase):
    """Unit tests for standalone helper functions."""

    def test_human_size_bytes(self):
        self.assertEqual(_human_size(0), "0 B")
        self.assertEqual(_human_size(512), "512 B")

    def test_human_size_kilobytes(self):
        self.assertIn("KB", _human_size(2048))

    def test_human_size_megabytes(self):
        self.assertIn("MB", _human_size(5 * 1024 * 1024))

    def test_html_page_renders_repo_uid(self):
        page = _html_page("my-repo", [])
        self.assertIn("my-repo", page)
        self.assertIn("0 package(s)", page)

    def test_html_page_with_rows(self):
        rows = ['<tr><td>pkg-1.0.0.bin</td><td>pkg</td><td>1.0.0</td>'
                '<td>any</td><td>1.0 KB</td><td>2024-01-01</td><td class="sha">abc</td></tr>']
        page = _html_page("r", rows)
        self.assertIn("1 package(s)", page)
        self.assertIn("pkg-1.0.0.bin", page)

    def test_file_md5(self):
        d = tempfile.mkdtemp()
        try:
            path = os.path.join(d, "testfile")
            with open(path, "wb") as f:
                f.write(b"hello world")
            digest = _file_md5(path)
            self.assertEqual(len(digest), 32)
            self.assertEqual(digest, "5eb63bbbe01eeed093cb22bb8f5acdc3")
        finally:
            shutil.rmtree(d)


class GenericRepoAdapterTests(TestCase):
    """Integration tests for GenericRepoAdapter._generate_repo_structure."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.orig_storage = getattr(settings, "STORAGE_PATH", None)
        self.orig_www = getattr(settings, "REPO_WWW_PATH", None)
        self.orig_keyring = getattr(settings, "KEYRING_PATH", None)

        settings.STORAGE_PATH = os.path.join(self.test_dir, "storage")
        settings.REPO_WWW_PATH = os.path.join(self.test_dir, "www")
        settings.KEYRING_PATH = os.path.join(self.test_dir, "keyring")

        for p in [settings.STORAGE_PATH, settings.REPO_WWW_PATH, settings.KEYRING_PATH]:
            os.makedirs(p, exist_ok=True)

        self.repo = Repository.objects.create(repo_uid="generic-test", repo_type="files")

    def tearDown(self):
        shutil.rmtree(self.test_dir)
        if self.orig_storage is not None:
            settings.STORAGE_PATH = self.orig_storage
        if self.orig_www is not None:
            settings.REPO_WWW_PATH = self.orig_www
        if self.orig_keyring is not None:
            settings.KEYRING_PATH = self.orig_keyring

    def _create_package(self, name="tool", version="1.0.0", arch="any", content=b"binary data"):
        """Create a Package record and the corresponding file on disk."""
        uid = f"aa-{name}-{version}"
        pkg = Package.objects.create(
            repo=self.repo,
            package_uid=uid,
            filename=f"{name}-{version}.bin",
            package_name=name,
            version=version,
            architecture=arch,
            upload_date="2024-06-15T12:00:00Z",
            checksum_sha512="abcdef1234567890" * 4,
        )
        # Write the file at the storage path so symlinking succeeds
        storage_path = os.path.join(settings.STORAGE_PATH, pkg.relative_path())
        os.makedirs(os.path.dirname(storage_path), exist_ok=True)
        with open(storage_path, "wb") as f:
            f.write(content)
        return pkg

    def test_empty_repo_generates_index(self):
        """An empty generic repo still generates index.html."""
        adapter = GenericRepoAdapter(self.repo)
        adapter.build = Build.objects.create(
            repo=self.repo, build_number=1, completion_status=Build.STATUS_RUNNING
        )

        repo_path = os.path.join(self.test_dir, "output")
        os.makedirs(repo_path)
        result = adapter._generate_repo_structure(repo_path)

        self.assertTrue(result)
        self.assertTrue(os.path.isfile(os.path.join(repo_path, "index.html")))

    def test_generates_md5_and_index(self):
        """With packages, the adapter generates .md5 files and a populated index."""
        self._create_package("tool", "1.0.0", content=b"tool v1")
        self._create_package("tool", "2.0.0", content=b"tool v2")

        adapter = GenericRepoAdapter(self.repo)
        adapter.build = Build.objects.create(
            repo=self.repo, build_number=1, completion_status=Build.STATUS_RUNNING
        )
        adapter.packages = Package.objects.filter(repo=self.repo)

        repo_path = os.path.join(self.test_dir, "output")
        os.makedirs(repo_path)
        result = adapter._generate_repo_structure(repo_path)

        self.assertTrue(result)

        # Check symlinks were created
        self.assertTrue(os.path.exists(os.path.join(repo_path, "tool_1.0.0_any.bin")))
        self.assertTrue(os.path.exists(os.path.join(repo_path, "tool_2.0.0_any.bin")))

        # Check MD5 files
        md5_path = os.path.join(repo_path, "tool_1.0.0_any.bin.md5")
        self.assertTrue(os.path.isfile(md5_path))
        with open(md5_path) as f:
            content = f.read()
        self.assertIn("tool_1.0.0_any.bin", content)
        # MD5 hex digest is 32 chars
        self.assertEqual(len(content.split()[0]), 32)

        # Check index.html
        index_path = os.path.join(repo_path, "index.html")
        self.assertTrue(os.path.isfile(index_path))
        with open(index_path) as f:
            html_content = f.read()
        self.assertIn("generic-test", html_content)
        self.assertIn("tool_1.0.0_any.bin", html_content)
        self.assertIn("tool_2.0.0_any.bin", html_content)
        self.assertIn("2 package(s)", html_content)

    def test_no_pgp_signing_without_key(self):
        """Without a signing key, no .asc or public.gpg files are created."""
        self._create_package()

        adapter = GenericRepoAdapter(self.repo)
        adapter.build = Build.objects.create(
            repo=self.repo, build_number=1, completion_status=Build.STATUS_RUNNING
        )
        adapter.packages = Package.objects.filter(repo=self.repo)

        repo_path = os.path.join(self.test_dir, "output")
        os.makedirs(repo_path)
        adapter._generate_repo_structure(repo_path)

        self.assertFalse(os.path.exists(os.path.join(repo_path, "index.html.asc")))
        self.assertFalse(os.path.exists(os.path.join(repo_path, "public.gpg")))

    def test_md5_not_generated_for_metadata_files(self):
        """MD5 files should not be generated for index.html or public.gpg."""
        self._create_package()

        adapter = GenericRepoAdapter(self.repo)
        adapter.build = Build.objects.create(
            repo=self.repo, build_number=1, completion_status=Build.STATUS_RUNNING
        )
        adapter.packages = Package.objects.filter(repo=self.repo)

        repo_path = os.path.join(self.test_dir, "output")
        os.makedirs(repo_path)
        adapter._generate_repo_structure(repo_path)

        self.assertFalse(os.path.exists(os.path.join(repo_path, "index.html.md5")))
