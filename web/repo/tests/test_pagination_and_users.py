"""Tests for pagination and UserViewSet CRUD.

Covers:
  E1 — Pagination: ?page=2, ?page_size=N, next/previous links
  E2 — UserViewSet: list, create, update (partial), delete
"""
import datetime

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from repo.models import Package, Repository

User = get_user_model()


class PaginationTestCase(APITestCase):
    """E1: Verify pagination behaviour on the packages endpoint."""

    def setUp(self):
        self.user = User.objects.create_superuser(
            username="pager", email="pager@test.com", password="secret1234"
        )
        token = Token.objects.get(user=self.user)
        self.http_auth = f"Token {token.key}"

        self.repo = Repository.objects.create(repo_uid="page-repo", repo_type="files")

        # Create 15 packages so we can test page boundaries
        for i in range(15):
            Package.objects.create(
                repo=self.repo,
                package_uid=f"uid-{i:03d}",
                filename=f"pkg-{i:03d}-1.0.bin",
                package_name=f"pkg-{i:03d}",
                version="1.0",
                architecture="any",
                upload_date=datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
                + datetime.timedelta(hours=i),
                checksum_sha512="a" * 128,
            )

    def test_default_page_returns_all_when_under_limit(self):
        """With 15 packages and default page_size=100, one page is enough."""
        resp = self.client.get(
            f"/api/{self.repo.repo_uid}/packages/",
            HTTP_AUTHORIZATION=self.http_auth,
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()
        self.assertEqual(len(data["results"]), 15)
        self.assertIsNone(data["next"])

    def test_custom_page_size(self):
        """?page_size=5 returns only 5 results with a next link."""
        resp = self.client.get(
            f"/api/{self.repo.repo_uid}/packages/?page_size=5",
            HTTP_AUTHORIZATION=self.http_auth,
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()
        self.assertEqual(len(data["results"]), 5)
        self.assertIsNotNone(data["next"])

    def test_page_two(self):
        """?page_size=10&page=2 returns the remaining 5 packages."""
        resp = self.client.get(
            f"/api/{self.repo.repo_uid}/packages/?page_size=10&page=2",
            HTTP_AUTHORIZATION=self.http_auth,
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()
        self.assertEqual(len(data["results"]), 5)
        # Second page has no next
        self.assertIsNone(data["next"])
        # But it has a previous
        self.assertIsNotNone(data.get("previous"))

    def test_page_size_capped_at_max(self):
        """?page_size=9999 is silently capped to max_page_size (500)."""
        resp = self.client.get(
            f"/api/{self.repo.repo_uid}/packages/?page_size=9999",
            HTTP_AUTHORIZATION=self.http_auth,
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # Still returns all 15 since 15 < 500
        self.assertEqual(len(resp.json()["results"]), 15)

    def test_invalid_page_returns_404(self):
        """Requesting a page beyond the last page returns 404."""
        resp = self.client.get(
            f"/api/{self.repo.repo_uid}/packages/?page_size=10&page=99",
            HTTP_AUTHORIZATION=self.http_auth,
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class UserViewSetTestCase(APITestCase):
    """E2: CRUD tests for /api/users/ (UserViewSet)."""

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin", email="admin@test.com", password="adminpass"
        )
        token = Token.objects.get(user=self.admin)
        self.http_auth = f"Token {token.key}"

    # ── List ────────────────────────────────────────────────────────────

    def test_list_users(self):
        resp = self.client.get("/api/users/", HTTP_AUTHORIZATION=self.http_auth)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()
        # At least the admin user exists
        results = data.get("results", data)  # handle paginated or unpaginated
        self.assertTrue(len(results) >= 1)

    def test_list_users_unauthenticated_fails(self):
        resp = self.client.get("/api/users/")
        self.assertIn(resp.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    # ── Create ──────────────────────────────────────────────────────────

    def test_create_user(self):
        resp = self.client.post(
            "/api/users/",
            {"username": "newuser", "email": "new@test.com", "password": "testpass123"},
            HTTP_AUTHORIZATION=self.http_auth,
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.filter(username="newuser").exists())

    def test_create_user_duplicate_username_fails(self):
        User.objects.create_user(username="dupe", email="d@test.com", password="pass")
        resp = self.client.post(
            "/api/users/",
            {"username": "dupe", "email": "d2@test.com", "password": "testpass123"},
            HTTP_AUTHORIZATION=self.http_auth,
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    # ── Retrieve ────────────────────────────────────────────────────────

    def test_retrieve_user(self):
        resp = self.client.get(
            f"/api/users/{self.admin.pk}/",
            HTTP_AUTHORIZATION=self.http_auth,
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.json()["username"], "admin")

    # ── Update (PATCH) ──────────────────────────────────────────────────

    def test_partial_update_user(self):
        user = User.objects.create_user(username="patchme", email="p@test.com", password="pass")
        resp = self.client.patch(
            f"/api/users/{user.pk}/",
            {"email": "patched@test.com"},
            HTTP_AUTHORIZATION=self.http_auth,
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        user.refresh_from_db()
        self.assertEqual(user.email, "patched@test.com")

    # ── Delete ──────────────────────────────────────────────────────────

    def test_delete_user(self):
        user = User.objects.create_user(username="deleteme", email="d@test.com", password="pass")
        user_pk = user.pk
        resp = self.client.delete(
            f"/api/users/{user_pk}/",
            HTTP_AUTHORIZATION=self.http_auth,
        )
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(User.objects.filter(pk=user_pk).exists())

    def test_delete_nonexistent_user_returns_404(self):
        resp = self.client.delete(
            "/api/users/99999/",
            HTTP_AUTHORIZATION=self.http_auth,
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
