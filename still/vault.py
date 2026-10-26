"""Passphrase-protected encryption for secrets and imported reports.

A random 256-bit data key encrypts everything with AES-GCM. The data key is
stored only wrapped by a key derived from the owner's passphrase with scrypt,
so changing the passphrase re-wraps one key instead of re-encrypting data. The
passphrase cannot be recovered; a forgotten passphrase means resetting Still.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1}
MIN_PASSPHRASE, MAX_PASSPHRASE = 12, 1024
WRAP_CONTEXT = b"still/data-key/v1"


class VaultError(Exception):
    """Safe to display."""


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _kek(passphrase: str, salt: bytes, params: dict) -> bytes:
    return hashlib.scrypt(passphrase.encode(), salt=salt, n=params["n"], r=params["r"], p=params["p"],
                          maxmem=128 * 1024 * 1024, dklen=32)


def check_passphrase(passphrase) -> str:
    if not isinstance(passphrase, str) or not MIN_PASSPHRASE <= len(passphrase) <= MAX_PASSPHRASE:
        raise VaultError(f"Use a passphrase of at least {MIN_PASSPHRASE} characters.")
    if len(set(passphrase)) < 5:
        raise VaultError("Use a passphrase with more variety; repeated characters are easy to guess.")
    return passphrase


def _wrap(passphrase: str, key: bytes) -> dict:
    salt, nonce = os.urandom(16), os.urandom(12)
    wrapped = AESGCM(_kek(passphrase, salt, SCRYPT)).encrypt(nonce, key, WRAP_CONTEXT)
    return {"version": 1, "kdf": "scrypt", **SCRYPT, "salt": _b64(salt), "nonce": _b64(nonce), "wrapped": _b64(wrapped)}


def create(passphrase: str) -> tuple[dict, bytes]:
    """Return (record to store, data key held in memory)."""
    key = os.urandom(32)
    return _wrap(check_passphrase(passphrase), key), key


def unlock(record: dict, passphrase) -> bytes:
    if not isinstance(passphrase, str) or len(passphrase) > MAX_PASSPHRASE:
        raise VaultError("Incorrect passphrase.")
    try:
        params = {k: int(record[k]) for k in ("n", "r", "p")}
        kek = _kek(passphrase, base64.b64decode(record["salt"]), params)
        return AESGCM(kek).decrypt(base64.b64decode(record["nonce"]), base64.b64decode(record["wrapped"]), WRAP_CONTEXT)
    except InvalidTag:
        raise VaultError("Incorrect passphrase.") from None
    except (KeyError, ValueError, TypeError):
        raise VaultError("The saved key record is damaged. Reset Still to start again.") from None


def rewrap(record: dict, current: str, new: str) -> dict:
    return _wrap(check_passphrase(new), unlock(record, current))


def seal(key: bytes, plaintext: bytes, purpose: str) -> bytes:
    """Encrypt with a fresh nonce; `purpose` binds the ciphertext to its use."""
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, purpose.encode())


def open_sealed(key: bytes, blob: bytes, purpose: str) -> bytes:
    try:
        return AESGCM(key).decrypt(blob[:12], blob[12:], purpose.encode())
    except (InvalidTag, ValueError):
        raise VaultError("Saved data could not be decrypted; it may be damaged.") from None


def fingerprint(key: bytes, data: bytes) -> str:
    """Keyed digest for duplicate detection that reveals nothing without the key."""
    return hmac.new(key, b"still/fingerprint/v1" + data, hashlib.sha256).hexdigest()
