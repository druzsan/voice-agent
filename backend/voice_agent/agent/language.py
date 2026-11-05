"""The languages Carrie can hold a conversation in."""

from voice_agent.config import Settings

_NAMES = {
    "en": "English",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "nl": "Dutch",
    "pl": "Polish",
    "tr": "Turkish",
    "ru": "Russian",
    "uk": "Ukrainian",
    "ar": "Arabic",
    "pt": "Portuguese",
    "cs": "Czech",
    "ro": "Romanian",
    "el": "Greek",
    "zh": "Chinese",
}


def language_name(code: str) -> str:
    return _NAMES.get(code, code)


def supported_languages(settings: Settings) -> tuple[str, ...]:
    """English always; German when both speech models are OpenAI's.

    The local models are English-only: Whisper's .en models and the English
    Piper voice.
    """
    if settings.stt_provider == "openai" and settings.tts_provider == "openai":
        return ("en", "de")
    return ("en",)
