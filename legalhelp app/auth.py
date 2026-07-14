"""
auth.py

Account authentication for LegalHelp: signup, login, logout, password
hashing, email-confirmation tokens, and multi-account switching within
a single browser session.

Design notes
------------
- Password hashing uses PBKDF2-HMAC-SHA256 via the standard library
  `hashlib`, with a random per-user salt (`secrets.token_hex`). This
  avoids adding a new dependency (e.g. bcrypt/argon2) while still being
  a slow, salted, industry-standard KDF rather than a fast general
  hash -- appropriate for a project of this scope.
- "Confirmation" (verifying account ownership) is implemented as a
  signed, single-use token tied to the account. In a real deployment
  this token would be emailed to the user and clicked from their inbox.
  This project has no outbound email/SMTP configured, so the token is
  instead surfaced directly in the UI after signup (clearly labeled as
  a local/demo confirmation step) -- see app.py. The token flow itself
  (generation, expiry, single-use, storage) is fully real; only the
  delivery channel is simulated. This is called out explicitly in the
  UI and README so it's never mistaken for a production email flow.
- Multiple accounts: `st.session_state` holds the currently active
  user, plus a small list of "remembered" accounts (id + email +
  display name only, never passwords) the user has logged into during
  this browser session, so switching between them doesn't require
  re-typing credentials each time within the same session.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import streamlit as st

import storage
from config import (
    CONFIRMATION_TOKEN_TTL_MINUTES,
    MAX_REMEMBERED_ACCOUNTS,
    MIN_PASSWORD_LENGTH,
    PBKDF2_ITERATIONS,
)

logger = logging.getLogger(__name__)

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_SESSION_KEY_CURRENT_USER = "auth_current_user"
_SESSION_KEY_REMEMBERED = "auth_remembered_accounts"
_SESSION_KEY_PENDING_CONFIRM_EMAIL = "auth_pending_confirm_email"


# --------------------------------------------------------------------------
# Data model exposed to the UI layer
# --------------------------------------------------------------------------

@dataclass
class AuthUser:
    """Minimal, UI-facing view of a logged-in account (no secrets)."""

    id: int
    email: str
    display_name: str
    is_confirmed: bool


def _to_auth_user(record: storage.UserRecord) -> AuthUser:
    return AuthUser(
        id=record.id,
        email=record.email,
        display_name=record.display_name,
        is_confirmed=record.is_confirmed,
    )


# --------------------------------------------------------------------------
# Password hashing
# --------------------------------------------------------------------------

def _hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    """
    Hash a password with PBKDF2-HMAC-SHA256.

    Args:
        password: The plain-text password to hash.
        salt: Existing hex-encoded salt to reuse (for verification). If
            omitted, a new random salt is generated (for new passwords).

    Returns:
        tuple[str, str]: (hex_digest, hex_salt)
    """
    salt_bytes = bytes.fromhex(salt) if salt else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt_bytes, PBKDF2_ITERATIONS
    )
    return digest.hex(), salt_bytes.hex()


def _verify_password(password: str, stored_hash: str, stored_salt: str) -> bool:
    candidate_hash, _ = _hash_password(password, salt=stored_salt)
    return hmac.compare_digest(candidate_hash, stored_hash)


# --------------------------------------------------------------------------
# Validation helpers
# --------------------------------------------------------------------------

def _validate_signup_fields(
    email: str, display_name: str, password: str, confirm_password: str
) -> Optional[str]:
    if not email or not _EMAIL_PATTERN.match(email.strip()):
        return "Please enter a valid email address."
    if not display_name or not display_name.strip():
        return "Please enter a display name."
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if password != confirm_password:
        return "Passwords do not match."
    return None


# --------------------------------------------------------------------------
# Confirmation tokens
# --------------------------------------------------------------------------

def _generate_confirmation_token(user_id: int) -> str:
    token = secrets.token_urlsafe(24)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(minutes=CONFIRMATION_TOKEN_TTL_MINUTES)
    ).isoformat()
    storage.store_confirmation_token(token, user_id, expires_at)
    return token


def confirm_account(token: str) -> tuple[bool, str]:
    """
    Redeem a confirmation token, marking the associated account confirmed.

    Returns:
        tuple[bool, str]: (success, user_facing_message)
    """
    token = (token or "").strip()
    if not token:
        return False, "Please enter a confirmation code."

    record = storage.pop_confirmation_token(token)
    if record is None:
        return False, "That confirmation code is invalid or has already been used."

    expires_at = datetime.fromisoformat(record["expires_at"])
    if expires_at < datetime.now(timezone.utc):
        return False, "That confirmation code has expired. Please request a new one."

    storage.confirm_user(record["user_id"])
    logger.info("Account %s confirmed.", record["user_id"])
    return True, "Your account is confirmed! You can now log in."


def resend_confirmation_token(email: str) -> tuple[bool, str, Optional[str]]:
    """
    Generate a fresh confirmation token for an unconfirmed account.

    Returns:
        tuple[bool, str, Optional[str]]: (success, message, token)
        `token` is returned directly since this project has no email
        delivery configured -- see module docstring.
    """
    user = storage.get_user_by_email(email)
    if user is None:
        # Deliberately vague to avoid leaking which emails are registered.
        return False, "If that account exists, a new code has been generated.", None
    if user.is_confirmed:
        return False, "That account is already confirmed. You can log in.", None

    token = _generate_confirmation_token(user.id)
    return True, "A new confirmation code has been generated.", token


# --------------------------------------------------------------------------
# Signup / login / logout
# --------------------------------------------------------------------------

def sign_up(
    email: str, display_name: str, password: str, confirm_password: str
) -> tuple[bool, str, Optional[str]]:
    """
    Register a new account (unconfirmed until the token is redeemed).

    Returns:
        tuple[bool, str, Optional[str]]: (success, message, confirmation_token)
    """
    validation_error = _validate_signup_fields(
        email, display_name, password, confirm_password
    )
    if validation_error:
        return False, validation_error, None

    password_hash, password_salt = _hash_password(password)

    try:
        user = storage.create_user(
            email=email.strip(),
            display_name=display_name.strip(),
            password_hash=password_hash,
            password_salt=password_salt,
        )
    except ValueError as exc:
        return False, str(exc), None

    token = _generate_confirmation_token(user.id)
    logger.info("New account created for user id %s (unconfirmed).", user.id)
    return (
        True,
        "Account created! Confirm it below to finish signing up.",
        token,
    )


def log_in(email: str, password: str) -> tuple[bool, str]:
    """
    Verify credentials and, if valid, set the account as the active
    session user (and add it to the remembered-accounts list).

    Returns:
        tuple[bool, str]: (success, message)
    """
    record = storage.get_user_by_email(email)
    if record is None or not _verify_password(
        password, record.password_hash, record.password_salt
    ):
        return False, "Incorrect email or password."

    if not record.is_confirmed:
        return (
            False,
            "This account hasn't been confirmed yet. Check the confirmation "
            "step from signup, or request a new code below.",
        )

    _set_active_user(_to_auth_user(record))
    logger.info("User id %s logged in.", record.id)
    return True, f"Welcome back, {record.display_name}!"


def log_out() -> None:
    """Clear the active session user (remembered accounts are kept)."""
    st.session_state[_SESSION_KEY_CURRENT_USER] = None


def switch_account(user_id: int) -> tuple[bool, str]:
    """
    Switch the active session to an already-remembered account, without
    re-entering a password, as long as it was logged into earlier in
    this same browser session.
    """
    remembered = get_remembered_accounts()
    match = next((account for account in remembered if account.id == user_id), None)
    if match is None:
        return False, "That account isn't available to switch to in this session."

    # Re-fetch fresh data (display name/confirmation status may have
    # changed) rather than trusting the cached remembered-account copy.
    record = storage.get_user_by_id(user_id)
    if record is None:
        return False, "That account no longer exists."

    _set_active_user(_to_auth_user(record))
    return True, f"Switched to {record.display_name}."


def _set_active_user(user: AuthUser) -> None:
    st.session_state[_SESSION_KEY_CURRENT_USER] = user

    remembered = get_remembered_accounts()
    remembered = [account for account in remembered if account.id != user.id]
    remembered.insert(0, user)
    st.session_state[_SESSION_KEY_REMEMBERED] = remembered[:MAX_REMEMBERED_ACCOUNTS]


def forget_account(user_id: int) -> None:
    """Remove an account from the session's remembered-accounts list."""
    remembered = get_remembered_accounts()
    st.session_state[_SESSION_KEY_REMEMBERED] = [
        account for account in remembered if account.id != user_id
    ]
    current = get_current_user()
    if current and current.id == user_id:
        log_out()


# --------------------------------------------------------------------------
# Session accessors
# --------------------------------------------------------------------------

def get_current_user() -> Optional[AuthUser]:
    return st.session_state.get(_SESSION_KEY_CURRENT_USER)


def get_remembered_accounts() -> List[AuthUser]:
    return st.session_state.get(_SESSION_KEY_REMEMBERED, [])


def is_logged_in() -> bool:
    return get_current_user() is not None


def change_password(
    user_id: int, current_password: str, new_password: str, confirm_new_password: str
) -> tuple[bool, str]:
    record = storage.get_user_by_id(user_id)
    if record is None:
        return False, "Account not found."
    if not _verify_password(current_password, record.password_hash, record.password_salt):
        return False, "Current password is incorrect."
    if len(new_password) < MIN_PASSWORD_LENGTH:
        return False, f"New password must be at least {MIN_PASSWORD_LENGTH} characters."
    if new_password != confirm_new_password:
        return False, "New passwords do not match."

    password_hash, password_salt = _hash_password(new_password)
    storage.update_password(user_id, password_hash, password_salt)
    return True, "Password updated."
