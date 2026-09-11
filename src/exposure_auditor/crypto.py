"""Field-level encryption for PII columns.

RDS encryption at rest protects the disk; this protects the rows themselves
from anyone who can run a SELECT (a leaked read replica, a support query, a
backup restored somewhere careless). Values we need to look up by equality get
a blind index: an HMAC of the normalized value under a separate key.
"""

import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken


class FieldCipher:
    def __init__(self, encryption_key: str, index_key: str) -> None:
        self._fernet = Fernet(encryption_key.encode())
        self._index_key = index_key.encode()

    def encrypt(self, value: bytes) -> bytes:
        return self._fernet.encrypt(value)

    def decrypt(self, token: bytes) -> bytes:
        try:
            return self._fernet.decrypt(token)
        except InvalidToken as exc:
            raise ValueError("ciphertext could not be decrypted with the configured key") from exc

    def blind_index(self, namespace: str, normalized: str) -> str:
        msg = f"{namespace}\x00{normalized}".encode()
        return hmac.new(self._index_key, msg, hashlib.sha256).hexdigest()


_cipher: FieldCipher | None = None


def configure_cipher(cipher: FieldCipher) -> None:
    global _cipher
    _cipher = cipher


def get_cipher() -> FieldCipher:
    if _cipher is None:
        raise RuntimeError("field cipher not configured; create_app() sets it up")
    return _cipher
