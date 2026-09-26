import logging
import secrets
import time

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError

from .settings import settings

logger = logging.getLogger("apollo.auth")

# Argon2id (argon2-cffi's default profile) — OWASP's current top recommendation
# for password storage. Salting is automatic and per-hash: the encoded string
# PasswordHasher produces embeds algorithm parameters + a random salt + the
# hash together (standard PHC format), so there's no separate salt column to
# manage — that's normal for this style of library, not a corner cut.
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (Argon2Error, InvalidHashError):
        # Argon2Error covers a genuine mismatch (VerifyMismatchError) and
        # other verification failures; InvalidHashError (oddly, a ValueError
        # subclass rather than an Argon2Error one) covers password_hash not
        # even being well-formed Argon2 output. Either way, it doesn't verify.
        return False


# JWT signing secret. A blank APOLLO_JWT_SECRET (the default) gets a random
# one generated here at process start rather than refusing to run — fine for
# a quick local `docker compose up`, wrong for anything meant to (a) survive
# a restart, since every previously-issued token stops verifying, or (b) run
# more than one replica of, since each process would mint its own secret and
# reject tokens issued by the others. JWT_SECRET_IS_EPHEMERAL lets main.py's
# startup log a warning about that, same pattern as the existing
# APOLLO_API_KEY warning.
JWT_SECRET_IS_EPHEMERAL = not settings.jwt_secret
_JWT_SECRET = settings.jwt_secret or secrets.token_hex(32)
_JWT_ALGORITHM = "HS256"


def create_access_token(user_id: int, username: str) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "username": username,
        "iat": now,
        "exp": now + settings.jwt_expire_days * 86400,
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    """Returns {"id": int, "username": str} for a valid, unexpired token —
    None for anything else (expired, tampered, wrong secret, malformed).
    Never raises: every caller treats "not a valid token" as one outcome,
    not a set of exceptions to enumerate."""
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
        return {"id": int(payload["sub"]), "username": payload["username"]}
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
