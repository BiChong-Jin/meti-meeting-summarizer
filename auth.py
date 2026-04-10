"""User authentication — registration, login, and admin functions."""

import logging
import os
import time

import bcrypt

from db import get_connection

log = logging.getLogger(__name__)

ALLOWED_DOMAIN = os.getenv("ALLOWED_DOMAIN", "")


class AuthError(Exception):
    """Raised for authentication/registration failures."""


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def _validate_email(email: str) -> None:
    """Validate that the email belongs to the allowed domain."""
    if not email or "@" not in email:
        raise AuthError("有効なメールアドレスを入力してください。")

    if not ALLOWED_DOMAIN:
        raise AuthError("ALLOWED_DOMAIN が設定されていません。管理者に連絡してください。")

    domain = email.split("@", 1)[1].lower()
    if domain != ALLOWED_DOMAIN.lower():
        raise AuthError(f"@{ALLOWED_DOMAIN} のメールアドレスのみ登録できます。")


def _is_first_user() -> bool:
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) as cnt FROM users").fetchone()
    return row["cnt"] == 0


def register_user(email: str, password: str) -> None:
    """Register a new user. First user auto-gets admin role."""
    email = email.strip().lower()
    _validate_email(email)

    if len(password) < 8:
        raise AuthError("パスワードは8文字以上にしてください。")

    role = "admin" if _is_first_user() else "user"

    with get_connection() as conn:
        existing = conn.execute("SELECT email FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            raise AuthError("このメールアドレスは既に登録されています。")

        conn.execute(
            "INSERT INTO users (email, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
            (email, _hash_password(password), role, time.strftime("%Y-%m-%dT%H:%M:%S")),
        )
    log.info("User registered: %s (role=%s)", email, role)


def authenticate(email: str, password: str) -> dict:
    """Verify credentials and return user info. Raises AuthError on failure."""
    email = email.strip().lower()

    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

    if not row or not _verify_password(password, row["password_hash"]):
        raise AuthError("メールアドレスまたはパスワードが正しくありません。")

    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET last_login = ? WHERE email = ?",
            (time.strftime("%Y-%m-%dT%H:%M:%S"), email),
        )

    return {"email": row["email"], "role": row["role"]}


def list_users() -> list[dict]:
    """Return all users (no password hashes)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT email, role, created_at, last_login FROM users ORDER BY created_at"
        ).fetchall()
    return [dict(r) for r in rows]


def update_role(email: str, new_role: str) -> None:
    """Change a user's role to 'admin' or 'user'."""
    with get_connection() as conn:
        conn.execute("UPDATE users SET role = ? WHERE email = ?", (new_role, email))
    log.info("Role updated: %s -> %s", email, new_role)


def delete_user(email: str) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM users WHERE email = ?", (email,))
    log.info("User deleted: %s", email)
