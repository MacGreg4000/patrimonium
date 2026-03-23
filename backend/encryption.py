"""AES-256-GCM encryption/decryption for file blobs and sensitive fields."""
import base64
import hashlib
import os
import secrets
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _get_key() -> bytes:
    raw = os.getenv("ENCRYPTION_KEY", "")
    if not raw:
        raise RuntimeError("ENCRYPTION_KEY environment variable is not set")
    try:
        key = base64.urlsafe_b64decode(raw.encode())
        if len(key) != 32:
            raise ValueError(f"Key must be 32 bytes, got {len(key)}")
        return key
    except Exception as e:
        raise RuntimeError(f"Invalid ENCRYPTION_KEY: {e}") from e


def encrypt(data: bytes) -> bytes:
    """Encrypt bytes with AES-256-GCM. Returns nonce + ciphertext."""
    key = _get_key()
    nonce = secrets.token_bytes(12)          # 96-bit nonce for GCM
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(nonce, data, None)   # no associated data
    return nonce + ct                        # prepend nonce


def decrypt(blob: bytes) -> bytes:
    """Decrypt bytes encrypted with `encrypt`."""
    key = _get_key()
    nonce, ct = blob[:12], blob[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ct, None)


def encrypt_str(plaintext: str) -> str:
    """Encrypt a UTF-8 string, return base64-encoded ciphertext."""
    blob = encrypt(plaintext.encode())
    return base64.urlsafe_b64encode(blob).decode()


def decrypt_str(ciphertext: str) -> str:
    """Decrypt a base64-encoded ciphertext string."""
    blob = base64.urlsafe_b64decode(ciphertext.encode())
    return decrypt(blob).decode()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
