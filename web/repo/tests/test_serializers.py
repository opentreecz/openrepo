# Copyright 2022 by Open Kilt LLC. All rights reserved.
import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from repo.models import Package, PGPSigningKey, Repository


class SerializerValidationTestCase(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username="admin_ser", password="password123")
        self.admin_token = Token.objects.get(user=self.admin).key
        self.signing_key = PGPSigningKey.objects.create(
            name="Test Key",
            email="test@example.com",
            fingerprint="FINGERPRINT12345",
            public_key_pem="dummy public",
            private_key_pem="dummy private",
        )

    def test_repo_uid_with_special_chars_rejected(self):
        """repo_uid with spaces or special chars is rejected"""
        response = self.client.post(
            "/api/repos/",
            {"repo_uid": "bad uid!", "repo_type": "deb", "signing_key": self.signing_key.fingerprint},
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("repo_uid", response.data)

    def test_repo_uid_disallowed_name_api_rejected(self):
        """repo_uid of 'api' is rejected as reserved"""
        response = self.client.post(
            "/api/repos/",
            {"repo_uid": "api", "repo_type": "deb", "signing_key": self.signing_key.fingerprint},
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("repo_uid", response.data)

    def test_repo_uid_disallowed_name_admin_rejected(self):
        """repo_uid of 'admin' is rejected as reserved"""
        response = self.client.post(
            "/api/repos/",
            {"repo_uid": "admin", "repo_type": "deb", "signing_key": self.signing_key.fingerprint},
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_repo_uid_disallowed_name_static_rejected(self):
        """repo_uid of 'static' is rejected as reserved"""
        response = self.client.post(
            "/api/repos/",
            {"repo_uid": "static", "repo_type": "deb", "signing_key": self.signing_key.fingerprint},
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_repo_without_signing_key_rejected(self):
        """Creating a repo without signing_key is rejected"""
        response = self.client.post(
            "/api/repos/",
            {"repo_uid": "valid-repo", "repo_type": "deb", "signing_key": ""},
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_repo_uid_with_dash_and_underscore_accepted(self):
        """repo_uid with dash and underscore is valid"""
        response = self.client.post(
            "/api/repos/",
            {"repo_uid": "my_good-repo", "repo_type": "deb", "signing_key": self.signing_key.fingerprint},
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Repository.objects.filter(repo_uid="my_good-repo").count(), 1)

    def test_repo_uid_numeric_accepted(self):
        """repo_uid with numbers is valid"""
        response = self.client.post(
            "/api/repos/",
            {"repo_uid": "repo123", "repo_type": "rpm", "signing_key": self.signing_key.fingerprint},
            HTTP_AUTHORIZATION=f"Token {self.admin_token}",
            format="json",
        )
        self.assertEqual(response.status_code, 201)


class PromoteToValidationTestCase(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username="admin_promote", password="password123")
        self.admin_token = Token.objects.get(user=self.admin).key
        self.signing_key = PGPSigningKey.objects.create(
            name="Promote Key",
            email="promote@example.com",
            fingerprint="PROMOTE_FP_1234",
            public_key_pem="pub",
            private_key_pem="priv",
        )
        self.auth = f"Token {self.admin_token}"

    def _create_repo(self, repo_uid, promote_to=None):
        data = {"repo_uid": repo_uid, "repo_type": "deb", "signing_key": self.signing_key.fingerprint}
        if promote_to is not None:
            data["promote_to"] = promote_to
        response = self.client.post("/api/repos/", data, HTTP_AUTHORIZATION=self.auth, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["repo_uid"]

    def test_two_repos_cannot_promote_to_the_same_target(self):
        """A repo_uid already used as someone's promote_to target can't be claimed again"""
        target = self._create_repo("promo-target")
        self._create_repo("promo-source-a", promote_to=target)
        self._create_repo("promo-source-b")

        response = self.client.put(
            "/api/promo-source-b/",
            {"repo_uid": "promo-source-b", "repo_type": "deb", "promote_to": target},
            HTTP_AUTHORIZATION=self.auth,
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("promote_to", response.data)

    def test_updating_repo_with_its_own_existing_promote_to_is_not_a_conflict(self):
        """Re-saving a repo that already owns a promote_to target doesn't self-conflict"""
        target = self._create_repo("promo-target-2")
        self._create_repo("promo-source-c", promote_to=target)

        response = self.client.put(
            "/api/promo-source-c/",
            {"repo_uid": "promo-source-c", "repo_type": "deb", "promote_to": target},
            HTTP_AUTHORIZATION=self.auth,
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

    def test_direct_circular_promotion_rejected(self):
        """A -> B, then trying to set B -> A is rejected as circular"""
        self._create_repo("circ-a")
        self._create_repo("circ-b", promote_to="circ-a")

        response = self.client.put(
            "/api/circ-a/",
            {"repo_uid": "circ-a", "repo_type": "deb", "promote_to": "circ-b"},
            HTTP_AUTHORIZATION=self.auth,
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("circular", str(response.data))

    def test_indirect_circular_promotion_rejected(self):
        """A -> B -> C, then trying to set C -> A is rejected as circular"""
        self._create_repo("chain-a")
        self._create_repo("chain-b", promote_to="chain-a")
        self._create_repo("chain-c", promote_to="chain-b")

        response = self.client.put(
            "/api/chain-a/",
            {"repo_uid": "chain-a", "repo_type": "deb", "promote_to": "chain-c"},
            HTTP_AUTHORIZATION=self.auth,
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("circular", str(response.data))


class PackageSerializerTestCase(TestCase):
    def setUp(self):
        self.signing_key = PGPSigningKey.objects.create(
            name="Key",
            email="k@example.com",
            fingerprint="PKG_SER_FP",
            public_key_pem="pub",
            private_key_pem="priv",
        )
        self.repo = Repository.objects.create(repo_uid="pkg-ser-repo", repo_type="deb", signing_key=self.signing_key)

    def test_package_relative_path(self):
        """Package.relative_path replaces dashes with slashes"""
        pkg = Package(
            repo=self.repo,
            package_uid="aa-bbccddee",
            filename="test.deb",
            package_name="test",
            version="1.0",
            architecture="all",
            upload_date=datetime.datetime.now(tz=datetime.timezone.utc),
            checksum_sha512="abc",
        )
        self.assertEqual(pkg.relative_path(), "aa/bbccddee")

    def test_package_str_representation(self):
        """Package can be saved and retrieved"""
        pkg = Package.objects.create(
            repo=self.repo,
            package_uid="zz-testpkg",
            filename="test.deb",
            package_name="testpkg",
            version="1.0",
            architecture="all",
            upload_date=datetime.datetime.now(tz=datetime.timezone.utc),
            checksum_sha512="abc123",
        )
        self.assertEqual(Package.objects.filter(package_uid="zz-testpkg").count(), 1)
        self.assertEqual(pkg.relative_path(), "zz/testpkg")
