import base64
from dataclasses import replace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from tests.fakes import FakeRecognizer, FakeSynthesizer, wav_of_silence
from voice_agent.agent.carrie import build_agent
from voice_agent.agent.templates import GREETING, template
from voice_agent.llm.responder import Responder
from voice_agent.main import create_app
from voice_agent.services import Services

LLM_FAILED = template("llm_failed", "en")


def start(client: TestClient) -> str:
    response = client.post("/api/conversations")
    assert response.status_code == 201
    conversation_id: str = response.json()["conversation"]["id"]
    return conversation_id


def say(
    client: TestClient, conversation_id: str, text: str, via: str = "keyboard"
) -> Any:
    return client.post(
        f"/api/conversations/{conversation_id}/turns/text",
        json={"text": text, "via": via},
    )


def speak(client: TestClient, conversation_id: str, wav: bytes) -> Any:
    return client.post(
        f"/api/conversations/{conversation_id}/turns/voice",
        content=wav,
        headers={"content-type": "audio/wav"},
    )


def messages(client: TestClient, conversation_id: str) -> list[dict[str, Any]]:
    detail: list[dict[str, Any]] = client.get(
        f"/api/conversations/{conversation_id}"
    ).json()["messages"]
    return detail


def test_start_greets_the_caller_out_loud(
    client: TestClient, synthesizer: FakeSynthesizer
) -> None:
    response = client.post("/api/conversations")

    assert response.status_code == 201
    body = response.json()
    assert body["conversation"]["llm_provider"] == "echo"
    assert body["conversation"]["stt_model"] == "small.en"
    assert body["greeting"]["text"] == GREETING
    assert body["greeting"]["source"] == "template"
    assert base64.b64decode(body["audio"]["wav_base64"]).startswith(b"RIFF")
    assert synthesizer.spoken == [GREETING]


def test_a_typed_message_is_answered_and_stored(client: TestClient) -> None:
    conversation_id = start(client)

    response = say(client, conversation_id, "  Hello there  ")

    assert response.status_code == 200
    body = response.json()
    assert body["user_message"]["text"] == "Hello there"
    assert body["user_message"]["source"] == "keyboard"
    assert body["assistant_message"]["text"] == "You said: Hello there"
    assert body["assistant_message"]["source"] == "llm"
    assert set(body["assistant_message"]["timings_ms"]) == {"llm", "tts", "total"}
    assert body["audio"]["duration_ms"] == 100
    assert [m["text"] for m in messages(client, conversation_id)] == [
        GREETING,
        "Hello there",
        "You said: Hello there",
    ]


def test_keypad_digits_are_stored_as_keypad_input(client: TestClient) -> None:
    conversation_id = start(client)

    response = say(client, conversation_id, "4711#", via="keypad")

    assert response.json()["user_message"]["source"] == "keypad"


def test_a_recording_is_transcribed_and_answered(
    client: TestClient, recognizer: FakeRecognizer
) -> None:
    conversation_id = start(client)

    response = speak(client, conversation_id, wav_of_silence(1.5))

    assert response.status_code == 200
    body = response.json()
    assert body["user_message"]["text"] == "What time is it?"
    assert body["user_message"]["source"] == "voice"
    assert body["user_message"]["stt"]["audio_ms"] == 1500
    assert set(body["user_message"]["timings_ms"]) == {"stt"}
    assert body["assistant_message"]["text"] == "You said: What time is it?"
    assert len(recognizer.heard[0]) == 24_000


def test_nothing_heard_stores_nothing(
    client: TestClient, recognizer: FakeRecognizer
) -> None:
    conversation_id = start(client)
    recognizer.text = ""

    response = speak(client, conversation_id, wav_of_silence())

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "no_speech"
    assert len(messages(client, conversation_id)) == 1


def test_likely_invented_words_count_as_nothing_heard(
    client: TestClient, recognizer: FakeRecognizer
) -> None:
    conversation_id = start(client)
    recognizer.text = "Thank you."
    recognizer.no_speech_prob = 0.9
    recognizer.avg_logprob = -1.4

    response = speak(client, conversation_id, wav_of_silence())

    assert response.json()["detail"]["code"] == "no_speech"


@pytest.mark.parametrize(
    ("wav", "content_type", "status_code"),
    [
        (wav_of_silence(), "audio/webm", 415),
        (b"not a wav file", "audio/wav", 422),
        (wav_of_silence(1, sample_rate=48_000), "audio/wav", 422),
        (wav_of_silence(0.1), "audio/wav", 422),
        (wav_of_silence(6), "audio/wav", 413),
    ],
    ids=["webm", "garbage", "48-khz", "too-short", "too-long"],
)
def test_rejects_unusable_recordings(
    client: TestClient, wav: bytes, content_type: str, status_code: int
) -> None:
    conversation_id = start(client)

    response = client.post(
        f"/api/conversations/{conversation_id}/turns/voice",
        content=wav,
        headers={"content-type": content_type},
    )

    assert response.status_code == status_code
    assert response.json()["detail"]["code"] == "invalid_audio"


