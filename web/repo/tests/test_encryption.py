"""Tests for the field-level encryption module."""
from django.test import TestCase

from repo.storage.encryption import (
    EncryptedCharField,
    _ENCRYPTED_PREFIX,
    decrypt_value,
    encrypt_value,
)
from repo.models import PGPSigningKey


class EncryptDecryptTests(TestCase):
    """Unit tests for encrypt_value / decrypt_value."""

    def test_encrypt_returns_prefixed_string(self):
        ct = encrypt_value("my secret key")
        self.assertTrue(ct.startswith(_ENCRYPTED_PREFIX))

    def test_decrypt_roundtrip(self):
        plaintext = "-----BEGIN PGP PRIVATE KEY-----\ndata\n-----END PGP PRIVATE KEY-----"
        ct = encrypt_value(plaintext)
        self.assertNotEqual(ct, plaintext)
        self.assertEqual(decrypt_value(ct), plaintext)

    def test_decrypt_plaintext_passthrough(self):
        """Pre-migration plaintext values are returned as-is."""
        self.assertEqual(decrypt_value("plain value"), "plain value")

    def test_encrypt_empty_returns_empty(self):
        self.assertEqual(encrypt_value(""), "")
        self.assertIsNone(encrypt_value(None))

    def test_decrypt_empty_returns_empty(self):
        self.assertEqual(decrypt_value(""), "")
        self.assertIsNone(decrypt_value(None))

    def test_different_plaintexts_produce_different_ciphertexts(self):
        ct1 = encrypt_value("secret1")
        ct2 = encrypt_value("secret2")
        self.assertNotEqual(ct1, ct2)


class EncryptedCharFieldTests(TestCase):
    """Test that EncryptedCharField transparently encrypts in the DB."""

    def test_model_save_encrypts_and_load_decrypts(self):
        key = PGPSigningKey.objects.create(
            name="Test",
            email="t@example.com",
            fingerprint="F2TEST1234567890",
            private_key_pem="my-private-key",
            public_key_pem="my-public-key",
            passphrase="secret-pass",
        )

        # In Python, we see plaintext
        self.assertEqual(key.private_key_pem, "my-private-key")
        self.assertEqual(key.passphrase, "secret-pass")

        # Reload from DB — still plaintext in Python
        key.refresh_from_db()
        self.assertEqual(key.private_key_pem, "my-private-key")
        self.assertEqual(key.passphrase, "secret-pass")

    def test_deconstruct_reports_as_charfield(self):
        """Migrations see a plain CharField, not EncryptedCharField."""
        field = EncryptedCharField(max_length=100)
        name, path, args, kwargs = field.deconstruct()
        self.assertEqual(path, "django.db.models.CharField")
