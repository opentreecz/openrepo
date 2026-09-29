# Data migration to encrypt existing plaintext PGP private keys and passphrases.

from django.db import migrations


def encrypt_existing_keys(apps, schema_editor):
    """Encrypt any plaintext private_key_pem and passphrase values."""
    # Import here so the migration can run even if cryptography is not installed
    # on the machine generating migrations (the forward function only runs
    # when actually applied).
    try:
        from repo.storage.encryption import encrypt_value, _ENCRYPTED_PREFIX
    except ImportError:
        # cryptography not installed — skip (values stay plaintext)
        return

    PGPSigningKey = apps.get_model("repo", "PGPSigningKey")
    for key in PGPSigningKey.objects.all():
        changed = False
        if key.private_key_pem and not key.private_key_pem.startswith(_ENCRYPTED_PREFIX):
            key.private_key_pem = encrypt_value(key.private_key_pem)
            changed = True
        if key.passphrase and not key.passphrase.startswith(_ENCRYPTED_PREFIX):
            key.passphrase = encrypt_value(key.passphrase)
            changed = True
        if changed:
            key.save(update_fields=["private_key_pem", "passphrase"])


def decrypt_existing_keys(apps, schema_editor):
    """Reverse: decrypt encrypted values back to plaintext."""
    try:
        from repo.storage.encryption import decrypt_value, _ENCRYPTED_PREFIX
    except ImportError:
        return

    PGPSigningKey = apps.get_model("repo", "PGPSigningKey")
    for key in PGPSigningKey.objects.all():
        changed = False
        if key.private_key_pem and key.private_key_pem.startswith(_ENCRYPTED_PREFIX):
            key.private_key_pem = decrypt_value(key.private_key_pem)
            changed = True
        if key.passphrase and key.passphrase.startswith(_ENCRYPTED_PREFIX):
            key.passphrase = decrypt_value(key.passphrase)
            changed = True
        if changed:
            key.save(update_fields=["private_key_pem", "passphrase"])


class Migration(migrations.Migration):

    dependencies = [
        ("repo", "0015_add_apk_repo_type"),
    ]

    operations = [
        migrations.RunPython(encrypt_existing_keys, decrypt_existing_keys),
    ]
