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

    assert load().llm_model == "azure/gpt-6.1-sol@germanywestcentral"


def test_the_default_model_is_reached_through_the_eu_router() -> None:
    settings = load()

    assert settings.llm_provider == "requesty"
    assert settings.requesty_base_url == "https://router.eu.requesty.ai/v1"


def test_secrets_stay_out_of_the_representation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VOICE_AGENT_OPENAI_API_KEY", "sk-very-secret")

    assert "sk-very-secret" not in repr(load())


def test_openai_speech_is_named_after_its_models() -> None:
    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        stt_provider="openai",
        tts_provider="openai",
    )

    assert settings.stt_name() == "openai/gpt-4o-mini-transcribe"
    assert settings.stt_name(live=True) == "openai/gpt-live-transcribe"
    assert settings.tts_name() == "openai/gpt-4o-mini-tts/marin"
    assert settings.openai_tts_speed == 1.25
    # Without live transcription, calls transcribe each utterance as a file
    no_live = settings.model_copy(update={"openai_stt_live": False})
    assert no_live.stt_name(live=True) == "openai/gpt-4o-mini-transcribe"
    assert not no_live.uses_live_stt


def test_local_speech_is_named_after_the_model_and_voice() -> None:
    settings = load()

    assert settings.stt_name(live=True) == "small.en"
    assert settings.tts_name() == "en_US-lessac-medium"
