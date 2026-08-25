import pytest

from app.security import CredentialCipher, hash_password, verify_password


def test_site_credentials_are_encrypted_and_round_trip():
    cipher = CredentialCipher("MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=")

    ciphertext = cipher.encrypt("super-secret")

    assert "super-secret" not in ciphertext
    assert cipher.decrypt(ciphertext) == "super-secret"


def test_wrong_encryption_key_cannot_decrypt():
    first = CredentialCipher("MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=")
    second = CredentialCipher("MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE=")

    with pytest.raises(ValueError, match="복호화"):
        second.decrypt(first.encrypt("secret"))


def test_application_password_uses_argon2():
    encoded = hash_password("administrator-password")

    assert encoded.startswith("$argon2")
    assert verify_password("administrator-password", encoded)
    assert not verify_password("wrong", encoded)
