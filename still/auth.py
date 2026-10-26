"""Owner sign-in for the local app.

There is one owner and one passphrase. Unlocking derives the data key and keeps
it in memory until the owner locks Still or the server stops, so scheduled
syncs can run. Browser sessions expire after the idle timeout without dropping
the key; signing back in needs the passphrase again.
"""
from __future__ import annotations

from threading import RLock
from typing import Callable
import secrets
import time

from . import vault
from .store import Store

COOKIE = "still_session"


class AuthError(Exception):
    """Safe to display."""


class Auth:
    def __init__(self, store: Store, clock: Callable[[], float] = time.monotonic):
        self.store, self.clock = store, clock
        self.lock = RLock()
        self.key: bytes | None = None
        self.sessions: dict[str, float] = {}
        self.failures, self.blocked_until = 0, 0.0

    def state(self) -> str:
        if self.store.vault_record() is None:
            return "setup"
        return "unlocked" if self.key is not None else "locked"

    def _session(self) -> str:
        token = secrets.token_urlsafe(32)
        self.sessions[token] = self.clock()
        return token

    def setup(self, passphrase) -> str:
        with self.lock:
            if self.store.vault_record() is not None:
                raise AuthError("Still is already set up. Sign in instead.")
            record, key = vault.create(passphrase)
            self.store.save_vault_record(record)
            self.key = key
            return self._session()

    def login(self, passphrase) -> str:
        with self.lock:
            record = self.store.vault_record()
            if record is None:
                raise AuthError("Still is not set up yet.")
            wait = self.blocked_until - self.clock()
            if wait > 0:
                raise AuthError(f"Too many attempts. Try again in {int(wait) + 1} seconds.")
            try:
                key = vault.unlock(record, passphrase)
            except vault.VaultError as error:
                self.failures += 1
                if self.failures >= 3:
                    self.blocked_until = self.clock() + min(300, 2 ** (self.failures - 3))
                raise AuthError(str(error)) from None
            self.failures, self.blocked_until = 0, 0.0
            self.key = key
            return self._session()

    def check(self, token: str | None) -> bool:
        with self.lock:
            seen = self.sessions.get(token or "")
            if seen is None or self.key is None:
                return False
            if self.clock() - seen > 60 * max(1, int(self.store.setting("autoLockMinutes"))):
                del self.sessions[token]
                return False
            self.sessions[token] = self.clock()
            return True

    def logout(self, token: str | None) -> None:
        with self.lock:
            self.sessions.pop(token or "", None)

    def lock_now(self) -> None:
        """Forget every session and the data key; background syncs stop."""
        with self.lock:
            self.sessions.clear()
            self.key = None

    def change_passphrase(self, current, new) -> None:
        with self.lock:
            try:
                self.store.save_vault_record(vault.rewrap(self.store.vault_record(), current, new))
            except vault.VaultError as error:
                raise AuthError(str(error)) from None

    def reset(self) -> None:
        with self.lock:
            self.store.wipe()
            self.lock_now()
            self.failures, self.blocked_until = 0, 0.0
