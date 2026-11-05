"""Carrie in a live call: tools, the reply check, safety guidance and the hold.

The model is scripted (FunctionModel), the customer care system is the
seeded in-memory one.
"""

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import replace

from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelMessage, ModelRequest, ToolReturnPart
from pydantic_ai.models.function import (
    AgentInfo,
    DeltaToolCall,
    DeltaToolCalls,
    FunctionModel,
)

from tests.fakes import InMemoryConversationRepository
from tests.integration.test_call import Caller
from voice_agent.agent.carrie import build_agent
from voice_agent.agent.templates import template
from voice_agent.config import Settings
from voice_agent.crm.memory import InMemoryCrm
from voice_agent.llm.responder import Responder
from voice_agent.main import create_app
from voice_agent.services import Services

Script = Callable[[list[ModelMessage]], list[str | DeltaToolCalls]]


def tool_call(name: str, **arguments: object) -> DeltaToolCalls:
    return {0: DeltaToolCall(name=name, json_args=json.dumps(arguments))}


def answered_tool(messages: list[ModelMessage]) -> bool:
    """Whether the model is called again after a tool ran."""
    last = messages[-1]
    return isinstance(last, ModelRequest) and any(
        isinstance(part, ToolReturnPart) for part in last.parts
    )


def client_with(services: Services, script: Script) -> TestClient:
    async def stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | DeltaToolCalls]:
        for piece in script(messages):
            yield piece

    responder = Responder(build_agent(FunctionModel(stream_function=stream)), 5, 200)
    return TestClient(create_app(services=replace(services, responder=responder)))


def transfer(messages: list[ModelMessage]) -> list[str | DeltaToolCalls]:
    if answered_tool(messages):
        return ["I'm connecting you with technical support now."]
    return [
        "I'll request the transfer now. ",
        tool_call(
            "handover_to_human",
            route="technical_support",
            reason="Caller asked for a person",
            summary="App sign-in fails since this morning.",
        ),
    ]


def test_a_transfer_puts_the_call_on_hold_until_the_caller_resumes(
    services: Services, crm: InMemoryCrm, repository: InMemoryConversationRepository
) -> None:
    with (
        client_with(services, transfer) as client,
        client.websocket_connect("/api/call?phone=0151%2022000302") as ws,
    ):
        caller = Caller(ws)
        started = caller.until("call_started")[-1]
        caller.until("state", state="listening")
        caller.say("I want to talk to a person.")
        turn = caller.until("state", state="on_hold")
        caller.say("Hello?")
        refused = caller.until("error")[-1]
        ws.send_json({"type": "resume"})
        resumed = caller.until("assistant_message")[-1]
        caller.hang_up()

    assert started["caller_phone"] == "+4915122000302"
    tool = next(m for m in turn if m["type"] == "tool")
    assert (tool["name"], tool["status"]) == ("handover_to_human", "ok")
    spoken = next(m for m in turn if m["type"] == "assistant_message")["text"]
    assert spoken == (
        "I'll request the transfer now. I'm connecting you with technical support now."
    )
    assert refused["code"] == "on_hold"
    assert resumed["text"] == template("resumed", "en")
    assert crm.handovers[0].route == "technical_support"
    # The turn's tool exchange is stored, for the history and the transcript
    reply = next(m for m in repository.messages if m.tool_calls)
    assert reply.model_messages is not None
    assert reply.tool_calls is not None
    assert reply.tool_calls[0]["name"] == "handover_to_human"


def test_danger_gets_safety_guidance_without_the_model(services: Services) -> None:
    def never(messages: list[ModelMessage]) -> list[str | DeltaToolCalls]:
        raise AssertionError("The model isn't asked")

    with (
        client_with(services, never) as client,
        client.websocket_connect("/api/call") as ws,
    ):
        caller = Caller(ws)
        caller.until("state", state="listening")
        caller.say("There's smoke coming out of the charging port!")
        reply = caller.until("assistant_message")[-1]
        caller.hang_up()

    assert reply["text"] == template("emergency", "en")
    assert reply["source"] == "template"


def test_unbacked_claims_are_left_out_and_commitments_withheld(
    services: Services,
) -> None:
    def overpromising(messages: list[ModelMessage]) -> list[str | DeltaToolCalls]:
        return [
            "I've created a ticket for you. ",
            "You'll get a rental car until the delivery. ",
            "Is there anything else?",
        ]

    with (
        client_with(services, overpromising) as client,
        client.websocket_connect("/api/call") as ws,
    ):
        caller = Caller(ws)
        caller.until("state", state="listening")
        caller.say("My delivery is late.")
        turn = caller.until("assistant_message")
        caller.hang_up()

    assert turn[-1]["text"] == (f"{template('withheld', 'en')} Is there anything else?")
    shown = "".join(m["text"] for m in turn if m["type"] == "assistant_delta")
    assert shown == turn[-1]["text"]


def test_a_language_switch_is_announced_to_the_browser(services: Services) -> None:
    def german(messages: list[ModelMessage]) -> list[str | DeltaToolCalls]:
        if answered_tool(messages):
            return ["Wie kann ich Ihnen helfen?"]
        return [tool_call("set_language", language="de")]

    with (
        client_with(replace(services, settings=_bilingual(services)), german) as client,
        client.websocket_connect("/api/call") as ws,
    ):
        caller = Caller(ws)
        caller.until("state", state="listening")
        caller.say("Guten Tag, sprechen Sie Deutsch?")
        turn = caller.until("assistant_message")
        caller.hang_up()

    assert {"type": "language", "language": "de"} in turn


def test_card_numbers_never_reach_the_transcript(
    client: TestClient, repository: InMemoryConversationRepository
) -> None:
    with client.websocket_connect("/api/call") as ws:
        caller = Caller(ws)
        caller.until("state", state="listening")
        caller.say("My card is 4111 1111 1111 1111")
        turn = caller.until("turn_done")
        caller.hang_up()

    user = next(m for m in turn if m["type"] == "user_message")
    assert "4111" not in user["text"]
    assert all("4111" not in m.text for m in repository.messages)


def _bilingual(services: Services) -> Settings:
    """Settings with OpenAI speech: German is supported."""
    return services.settings.model_copy(
        update={"stt_provider": "openai", "tts_provider": "openai"}
    )


def test_safety_guidance_is_in_the_language_of_the_report(services: Services) -> None:
    def never(messages: list[ModelMessage]) -> list[str | DeltaToolCalls]:
        raise AssertionError("The model isn't asked")

    with (
        client_with(replace(services, settings=_bilingual(services)), never) as client,
        client.websocket_connect("/api/call") as ws,
    ):
        caller = Caller(ws)
        caller.until("state", state="listening")
        caller.say("Aus dem Ladeanschluss kommt Rauch!")
        turn = caller.until("assistant_message")
        caller.hang_up()

    assert {"type": "language", "language": "de"} in turn
    assert turn[-1]["text"] == template("emergency", "de")
