"""Carrie: one agent, one set of instructions, six tools."""

from pathlib import Path

from pydantic_ai import Agent, RunContext
from pydantic_ai.models import Model

from voice_agent.agent.deps import CallDeps
from voice_agent.agent.state import describe
from voice_agent.agent.tools import TOOLS

PROMPTS = Path(__file__).parent / "prompts"
# The fixed part first, so providers can cache it; the call's state follows
INSTRUCTIONS = "\n\n".join(
    (PROMPTS / f"{name}.md").read_text(encoding="utf-8").strip()
    for name in (
        "core",
        "delivery",
        "charging",
        "connected_services",
        "warranty",
        "examples",
    )
)


def current_call(ctx: RunContext[CallDeps]) -> str:
    deps = ctx.deps
    return describe(deps.state, deps.now(), deps.settings.supported_languages)


def build_agent(model: Model) -> Agent[CallDeps, str]:
    return Agent(
        model,
        deps_type=CallDeps,
        output_type=str,
        instructions=[INSTRUCTIONS, current_call],
        tools=TOOLS,
        # A tool may ask the model to correct its arguments twice
        retries=2,
        name="carrie",
    )
