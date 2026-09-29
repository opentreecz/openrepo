"""Transparent field-level encryption for sensitive model fields.

Uses Fernet symmetric encryption with a key derived from Django's
SECRET_KEY.  Values are encrypted on save and decrypted on load,
so application code sees plaintext while the database stores ciphertext.

The encryption key is derived once at import time using PBKDF2-HMAC-SHA256
with a fixed salt.  This means the same SECRET_KEY always produces the
same encryption key, which is required for decrypting existing data.
"""
import base64
import logging

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from django.conf import settings
from django.db import models

logger = logging.getLogger("openrepo_web")

# Prefix added to encrypted values so we can distinguish them from
# plaintext (important during migration).
_ENCRYPTED_PREFIX = "enc::"


def _derive_key():
    """Derive a Fernet key from Django's SECRET_KEY."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"openrepo-field-encryption-v1",
        iterations=100_000,
    )
    key_bytes = kdf.derive(settings.SECRET_KEY.encode("utf-8"))
    return base64.urlsafe_b64encode(key_bytes)


def _get_fernet():
    """Return a Fernet instance for the current SECRET_KEY."""
    return Fernet(_derive_key())


def encrypt_value(plaintext):
    """Encrypt a string value, returning a prefixed ciphertext string."""
    if not plaintext:
        return plaintext
    token = _get_fernet().encrypt(plaintext.encode("utf-8"))
    return _ENCRYPTED_PREFIX + token.decode("ascii")


def decrypt_value(stored):
    """Decrypt a stored value.  Returns plaintext if the value is not encrypted."""
    if not stored or not stored.startswith(_ENCRYPTED_PREFIX):
        return stored  # plaintext (pre-migration data)
    token = stored[len(_ENCRYPTED_PREFIX):].encode("ascii")
    try:
        return _get_fernet().decrypt(token).decode("utf-8")
    except InvalidToken:
        logger.warning("Failed to decrypt field value — returning as-is")
        return stored


class EncryptedCharField(models.CharField):
    """A CharField that transparently encrypts values at rest.

    In Python, the field behaves like a normal CharField (plaintext).
    In the database, the value is stored as Fernet-encrypted ciphertext
    prefixed with ``enc::``.

    Pre-existing plaintext values (without the prefix) are returned as-is,
    allowing a gradual migration.
    """

    def from_db_value(self, value, expression, connection):
        """Decrypt when loading from the database."""
        return decrypt_value(value)

    def get_prep_value(self, value):
        """Encrypt when saving to the database."""
        if value and not value.startswith(_ENCRYPTED_PREFIX):
            return encrypt_value(value)
        return value  # already encrypted or empty

    def deconstruct(self):
        """Return the field definition for migrations.

        Since EncryptedCharField behaves identically to CharField in
        the schema (same column type, same max_length), we report it
        as a plain CharField in migrations.  This avoids requiring
        the encryption module to be importable during migration
        generation on machines without cryptography installed.
        """
        name, path, args, kwargs = super().deconstruct()
        # Report as plain CharField so migrations don't reference this class
        path = "django.db.models.CharField"
        return name, path, args, kwargs
