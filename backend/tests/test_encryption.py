"""Unit tests for encryption.py (AES-256-GCM)."""
import hashlib
import os

import pytest

import encryption as enc


def test_encrypt_decrypt_roundtrip():
    plaintext = b"Hello, Patrimonium!"
    assert enc.decrypt(enc.encrypt(plaintext)) == plaintext


def test_encrypt_str_decrypt_str():
    text = "secret password 🔒"
    assert enc.decrypt_str(enc.encrypt_str(text)) == text


def test_sha256_hex_known_value():
    data = b"abc"
    expected = hashlib.sha256(b"abc").hexdigest()
    assert enc.sha256_hex(data) == expected


def test_different_nonces_per_encryption():
    data = b"same data"
    ct1 = enc.encrypt(data)
    ct2 = enc.encrypt(data)
    # Nonces (first 12 bytes) must differ
    assert ct1[:12] != ct2[:12]
    # But both must decrypt correctly
    assert enc.decrypt(ct1) == data
    assert enc.decrypt(ct2) == data


def test_ciphertext_size():
    plaintext = b"X" * 50
    ct = enc.encrypt(plaintext)
    # nonce (12) + ciphertext + GCM auth tag (16)
    assert len(ct) == 12 + len(plaintext) + 16


def test_tampered_ciphertext_raises():
    ct = bytearray(enc.encrypt(b"sensitive"))
    ct[20] ^= 0xFF  # flip a bit in ciphertext
    with pytest.raises(Exception):
        enc.decrypt(bytes(ct))


def test_missing_encryption_key_raises(monkeypatch):
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ENCRYPTION_KEY"):
        enc._get_key()
