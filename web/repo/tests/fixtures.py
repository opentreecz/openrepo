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

"""Shared test fixtures — eliminates setUp boilerplate across 30+ test files.

Usage::

    from repo.tests.fixtures import make_admin, make_signing_key, TempSettingsMixin

    class MyTestCase(TempSettingsMixin, APITestCase):
        # TempSettingsMixin provides self.test_dir and overrides STORAGE_PATH,
        # REPO_WWW_PATH, KEYRING_PATH automatically.

        def setUp(self):
            super().setUp()
            self.user, self.token, self.auth = make_admin("my-admin")
            self.signing_key = make_signing_key()
            self.repo = Repository.objects.create(
                repo_uid="my-repo", repo_type="deb",
                signing_key=self.signing_key,
            )
"""

import os
import shutil
import tempfile

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token

from repo.models import PGPSigningKey


# ---------------------------------------------------------------------------
# P1 — Admin user + auth token
# ---------------------------------------------------------------------------

def make_admin(username="test-admin", password="password123", email=""):
    """Create a superuser and return ``(user, token_key, auth_header)``.

    The auth header is ready to pass as ``HTTP_AUTHORIZATION`` to the test
    client::

        user, token, auth = make_admin("my-admin")
        self.client.get("/api/repos/", HTTP_AUTHORIZATION=auth)
    """
    User = get_user_model()
    if not email:
        email = f"{username}@test.com"
    user = User.objects.create_superuser(username=username, password=password, email=email)
    token_key = Token.objects.get(user=user).key
    auth_header = f"Token {token_key}"
    return user, token_key, auth_header


# ---------------------------------------------------------------------------
# P2 — PGP signing key
# ---------------------------------------------------------------------------

_SIGNING_KEY_COUNTER = 0


def make_signing_key(
    name="Test Key",
    email="test@example.com",
    fingerprint=None,
    public_key_pem="pub",
    private_key_pem="priv",
    passphrase="",
):
    """Create and return a :class:`~repo.models.PGPSigningKey`.

    If *fingerprint* is not given a unique one is generated automatically so
    that multiple calls within the same test don't collide on the unique
    constraint.
    """
    global _SIGNING_KEY_COUNTER
    if fingerprint is None:
        _SIGNING_KEY_COUNTER += 1
        fingerprint = f"TESTFP{_SIGNING_KEY_COUNTER:034d}"
    return PGPSigningKey.objects.create(
        name=name,
        email=email,
        fingerprint=fingerprint,
        public_key_pem=public_key_pem,
        private_key_pem=private_key_pem,
        passphrase=passphrase,
    )


# ---------------------------------------------------------------------------
# P4 — Temp directory + settings override mixin
# ---------------------------------------------------------------------------

class TempSettingsMixin:
    """Mixin that isolates tests from the host filesystem.

    Creates a fresh ``tempfile.mkdtemp()`` and overrides Django settings that
    point to on-disk paths.  Restores originals and removes the temp tree in
    ``tearDown``.

    Override ``_settings_to_override`` in subclasses to control which settings
    are redirected.  Defaults to the three most common:
    ``STORAGE_PATH``, ``REPO_WWW_PATH``, ``KEYRING_PATH``.

    After ``setUp``, the following attributes are available:

    * ``self.test_dir`` — root temp directory
    * ``self.storage_path`` — ``<test_dir>/storage``
    * ``self.www_path`` — ``<test_dir>/www``
    * ``self.keyring_path`` — ``<test_dir>/keyring``
    """

    #: Override in subclasses to add e.g. ``DEB_DB_PATH``, ``RPM_CACHE_DIR``.
    _extra_settings: dict = {}

    def setUp(self):
        super().setUp()
        self.test_dir = tempfile.mkdtemp()
        self.storage_path = os.path.join(self.test_dir, "storage")
        self.www_path = os.path.join(self.test_dir, "www")
        self.keyring_path = os.path.join(self.test_dir, "keyring")

        self._saved_settings = {}
        defaults = {
            "STORAGE_PATH": self.storage_path,
            "REPO_WWW_PATH": self.www_path,
            "KEYRING_PATH": self.keyring_path,
        }
        defaults.update(self._extra_settings)

        for name, new_value in defaults.items():
            self._saved_settings[name] = getattr(settings, name, None)
            setattr(settings, name, new_value)
            os.makedirs(new_value, exist_ok=True)

    def tearDown(self):
        for name, original in self._saved_settings.items():
            if original is not None:
                setattr(settings, name, original)
        shutil.rmtree(self.test_dir, ignore_errors=True)
        super().tearDown()
