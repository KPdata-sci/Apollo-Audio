"""Creates a login account. There is no public signup endpoint (see
CLAUDE.md's Authentication section for why) — this is the only way a user
gets created.

Run locally (docker-compose):
    docker compose exec api python -m app.create_user <username>

Run in Kubernetes:
    kubectl exec -n apollo -it deployment/api -- python -m app.create_user <username>

Prompts for the password (not read from an argument or env var, so it never
ends up in shell history or a process list) and hashes it with Argon2id
(app/auth.py) before it ever reaches the database.
"""
import argparse
import getpass
import logging
import sys

import psycopg

from .auth import hash_password
from .logging_config import configure_logging
from .warehouse import insert_user

configure_logging()
logger = logging.getLogger("apollo.create_user")

_MIN_PASSWORD_LENGTH = 8


def run(username: str) -> int:
    password = getpass.getpass("Password: ")
    if len(password) < _MIN_PASSWORD_LENGTH:
        print(f"Password must be at least {_MIN_PASSWORD_LENGTH} characters.", file=sys.stderr)
        return 1
    if password != getpass.getpass("Confirm password: "):
        print("Passwords didn't match.", file=sys.stderr)
        return 1

    try:
        user_id = insert_user(username, hash_password(password))
    except psycopg.errors.UniqueViolation:
        print(f"Username {username!r} is already taken.", file=sys.stderr)
        return 1

    print(f"Created user {username!r} (id={user_id}).")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username")
    args = parser.parse_args()
    raise SystemExit(run(args.username))
