import pytest

from voice_agent.config import Settings


def load() -> Settings:
    return Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


def test_keys_have_their_conventional_names_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "conventional")
    monkeypatch.setenv("REQUESTY_API_KEY", "conventional")
    monkeypatch.setenv("VOICE_AGENT_REQUESTY_API_KEY", "prefixed")

    settings = load()

    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "conventional"
    # The app's own name wins
    assert settings.requesty_api_key is not None
    assert settings.requesty_api_key.get_secret_value() == "prefixed"


def test_empty_values_count_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICE_AGENT_LLM_MODEL", "")

    assert load().llm_model is None


def test_secrets_stay_out_of_the_representation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VOICE_AGENT_OPENAI_API_KEY", "sk-very-secret")

    assert "sk-very-secret" not in repr(load())
