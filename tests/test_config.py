from pathlib import Path

import pytest

from tearsheet.config import get_settings


def test_default_home_is_dot_tearsheet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEARSHEET_HOME", raising=False)
    assert get_settings().home == Path.home() / ".tearsheet"


def test_home_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TEARSHEET_HOME", str(tmp_path / "elsewhere"))
    assert get_settings().home == tmp_path / "elsewhere"


def test_default_user_agent_identifies_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEARSHEET_UA", raising=False)
    assert "tearsheet" in get_settings().user_agent


def test_user_agent_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEARSHEET_UA", "MyBot/1.0")
    assert get_settings().user_agent == "MyBot/1.0"


def test_default_page_ttl_is_seven_days(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEARSHEET_TTL", raising=False)
    assert get_settings().page_ttl_seconds == 7 * 24 * 3600


def test_ttl_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEARSHEET_TTL", "3600")
    assert get_settings().page_ttl_seconds == 3600


def test_fetch_limits_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    assert s.max_response_bytes == 5 * 1024 * 1024
    assert s.timeout_seconds == 20.0
    assert s.robots_ttl_seconds == 24 * 3600
