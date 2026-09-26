import time
from unittest.mock import patch

import jwt

from app import auth


def test_hash_password_is_salted_and_not_the_plaintext():
    h1 = auth.hash_password("correct horse battery staple")
    h2 = auth.hash_password("correct horse battery staple")

    assert "correct horse battery staple" not in h1
    # Argon2id salts per-hash — the same password hashes differently every time.
    assert h1 != h2


def test_verify_password_round_trips():
    password_hash = auth.hash_password("correct horse battery staple")

    assert auth.verify_password("correct horse battery staple", password_hash) is True
    assert auth.verify_password("wrong password", password_hash) is False


def test_verify_password_rejects_garbage_hash_instead_of_raising():
    assert auth.verify_password("anything", "not-a-real-argon2-hash") is False


def test_create_and_decode_access_token_round_trips():
    token = auth.create_access_token(user_id=42, username="kieran")

    decoded = auth.decode_access_token(token)

    assert decoded == {"id": 42, "username": "kieran"}


def test_decode_access_token_rejects_garbage():
    assert auth.decode_access_token("not-a-real-token") is None
    assert auth.decode_access_token("") is None


def test_decode_access_token_rejects_a_token_signed_with_a_different_secret():
    forged = jwt.encode(
        {"sub": "1", "username": "kieran", "iat": int(time.time()), "exp": int(time.time()) + 3600},
        "some-other-secret-thats-at-least-32-bytes-long",
        algorithm="HS256",
    )

    assert auth.decode_access_token(forged) is None


def test_decode_access_token_rejects_an_expired_token():
    with patch("app.auth.settings.jwt_expire_days", -1):
        expired = auth.create_access_token(user_id=1, username="kieran")

    assert auth.decode_access_token(expired) is None
