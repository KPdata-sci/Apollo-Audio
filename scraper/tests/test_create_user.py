from unittest.mock import patch

import psycopg

from app import create_user


@patch("app.create_user.insert_user", return_value=7)
@patch("app.create_user.getpass.getpass", side_effect=["a long enough password", "a long enough password"])
def test_run_hashes_the_password_before_storing_it(mock_getpass, mock_insert_user, capsys):
    exit_code = create_user.run("kieran")

    assert exit_code == 0
    assert mock_insert_user.call_count == 1
    stored_username, stored_hash = mock_insert_user.call_args.args
    assert stored_username == "kieran"
    # Never the plaintext, and never even readable as one of our own inputs.
    assert stored_hash != "a long enough password"
    assert "a long enough password" not in stored_hash
    assert "a long enough password" not in capsys.readouterr().out


@patch("app.create_user.getpass.getpass", side_effect=["short", "short"])
def test_run_rejects_a_too_short_password(mock_getpass):
    exit_code = create_user.run("kieran")

    assert exit_code == 1


@patch("app.create_user.getpass.getpass", side_effect=["a long enough password", "a different password"])
def test_run_rejects_mismatched_confirmation(mock_getpass):
    exit_code = create_user.run("kieran")

    assert exit_code == 1


@patch("app.create_user.insert_user")
@patch("app.create_user.getpass.getpass", side_effect=["a long enough password", "a long enough password"])
def test_run_reports_a_duplicate_username_clearly(mock_getpass, mock_insert_user):
    mock_insert_user.side_effect = psycopg.errors.UniqueViolation()

    exit_code = create_user.run("kieran")

    assert exit_code == 1
