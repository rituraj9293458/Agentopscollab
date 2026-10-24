import os

from raceproof.config import Settings
from raceproof.tracing import configure_langsmith, safe_trace_inputs


def test_langsmith_configuration_is_opt_in(monkeypatch) -> None:
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGSMITH_TRACING_V2", raising=False)
    settings = Settings(
        _env_file=None,
        LANGSMITH_API_KEY="trace-secret",
        LANGSMITH_TRACING=False,
    )
    assert configure_langsmith(settings) is False
    assert os.environ["LANGSMITH_TRACING"] == "false"
    assert os.environ["LANGSMITH_TRACING_V2"] == "false"


def test_langsmith_configuration_exports_validated_settings(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        LANGSMITH_API_KEY="trace-secret",
        LANGSMITH_TRACING=True,
        LANGSMITH_PROJECT="raceproof-tests",
    )
    assert configure_langsmith(settings) is True
    assert os.environ["LANGSMITH_API_KEY"] == "trace-secret"
    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert os.environ["LANGSMITH_TRACING_V2"] == "true"
    assert os.environ["LANGSMITH_PROJECT"] == "raceproof-tests"


def test_trace_serialization_redacts_credentials(monkeypatch) -> None:
    monkeypatch.setenv("LANGSMITH_API_KEY", "trace-secret")
    payload = safe_trace_inputs(
        {
            "api_key": "another-secret",
            "database_url": "postgresql+psycopg://user:password@localhost:5432/db",
            "message": "LangSmith key trace-secret",
        }
    )
    assert payload["api_key"] == "[REDACTED]"
    assert payload["database_url"] == "[REDACTED]"
    assert "trace-secret" not in payload["message"]
