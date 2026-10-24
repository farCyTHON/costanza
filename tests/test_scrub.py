from __future__ import annotations

from costanza.scrub import redact


def test_github_token_redacted() -> None:
    token = "ghp_" + ("a" * 36)
    result = redact(f"use {token} please")
    assert token not in result.text
    assert "[REDACTED:github_token]" in result.text
    assert "github_token" in result.names


def test_private_key_block() -> None:
    result = redact("-----BEGIN RSA PRIVATE KEY-----\nMIIE")
    assert "BEGIN RSA PRIVATE KEY" not in result.text
    assert "private_key" in result.names


def test_url_credentials_password_only() -> None:
    result = redact("clone https://user:s3cretpass@github.com/x/y")
    assert "s3cretpass" not in result.text
    assert "https://user:[REDACTED:url_credentials]@" in result.text


def test_assignment_and_bearer() -> None:
    result = redact("password=hunter22 TOKEN")
    assert "hunter22" not in result.text
    assert "[REDACTED:assignment]" in result.text
    bearer = redact("Authorization: Bearer " + ("B" * 24))
    assert "B" * 24 not in bearer.text
    assert "bearer" in bearer.names


def test_high_entropy_near_keyword() -> None:
    blob = "sK9mP2qR7tL4nX8vB3wY6zA1"
    result = redact(f"api token {blob}")
    assert blob not in result.text
    assert "entropy" in result.names


def test_false_positive_prose_and_code() -> None:
    prose = "The secret is that we use SQLite, not Postgres."
    assert redact(prose).names == ()
    sha = "The commit key is a1b2c3d and the password hashing uses bcrypt."
    assert redact(sha).names == ()
    code = "def get_token():\n    return session.token\n"
    assert redact(code).names == ()
    hex_id = "synced: 9f8e7d6c5b4a321 2026-10-12"
    assert redact(hex_id).names == ()


def test_allow_list() -> None:
    token = "ghp_" + ("b" * 36)
    result = redact(f"keep {token}", allow=[token])
    assert token in result.text
    assert result.names == ()
