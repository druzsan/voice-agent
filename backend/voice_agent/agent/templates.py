"""Fixed wording Carrie speaks without the model, per language.

The greeting, emergency guidance and fallbacks must be right every time,
so they don't depend on a model run.
"""

GREETING = "Hello, this is Carrie, your digital customer care assistant. How can I help you today?"

_TEMPLATES: dict[str, dict[str, str]] = {
    # Approved safety guidance for smoke, fire, sparks, burning smell or heat
    # (delivery spec §5, charging spec §3.1). The caller's location isn't
    # known, so no country-specific number.
    "emergency": {
        "en": (
            "Please move away from the vehicle and any charging equipment right now, "
            "and warn others to keep away without going near it yourself. "
            "Don't touch the vehicle, the cable or the charger. "
            "From a safe place, call the local emergency services."
        ),
        "de": (
            "Gehen Sie bitte sofort auf Abstand zum Fahrzeug und zur Ladeeinrichtung "
            "und warnen Sie andere, ohne sich selbst zu nähern. "
            "Berühren Sie weder Fahrzeug noch Kabel oder Ladesäule. "
            "Rufen Sie von einem sicheren Ort aus den örtlichen Notruf."
        ),
    },
    # A model reply that broke a commitment rule, in its place
    "withheld": {
        "en": "I can't promise that myself; the responsible team decides on it.",
        "de": "Das kann ich Ihnen nicht selbst zusagen; darüber entscheidet das zuständige Team.",
    },
    "safety_unconfirmed": {
        "en": "I can't confirm from here that it's safe.",
        "de": "Ich kann von hier aus nicht bestätigen, dass das sicher ist.",
    },
    "llm_failed": {
        "en": "Sorry, I couldn't answer that just now. Could you say it again?",
        "de": "Entschuldigung, das konnte ich gerade nicht beantworten. Können Sie es bitte noch einmal sagen?",
    },
    "not_configured": {
        "en": "I'm sorry, I can't answer right now because of a technical problem.",
        "de": "Es tut mir leid, wegen eines technischen Problems kann ich gerade nicht antworten.",
    },
    # The caller picked the call up again after being on hold
    "resumed": {
        "en": "I'm back with you. How else can I help?",
        "de": "Ich bin wieder für Sie da. Wie kann ich Ihnen noch helfen?",
    },
}


def template(name: str, language: str) -> str:
    texts = _TEMPLATES[name]
    return texts.get(language, texts["en"])
