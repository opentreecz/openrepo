from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Call before starting app server to ensure system is properly configured"

    def handle(self, *args, **options):
        call_command("refresh_keychain")
        self.stdout.write(self.style.SUCCESS("Completed startup checks"))
