"""
storage.py

Persistence layer for LegalHelp accounts and per-account analysis
history.

Design notes
------------
- Uses SQLite via the standard library `sqlite3` module -- no extra
  infrastructure (no external DB server) is required, which keeps the
  app easy to self-host while still giving real persistence across
  restarts (unlike `st.session_state`, which is wiped per session).
- The database file lives outside of source control (see config.py /
  .gitignore) and is created automatically on first run.
- Passwords are never stored in plain text -- see auth.py for hashing.
  This module only stores whatever password hash/salt it is given; it
  has no knowledge of the hashing scheme itself.
- "Persistent memory" in the product sense means: every document
  analysis a logged-in user runs is saved to their account's history
  (question, explanation, language, timestamp) so they can revisit it
  after logging back in, from any device/session. Uploaded page
  images themselves are still never persisted (kept in-memory only,
  per the app's existing privacy design) -- only the resulting text
  Q&A is stored.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from config import DATABASE_PATH

logger = logging.getLogger(__name__)

# A single process-wide lock keeps SQLite writes safe under Streamlit's
# multi-session-single-process execution model without needing a
# separate database server.
_DB_LOCK = threading.Lock()


# --------------------------------------------------------------------------
# Data models
# --------------------------------------------------------------------------

@dataclass
class UserRecord:
    """A stored user account."""

    id: int
    email: str
    display_name: str
    password_hash: str
    password_salt: str
    is_confirmed: bool
    created_at: str


@dataclass
class HistoryEntry:
    """One saved analysis result belonging to a user account."""

    id: int
    user_id: int
    question: str
    response_text: str
    language_code: str
    created_at: str


# --------------------------------------------------------------------------
# Connection handling
# --------------------------------------------------------------------------

def _connect() -> sqlite3.Connection:
    Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    # `timeout` bounds how long sqlite3 itself will block waiting on a
    # file lock held by another connection, in seconds. Without this,
    # a stuck/overlapping connection (e.g. from an interrupted rerun
    # on a managed host with unusual filesystem locking behavior) can
    # hang the whole app indefinitely with no error and no traceback --
    # exactly the "infinite spinner" failure mode this guards against.
    connection = sqlite3.connect(
        DATABASE_PATH, check_same_thread=False, timeout=10
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    # WAL (Write-Ahead Logging) mode lets readers and writers avoid
    # blocking each other in the common case, which matters here since
    # Streamlit can run multiple overlapping script executions (reruns,
    # concurrent sessions) against the same database file.
    connection.execute("PRAGMA journal_mode = WAL;")
    # Belt-and-braces alongside the connect() timeout above: this sets
    # SQLite's internal busy-retry window as well.
    connection.execute("PRAGMA busy_timeout = 10000;")
    return connection


@contextmanager
def _db():
    """Context manager yielding a locked, committed SQLite connection."""
    with _DB_LOCK:
        connection = _connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


# Streamlit re-executes the whole script on every rerun (button click,
# widget interaction, etc.), so app.py's top-level `storage.init_db()`
# call fires far more often than "once per process start". The SQL
# itself (CREATE TABLE IF NOT EXISTS) is idempotent and safe to repeat,
# but repeating it doesn't need to acquire the DB lock and open a new
# connection every single rerun -- this flag skips that unnecessary
# work (and lock contention) after the first successful call in this
# process.
_SCHEMA_READY = False


def init_db() -> None:
    """
    Create the database schema if it doesn't already exist.

    Safe to call on every app startup or rerun -- CREATE TABLE IF NOT
    EXISTS is idempotent -- but only does real work once per process.
    """
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return

    with _db() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                email           TEXT NOT NULL UNIQUE,
                display_name    TEXT NOT NULL,
                password_hash   TEXT NOT NULL,
                password_salt   TEXT NOT NULL,
                is_confirmed    INTEGER NOT NULL DEFAULT 0,
                created_at      TEXT NOT NULL
            );
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS confirmation_tokens (
                token           TEXT PRIMARY KEY,
                user_id         INTEGER NOT NULL,
                created_at      TEXT NOT NULL,
                expires_at      TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS analysis_history (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL,
                question        TEXT NOT NULL,
                response_text   TEXT NOT NULL,
                language_code   TEXT NOT NULL,
                created_at      TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )
    _SCHEMA_READY = True
    logger.info("Database schema ready at %s", DATABASE_PATH)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------
# User account queries
# --------------------------------------------------------------------------

def create_user(
    email: str, display_name: str, password_hash: str, password_salt: str
) -> UserRecord:
    """
    Insert a new, unconfirmed user account.

    Raises:
        ValueError: If the email is already registered.
    """
    normalized_email = email.strip().lower()
    with _db() as connection:
        try:
            cursor = connection.execute(
                """
                INSERT INTO users
                    (email, display_name, password_hash, password_salt,
                     is_confirmed, created_at)
                VALUES (?, ?, ?, ?, 0, ?)
                """,
                (
                    normalized_email,
                    display_name.strip(),
                    password_hash,
                    password_salt,
                    _utc_now_iso(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("An account with that email already exists.") from exc

        user_id = cursor.lastrowid

    return get_user_by_id(user_id)  # type: ignore[return-value]


def get_user_by_email(email: str) -> Optional[UserRecord]:
    normalized_email = email.strip().lower()
    with _db() as connection:
        row = connection.execute(
            "SELECT * FROM users WHERE email = ?", (normalized_email,)
        ).fetchone()
    return _row_to_user(row) if row else None


def get_user_by_id(user_id: int) -> Optional[UserRecord]:
    with _db() as connection:
        row = connection.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return _row_to_user(row) if row else None


def confirm_user(user_id: int) -> None:
    with _db() as connection:
        connection.execute(
            "UPDATE users SET is_confirmed = 1 WHERE id = ?", (user_id,)
        )


def update_password(user_id: int, password_hash: str, password_salt: str) -> None:
    with _db() as connection:
        connection.execute(
            "UPDATE users SET password_hash = ?, password_salt = ? WHERE id = ?",
            (password_hash, password_salt, user_id),
        )


def _row_to_user(row: sqlite3.Row) -> UserRecord:
    return UserRecord(
        id=row["id"],
        email=row["email"],
        display_name=row["display_name"],
        password_hash=row["password_hash"],
        password_salt=row["password_salt"],
        is_confirmed=bool(row["is_confirmed"]),
        created_at=row["created_at"],
    )


# --------------------------------------------------------------------------
# Confirmation tokens
# --------------------------------------------------------------------------

def store_confirmation_token(token: str, user_id: int, expires_at: str) -> None:
    with _db() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO confirmation_tokens
                (token, user_id, created_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (token, user_id, _utc_now_iso(), expires_at),
        )


def pop_confirmation_token(token: str) -> Optional[dict]:
    """
    Look up and delete a confirmation token in one step (single-use).

    Returns:
        dict with 'user_id' and 'expires_at' if the token existed,
        else None.
    """
    with _db() as connection:
        row = connection.execute(
            "SELECT user_id, expires_at FROM confirmation_tokens WHERE token = ?",
            (token,),
        ).fetchone()
        if row is None:
            return None
        connection.execute(
            "DELETE FROM confirmation_tokens WHERE token = ?", (token,)
        )
        return {"user_id": row["user_id"], "expires_at": row["expires_at"]}


# --------------------------------------------------------------------------
# Analysis history ("persistent memory")
# --------------------------------------------------------------------------

def save_history_entry(
    user_id: int, question: str, response_text: str, language_code: str
) -> None:
    with _db() as connection:
        connection.execute(
            """
            INSERT INTO analysis_history
                (user_id, question, response_text, language_code, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, question, response_text, language_code, _utc_now_iso()),
        )


def get_history_for_user(user_id: int, limit: int = 50) -> List[HistoryEntry]:
    with _db() as connection:
        rows = connection.execute(
            """
            SELECT * FROM analysis_history
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    return [
        HistoryEntry(
            id=row["id"],
            user_id=row["user_id"],
            question=row["question"],
            response_text=row["response_text"],
            language_code=row["language_code"],
            created_at=row["created_at"],
        )
        for row in rows
    ]


def delete_history_entry(entry_id: int, user_id: int) -> None:
    """Delete a single history entry, scoped to its owning user for safety."""
    with _db() as connection:
        connection.execute(
            "DELETE FROM analysis_history WHERE id = ? AND user_id = ?",
            (entry_id, user_id),
        )


def clear_history_for_user(user_id: int) -> None:
    with _db() as connection:
        connection.execute(
            "DELETE FROM analysis_history WHERE user_id = ?", (user_id,)
        )