def test_after_hanging_up_no_more_turns(client: TestClient) -> None:
    conversation_id = start(client)

    assert client.post(f"/api/conversations/{conversation_id}/end").status_code == 204
    # Ending again changes nothing, e.g. when the page closes after hanging up
    ended_again = client.post(
        f"/api/conversations/{conversation_id}/end", json={"reason": "page_closed"}
    )
    response = say(client, conversation_id, "Hello?")

    assert ended_again.status_code == 204
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "conversation_ended"
    detail = client.get(f"/api/conversations/{conversation_id}").json()
    assert detail["end_reason"] == "hangup"
    assert detail["ended_at"] is not None


def test_unknown_conversations_are_not_found(client: TestClient) -> None:
    unknown = "0190a000-0000-7000-8000-000000000000"

    assert say(client, unknown, "Hi").status_code == 404
    assert client.post(f"/api/conversations/{unknown}/end").status_code == 404
    assert client.get(f"/api/conversations/{unknown}").status_code == 404


def client_with_model(services: Services, model: FunctionModel) -> TestClient:
    return TestClient(
        create_app(
            services=replace(services, responder=Responder(build_agent(model), 5, 100))
        )
    )


def test_a_failing_model_gets_a_fixed_reply(services: Services) -> None:
    def broken(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise RuntimeError("provider down")

    with client_with_model(services, FunctionModel(broken)) as client:
        body = say(client, start(client), "Hello").json()

    assert body["assistant_message"]["text"] == LLM_FAILED
    assert body["assistant_message"]["source"] == "template"
    assert body["assistant_message"]["llm_usage"] is None


def test_the_model_gets_the_earlier_turns_but_not_the_greeting(
    services: Services,
) -> None:
    calls: list[list[ModelMessage]] = []

    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(messages)
        return ModelResponse(parts=[TextPart(f"Answer {len(calls)}")])

    with client_with_model(services, FunctionModel(answer)) as client:
        conversation_id = start(client)
        say(client, conversation_id, "First")
        say(client, conversation_id, "Second")

    texts = [
        part.content
        for message in calls[1]
        for part in message.parts
        if isinstance(part, UserPromptPart | TextPart)
    ]
    assert texts == ["First", "Answer 1", "Second"]


def test_without_speech_the_reply_is_still_shown(
    client: TestClient, synthesizer: FakeSynthesizer
) -> None:
    conversation_id = start(client)
    synthesizer.fail = True

    body = say(client, conversation_id, "Hello").json()

    assert body["audio"] is None
    assert body["assistant_message"]["text"] == "You said: Hello"


def test_the_list_shows_the_newest_conversation_first(client: TestClient) -> None:
    first = start(client)
    second = start(client)
    say(client, second, "Hello")

    listed = client.get("/api/conversations").json()

    assert [(c["id"], c["message_count"]) for c in listed] == [(second, 3), (first, 1)]


def test_push_to_talk_turns_store_what_their_models_consumed(
    client: TestClient,
) -> None:

    conversation = client.post("/api/conversations").json()
    greeting = conversation["greeting"]
    assert [u["service"] for u in greeting["usage"]] == ["tts"]

    body = client.post(
        f"/api/conversations/{conversation['conversation']['id']}/turns/voice",
        content=wav_of_silence(1.5),
        headers={"content-type": "audio/wav"},
    ).json()

    assert [u["service"] for u in body["user_message"]["usage"]] == ["stt"]
    answer = body["assistant_message"]["usage"]
    assert [u["service"] for u in answer] == ["llm", "tts"]
    assert all(u["duration_ms"] >= 0 for u in answer)


def test_feedback_on_a_call_is_stored_and_can_be_changed(client: TestClient) -> None:
    conversation_id = start(client)

    first = client.put(
        f"/api/conversations/{conversation_id}/feedback",
        json={"rating": "down", "comment": "  Too slow.  "},
    )
    second = client.put(
        f"/api/conversations/{conversation_id}/feedback", json={"rating": "up"}
    )
    listed = client.get("/api/conversations").json()[0]

    assert first.status_code == 200
    assert (first.json()["feedback_rating"], first.json()["feedback_comment"]) == (
        "down",
        "Too slow.",
    )
    assert (listed["feedback_rating"], listed["feedback_comment"]) == ("up", None)
    assert listed["feedback_at"] is not None
    assert second.json()["id"] == conversation_id


def test_feedback_needs_a_known_call_and_a_rating(client: TestClient) -> None:
    unknown = client.put(
        "/api/conversations/01a1abe9-c983-7fcf-820e-1f2f8c65a057/feedback",
        json={"rating": "up"},
    )
    conversation_id = start(client)
    invalid = client.put(
        f"/api/conversations/{conversation_id}/feedback", json={"rating": "meh"}
    )

    assert unknown.status_code == 404
    assert invalid.status_code == 422
