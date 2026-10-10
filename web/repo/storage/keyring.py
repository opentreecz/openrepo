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

import gnupg
from django.conf import settings

from repo.models import PGPSigningKey


def _init_gpg() -> gnupg.GPG:
    """Create and return a configured gnupg.GPG instance.

    Creates KEYRING_PATH if it does not exist, then handles the gnupg
    backport quirk where the ``gnupghome`` kwarg may raise ``TypeError``
    on older versions (falls back to ``homedir``).
    """
    if not os.path.isdir(settings.KEYRING_PATH):
        os.makedirs(settings.KEYRING_PATH)

    # Weird backport behavior with arguments
    # https://stackoverflow.com/questions/35028852/how-to-set-the-gnupg-home-directory-within-the-gnupg-python-binding
    try:
        gpg = gnupg.GPG(gnupghome=settings.KEYRING_PATH)
    except TypeError:
        gpg = gnupg.GPG(homedir=settings.KEYRING_PATH)

    gpg.encoding = "utf-8"
    return gpg


class PGPKeyManager:
    """Manages PGP key lifecycle: generate, delete.

    Callers: ``PGPKeysViewSet`` (REST API).
    Not responsible for signing or ensuring keys are on the keyring —
    see ``PGPSigner`` in ``storage/signer.py`` for those operations.
    """

    def __init__(self):
        self.gpg = _init_gpg()

    def generate_key(self, full_name: str, email: str) -> PGPSigningKey:
        """Generate a new RSA-4096 key pair and persist it to the database.

        :param full_name: Full name of the key owner.
        :param email: E-mail address of the key owner.
        :returns: The newly created :class:`~repo.models.PGPSigningKey` instance.
        """
        input_data = self.gpg.gen_key_input(
            key_type="RSA",
            key_length=4096,
            expire_date="50y",
            name_real=full_name,
            name_email=email,
            no_protection=True,
        )
        key = self.gpg.gen_key(input_data)

        fingerprint = key.fingerprint
        ascii_armored_public_keys = self.gpg.export_keys([fingerprint], secret=False)
        ascii_armored_private_keys = self.gpg.export_keys([fingerprint], secret=True, passphrase="")

        new_key = PGPSigningKey()
        new_key.name = full_name
        new_key.email = email
        new_key.public_key_pem = ascii_armored_public_keys
        new_key.private_key_pem = ascii_armored_private_keys
        new_key.fingerprint = fingerprint
        new_key.save()

        return new_key

    def delete(self, fingerprint: str, passphrase: str = "") -> None:
        """Remove a key pair from the GPG keyring.

        :param fingerprint: Full key fingerprint.
        :param passphrase: Passphrase protecting the private key (if any).
        """
        self.gpg.delete_keys(fingerprint, secret=True, passphrase=passphrase)
        self.gpg.delete_keys(fingerprint, secret=False)


