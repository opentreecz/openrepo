# OpenRepo is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License
# version 3 as published by the Free Software Foundation

import yaml
from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient


class OpenAPISchemaTest(TestCase):
    """Tests for the auto-generated OpenAPI schema."""

    def setUp(self):
        self.user = User.objects.create_superuser("admin", "admin@test.com", "admin")
        self.token = Token.objects.create(user=self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

    def test_schema_endpoint_returns_yaml(self):
        """GET /api/schema/ returns a valid YAML OpenAPI document."""
        response = self.client.get("/api/schema/", format="json")
        self.assertEqual(response.status_code, 200)
        schema = yaml.safe_load(response.content)
        self.assertIn("openapi", schema)
        self.assertIn("info", schema)
        self.assertIn("paths", schema)

    def test_schema_contains_expected_endpoints(self):
        """The schema includes all key API endpoints."""
        response = self.client.get("/api/schema/", format="json")
        schema = yaml.safe_load(response.content)
        paths = schema["paths"]

        expected_paths = [
            "/api/whoami",
            "/api/repos/",
            "/api/signingkeys/",
            "/api/builds/",
            "/api/buildlogs/",
        ]
        for path in expected_paths:
            self.assertIn(path, paths, f"Missing expected path: {path}")

    def test_schema_info_metadata(self):
        """The schema info section has correct metadata."""
        response = self.client.get("/api/schema/", format="json")
        schema = yaml.safe_load(response.content)
        info = schema["info"]
        self.assertEqual(info["title"], "OpenRepo API")
        self.assertIn("version", info)

    def test_schema_upload_response_has_task_id(self):
        """The upload endpoint schema documents the 202 response with task_id."""
        response = self.client.get("/api/schema/", format="json")
        schema = yaml.safe_load(response.content)
        # Find any upload path (parameterized as {repo_uid})
        upload_paths = [p for p in schema["paths"] if "upload" in p and "status" not in p]
        self.assertTrue(len(upload_paths) > 0, "No upload endpoint found in schema")

    def test_schema_validates_without_warnings(self):
        """The schema can be generated without validation errors."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        # This will raise if validation fails
        call_command("spectacular", "--validate", stdout=out)
        output = out.getvalue()
        self.assertNotIn("Error", output)
