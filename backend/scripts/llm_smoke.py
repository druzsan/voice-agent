"""Ask the configured language model one question and show what came back.

    uv run python -m scripts.llm_smoke ["your question"]

Uses the same settings as the app (environment and the repository's .env),
so it checks the provider, model ID and API key without the UI.
"""

import asyncio
import sys
import time

from voice_agent.agent.deps import CallDeps
from voice_agent.agent.state import CallState
from voice_agent.config import Settings
from voice_agent.crm.memory import InMemoryCrm
from voice_agent.services import build_responder, carrie_settings


async def main(question: str) -> int:
    settings = Settings()
    print(f"Provider: {settings.llm_provider}, model: {settings.llm_model}")
    responder = build_responder(settings)
    if not responder.configured:
        print("The language model is not configured; see the warnings above.")
        return 1
    start = time.perf_counter()
    # Carrie with the starting data in memory: no database needed
    deps = CallDeps(
        state=CallState(),
        crm=InMemoryCrm.seeded(),
        settings=carrie_settings(settings),
        conversation_id=None,
    )
    reply = await responder.reply([], question, deps)
    elapsed = time.perf_counter() - start
    print(f"Reply ({reply.source}, {elapsed:.2f} s): {reply.text}")
    print(f"Usage: {reply.usage}")
    return 0 if reply.source == "llm" else 1


if __name__ == "__main__":
    question = " ".join(sys.argv[1:]) or "Hi, what can you help me with?"
    sys.exit(asyncio.run(main(question)))
