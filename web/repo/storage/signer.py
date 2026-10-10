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

"""GPG signing operations for the repo build pipeline.

``PGPSigner`` is the object passed as ``signer`` to repo adapters and to the
``refresh_keychain`` management command.  It is responsible for two things:

1. Ensuring a key is present on the system GPG keychain (``ensure_key``).
2. Producing a detached ASCII-armoured signature for a file (``detach_sign_file``).

Key *lifecycle* (generate, delete) lives in :mod:`repo.storage.keyring`.
"""

from .keyring import _init_gpg


class PGPSigner:
    """Handles GPG keychain operations and file signing for the build pipeline.

    Callers: ``adapters.repo.orchestrator`` (passed to repo adapters as
    ``signer``), ``management.commands.refresh_keychain``.
    """

    def __init__(self):
        self.gpg = _init_gpg()

    def ensure_key(self, pgp_key) -> None:
        """Ensure *pgp_key* is imported and trusted on the system GPG keychain.

        Required before any subprocess ``gpg`` invocation can use the key.
        If the key is already present the method returns without importing.

        :param pgp_key: A :class:`~repo.models.PGPSigningKey` instance or any
            object with ``fingerprint`` and ``private_key_pem`` attributes.
        """
        public_keys = self.gpg.list_keys(False)
        already_present = any(
            k["fingerprint"] == pgp_key.fingerprint for k in public_keys
        )
        if not already_present:
            self.gpg.import_keys(pgp_key.private_key_pem)
            self.gpg.trust_keys(pgp_key.fingerprint, "TRUST_ULTIMATE")

    def detach_sign_file(
        self,
        pgp_key,
        output_file: str,
        input_file: str,
        clear_sign: bool = False,
    ) -> None:
        """Write a detached GPG signature for *input_file* to *output_file*.

        :param pgp_key: Key to sign with (needs ``fingerprint`` attribute).
        :param output_file: Destination path for the ``.asc`` signature file.
        :param input_file: Path of the file to sign.
        :param clear_sign: If ``True`` produce a clear-text signature instead
            of a binary-detached one.
        """
        self.gpg.sign_file(
            input_file,
            detach=True,
            keyid=pgp_key.fingerprint,
            clearsign=clear_sign,
            binary=False,
            output=output_file,
            extra_args=["-a"],
        )
