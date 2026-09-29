"""Tests for the health check endpoint (GET /api/health/)."""
from rest_framework import status
from rest_framework.test import APITestCase


class HealthCheckTestCase(APITestCase):
    """F1: Health check endpoint tests."""

    def test_health_returns_200(self):
        resp = self.client.get("/api/health/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_health_no_auth_required(self):
        """The health endpoint must be accessible without authentication."""
        resp = self.client.get("/api/health/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_health_response_fields(self):
        resp = self.client.get("/api/health/")
        data = resp.json()
        self.assertIn("status", data)
        self.assertIn("database", data)
        self.assertIn("version", data)
        self.assertIn("repos", data)
        self.assertIn("packages", data)

    def test_health_database_ok(self):
        resp = self.client.get("/api/health/")
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["database"], "ok")

    def test_health_version_is_string(self):
        resp = self.client.get("/api/health/")
        data = resp.json()
        self.assertIsInstance(data["version"], str)
        self.assertNotEqual(data["version"], "unknown")

    def test_health_counts_are_integers(self):
        resp = self.client.get("/api/health/")
        data = resp.json()
        self.assertIsInstance(data["repos"], int)
        self.assertIsInstance(data["packages"], int)
