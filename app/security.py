from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

_password_hasher = PasswordHasher()


class CredentialCipher:
    def __init__(self, key: str):
        try:
            self._fernet = Fernet(key.encode())
        except (TypeError, ValueError) as exc:
            raise ValueError("유효한 Fernet 암호화 키가 필요합니다") from exc

    def encrypt(self, value: str) -> str:
        if not value:
            return ""
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        if not value:
            return ""
        try:
            return self._fernet.decrypt(value.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("자격증명을 복호화할 수 없습니다") from exc


def hash_password(value: str) -> str:
    return _password_hasher.hash(value)


def verify_password(value: str, encoded: str) -> bool:
    try:
        return _password_hasher.verify(encoded, value)
    except VerifyMismatchError:
        return False
