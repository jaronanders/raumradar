import os
from cryptography.fernet import Fernet

_KEY = os.environ.get("UNTIS_ENCRYPTION_KEY").encode()
_cipher = Fernet(_KEY)

def encrypt_password(password: str) -> str:
    return _cipher.encrypt(password.encode()).decode()


def decrypt_password(encrypted_password: str) -> str:
    return _cipher.decrypt(encrypted_password.encode()).decode()