from django.core.management.base import BaseCommand

from repo.models import PGPSigningKey
from repo.storage.keyring import PGPKeyring


class Command(BaseCommand):
    help = "Import all PGP keys from the database into the local GPG keyring"

    def handle(self, *args, **options):
        keyring = PGPKeyring()
        keys = PGPSigningKey.objects.all()
        for key in keys:
            keyring.ensure_key(key)
        self.stdout.write(self.style.SUCCESS(f"Refreshed {keys.count()} PGP key(s) in keyring"))
