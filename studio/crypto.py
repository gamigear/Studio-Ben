"""Mã hóa AES-256-GCM cho các giá trị bí mật (API key) lưu trong DB.

Khóa 256-bit được dẫn xuất từ settings.FIELD_ENCRYPTION_KEY bằng HKDF-SHA256.
Định dạng lưu: "v1:" + base64(nonce 12 byte + ciphertext + tag).
"""

import base64
import os
from functools import lru_cache

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings
from django.db import models

PREFIX = "v1:"


@lru_cache(maxsize=4)
def _key(secret: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=b"lenlich-field-encryption", info=b"v1").derive(
        secret.encode()
    )


def encrypt(plaintext: str) -> str:
    nonce = os.urandom(12)
    sealed = AESGCM(_key(settings.FIELD_ENCRYPTION_KEY)).encrypt(nonce, plaintext.encode(), None)
    return PREFIX + base64.b64encode(nonce + sealed).decode()


def decrypt(token: str) -> str:
    if not token.startswith(PREFIX):
        raise ValueError("Giá trị không phải dữ liệu đã mã hóa.")
    raw = base64.b64decode(token[len(PREFIX) :])
    return AESGCM(_key(settings.FIELD_ENCRYPTION_KEY)).decrypt(raw[:12], raw[12:], None).decode()


class EncryptedTextField(models.TextField):
    """TextField tự mã hóa khi ghi và giải mã khi đọc."""

    def from_db_value(self, value, expression, connection):
        if not value:
            return value
        return decrypt(value)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if not value:
            return value
        return encrypt(value)
