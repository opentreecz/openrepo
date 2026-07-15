# Copyright 2022 by Open Kilt LLC. All rights reserved.
# This file is part of the OpenRepo Repository Management Software (OpenRepo)
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

import os
import threading
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from repo.models import Package, PGPSigningKey, Repository


def _run_thread_inline(self):
    """Patch threading.Thread.start to run the target inline (avoids SQLite cross-thread issues)."""
    self.run()


class RepoRestApiTestCase(APITestCase):
    def setUp(self):

        User = get_user_model()
        self.user = User.objects.create_superuser(username="matt", email="matt@test.com", password="4242424242")

        token = Token.objects.get(user=self.user)
        self.api_key = token.key

        self.http_auth = f"Token {self.api_key}"
        self.headers = {"Authorization": f"Token {self.api_key}"}

        settings.STORAGE_PATH = "/tmp/openrepo_test"
        if not os.path.exists(settings.STORAGE_PATH):
            os.makedirs(settings.STORAGE_PATH)

        # Create a dummy signing key as the app currently requires it during validation
        self.signing_key = PGPSigningKey.objects.create(
            name="Test Key",
            email="test@example.com",
            fingerprint="ABCDEF1234567890",
            public_key_pem="dummy public",
            private_key_pem="dummy private",
        )

    def tearDown(self):
        pass

    def test_repo_create_delete(self):
        """Create, list, and delete a repo"""

        REPO_UID = "test-repo"

        response = self.client.post(
            "/api/repos/",
            {
                "repo_uid": REPO_UID,
                "repo_name": "Test repo",
                "architecture": "x86_64",
                "repo_type": "deb",
                "signing_key": self.signing_key.fingerprint,
            },
            HTTP_AUTHORIZATION=self.http_auth,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Repository.objects.count(), 1)
        self.assertEqual(Repository.objects.get().repo_uid, REPO_UID)

        response = self.client.delete(f"/api/{REPO_UID}/", HTTP_AUTHORIZATION=self.http_auth, format="json")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(Repository.objects.count(), 0)

    @patch.object(threading.Thread, "start", _run_thread_inline)
    def test_package_upload_delete(self):

        REPO_UID = "pkgrepo"

        CUR_DIR = os.path.dirname(os.path.realpath(__file__))

        response = self.client.post(
            "/api/repos/",
            {
                "repo_uid": REPO_UID,
                "repo_name": "Test repo",
                "architecture": "x86_64",
                "repo_type": "deb",
                "signing_key": self.signing_key.fingerprint,
            },
            HTTP_AUTHORIZATION=self.http_auth,
            format="json",
        )

        upload_file_path = os.path.join(CUR_DIR, "unittest_files/hello-world_1.0.0_all.deb")
        with open(upload_file_path, "rb") as upload_file_buffer:
            response = self.client.post(
                f"/api/{REPO_UID}/upload/",
                data={"package_file": upload_file_buffer},
                format="multipart",
                HTTP_AUTHORIZATION=self.http_auth,
            )

        # Upload returns 202 Accepted with a task_id; processing runs inline due to mock
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertIn("task_id", response.data)

        task_id = response.data["task_id"]

        # Poll upload status endpoint to confirm processing completed
        status_response = self.client.get(
            f"/api/upload-status/{task_id}/",
            HTTP_AUTHORIZATION=self.http_auth,
        )
        self.assertEqual(status_response.status_code, status.HTTP_200_OK)
        self.assertEqual(status_response.data["status"], "completed")

        package = Package.objects.get()
        disk_path = os.path.join(settings.STORAGE_PATH, package.package_uid.replace("-", "/"))

        self.assertEqual(Package.objects.count(), 1)
        self.assertTrue(os.path.isfile(disk_path))

        # Delete the package and make sure that the file on disk is deleted as well
        response = self.client.delete(
            f"/api/{REPO_UID}/pkg/{package.package_uid}/", HTTP_AUTHORIZATION=self.http_auth, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(Package.objects.count(), 0)
        self.assertTrue(not os.path.isfile(disk_path))
