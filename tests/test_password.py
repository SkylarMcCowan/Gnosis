"""Regression tests for /password (generate_password/password_command, webagent.py:4474-4484)."""
import string

import webagent


def test_generate_password_default_length_and_charset():
    pwd = webagent.generate_password()
    assert len(pwd) == 20
    assert all(c in string.ascii_letters + string.digits + string.punctuation for c in pwd)


def test_password_command_default_count(capsys):
    webagent.password_command()
    lines = [l for l in capsys.readouterr().out.splitlines() if l.strip()]
    assert len(lines) == 5


def test_password_command_respects_dash_n_count(capsys):
    webagent.password_command("-3")
    lines = [l for l in capsys.readouterr().out.splitlines() if l.strip()]
    assert len(lines) == 3


def test_password_command_ignores_malformed_count(capsys):
    webagent.password_command("not-a-number")
    lines = [l for l in capsys.readouterr().out.splitlines() if l.strip()]
    assert len(lines) == 5
