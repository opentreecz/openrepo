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
from django.core.management.base import BaseCommand

from repo.models import PGPSigningKey


class Command(BaseCommand):
    help = "Import a PGP private key from a file into the OpenRepo keychain and database"

    def add_arguments(self, parser):
        parser.add_argument("private_key_path", type=str, help="Path to GPG private key stored in PEM format")
        parser.add_argument("--passphrase", type=str, default=None, help="Passphrase for the private key, if any")

    def handle(self, *args, **options):

        if not os.path.isfile(options["private_key_path"]):
            self.stdout.write(f"Cannot find file {options['private_key_path']}")
            return

        gpg = gnupg.GPG()
        gpg.encoding = "utf-8"

        passphrase = options.get("passphrase")

        with open(options["private_key_path"], "r") as pgp_f:
            private_key_content = pgp_f.read()

        import_result = gpg.import_keys(private_key_content, passphrase=passphrase)
        if not import_result.count:
            self.stdout.write(self.style.ERROR("Failed to import key — check the file and passphrase"))
            return

        private_key = gpg.scan_keys(options["private_key_path"])
        keyinfo = private_key[0]
        fingerprint = keyinfo["fingerprint"]
        parts = keyinfo["uids"][0].split("<")
        name = parts[0].strip()
        email = parts[1].strip(">").strip()

        # Extract the public key
        public_key = gpg.export_keys(fingerprint, False)

        new_key = PGPSigningKey()
        new_key.private_key_pem = private_key_content
        new_key.public_key_pem = public_key
        new_key.fingerprint = fingerprint
        new_key.name = name
        new_key.email = email
        new_key.passphrase = passphrase or ""
        new_key.save()
        self.stdout.write(self.style.SUCCESS("Successfully imported key"))
