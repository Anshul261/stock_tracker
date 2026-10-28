"""SQLite storage for settings, encrypted secrets, encrypted reports and sync history."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
import json
import os
import sqlite3

from . import vault

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS secrets (name TEXT PRIMARY KEY, blob BLOB NOT NULL, updated TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL, received TEXT NOT NULL, source TEXT NOT NULL,
  from_date TEXT NOT NULL, to_date TEXT NOT NULL, blob BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS sync_runs (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, started TEXT NOT NULL, finished TEXT,
  status TEXT NOT NULL, message TEXT NOT NULL DEFAULT '', summary TEXT NOT NULL DEFAULT '{}');
"""
DEFAULTS = {"mode": "demo", "autoLockMinutes": 30, "fromInception": False,
            "schedule": {"enabled": False, "time": "07:00"}, "lastScheduledRun": None,
            "tokenSavedAt": None, "tokenExpires": None, "search": {"provider": None, "limit": 50}, "secContact": None, "pricesSavedAt": None}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class Store:
    def __init__(self, folder: Path):
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = folder / "still.db"
        if not self.path.exists():
            os.close(os.open(self.path, os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600))
        self.lock = RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    # Plain settings: preferences only. Never put secrets or account data here.
    def setting(self, key: str):
        with self.lock:
            row = self.db.execute("SELECT value FROM meta WHERE key = ?", ("setting:" + key,)).fetchone()
        return json.loads(row[0]) if row else DEFAULTS.get(key)

    def set_setting(self, key: str, value) -> None:
        if key not in DEFAULTS:
            raise KeyError(key)
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", ("setting:" + key, json.dumps(value)))

    def vault_record(self) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT value FROM meta WHERE key = 'vault'").fetchone()
        return json.loads(row[0]) if row else None

    def save_vault_record(self, record: dict) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO meta VALUES ('vault', ?)", (json.dumps(record),))

    def secret(self, key: bytes, name: str) -> str | None:
        with self.lock:
            row = self.db.execute("SELECT blob FROM secrets WHERE name = ?", (name,)).fetchone()
        return vault.open_sealed(key, row[0], "secret:" + name).decode() if row else None

    def set_secret(self, key: bytes, name: str, value: str | None) -> None:
        with self.lock:
            if value is None:
                self.db.execute("DELETE FROM secrets WHERE name = ?", (name,))
            else:
                self.db.execute("INSERT OR REPLACE INTO secrets VALUES (?, ?, ?)",
                                (name, vault.seal(key, value.encode(), "secret:" + name), now()))

    def has_secret(self, name: str) -> bool:
        with self.lock:
            return self.db.execute("SELECT 1 FROM secrets WHERE name = ?", (name,)).fetchone() is not None

    def add_report(self, key: bytes, data: bytes, source: str, from_date: str, to_date: str) -> int | None:
        """Store an encrypted report; return its id, or None if it is already stored."""
        mark = vault.fingerprint(key, data)
        with self.lock:
            if self.db.execute("SELECT 1 FROM reports WHERE fingerprint = ?", (mark,)).fetchone():
                return None
            cursor = self.db.execute(
                "INSERT INTO reports (fingerprint, received, source, from_date, to_date, blob) VALUES (?, ?, ?, ?, ?, ?)",
                (mark, now(), source, from_date, to_date, vault.seal(key, data, "report")))
            return cursor.lastrowid

    def reports(self) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT id, received, source, from_date, to_date FROM reports ORDER BY from_date, id").fetchall()
        return [dict(zip(("id", "received", "source", "fromDate", "toDate"), r)) for r in rows]

    def report_data(self, key: bytes) -> list[bytes]:
        with self.lock:
            rows = self.db.execute("SELECT blob FROM reports ORDER BY from_date, id").fetchall()
        return [vault.open_sealed(key, r[0], "report") for r in rows]

    def delete_reports(self) -> None:
        with self.lock:
            self.db.execute("DELETE FROM reports")
            self.db.execute("VACUUM")

    def start_run(self, kind: str) -> int:
        with self.lock:
            return self.db.execute("INSERT INTO sync_runs (kind, started, status) VALUES (?, ?, 'running')",
                                   (kind, now())).lastrowid

    def finish_run(self, run: int, status: str, message: str, summary: dict | None = None) -> None:
        with self.lock:
            self.db.execute("UPDATE sync_runs SET finished = ?, status = ?, message = ?, summary = ? WHERE id = ?",
                            (now(), status, message, json.dumps(summary or {}), run))
            # Keep a bounded history.
            self.db.execute("DELETE FROM sync_runs WHERE id NOT IN (SELECT id FROM sync_runs ORDER BY id DESC LIMIT 50)")

    def runs(self, limit: int = 20) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT id, kind, started, finished, status, message, summary FROM sync_runs "
                                   "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{"id": r[0], "kind": r[1], "started": r[2], "finished": r[3], "status": r[4], "message": r[5],
                 "summary": json.loads(r[6])} for r in rows]

    def wipe(self) -> None:
        """Remove every secret, report, run and setting, including the key record."""
        with self.lock:
            for table in ("meta", "secrets", "reports", "sync_runs"):
                self.db.execute(f"DELETE FROM {table}")
            self.db.execute("VACUUM")
