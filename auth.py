"""Caretaker authentication for ElderGuard.

Accounts live in data/caretakers.json. Passwords are never stored in plain
text: each account gets its own random salt and the password is hashed with
PBKDF2-HMAC-SHA256 (100,000 rounds) - standard library only.

A default demo account is seeded automatically on first run so the project
works out of the box. Extra caretakers can be added from the terminal:

    python auth.py add ravi@elderguard.local "Ravi Sharma" s3cret
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sys
from pathlib import Path
from typing import Any

ACCOUNTS_FILE = Path(__file__).resolve().parent / "data" / "caretakers.json"
HASH_ROUNDS = 100_000


def _load_accounts() -> list[dict[str, Any]]:
    ACCOUNTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        return json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_accounts(accounts: list[dict[str, Any]]) -> None:
    ACCOUNTS_FILE.write_text(json.dumps(accounts, indent=2), encoding="utf-8")


def _hash_password(password: str, salt_hex: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), HASH_ROUNDS
    ).hex()


def ensure_default_account(email: str, password: str, name: str) -> None:
    """Create the starter account once, if no account with that email exists."""
    accounts = _load_accounts()
    if any(account["email"].lower() == email.lower() for account in accounts):
        return
    salt = secrets.token_hex(16)
    accounts.append({
        "email": email,
        "name": name,
        "salt": salt,
        "password_hash": _hash_password(password, salt),
    })
    _save_accounts(accounts)


def add_account(email: str, password: str, name: str) -> bool:
    """Add a caretaker account. Returns False if the email already exists."""
    accounts = _load_accounts()
    if any(account["email"].lower() == email.lower() for account in accounts):
        return False
    salt = secrets.token_hex(16)
    accounts.append({
        "email": email.strip(),
        "name": name.strip(),
        "salt": salt,
        "password_hash": _hash_password(password, salt),
    })
    _save_accounts(accounts)
    return True


def authenticate(email: str, password: str) -> dict[str, str] | None:
    """Return {name, email} when credentials match, otherwise None."""
    for account in _load_accounts():
        if account.get("email", "").lower() != email.strip().lower():
            continue
        attempt = _hash_password(password, account["salt"])
        if secrets.compare_digest(attempt, account["password_hash"]):
            return {"name": account["name"], "email": account["email"]}
    return None


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "add":
        email, name, password = sys.argv[2], sys.argv[3], sys.argv[4]
        print("Account created." if add_account(email, password, name)
              else "That email already has an account.")
    else:
        print("Usage: python auth.py add <email> \"<display name>\" <password>")
