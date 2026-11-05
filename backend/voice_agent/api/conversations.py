import base64
from typing import Annotated, Any, Literal, NoReturn
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, StringConstraints

from voice_agent.conversation.records import (
    Conversation,
    ConversationDetail,
    ConversationSummary,
    EndReason,
    Message,
)
from voice_agent.conversation.turns import (
    ConversationEnded,
    ConversationNotFound,
    NoSpeech,
    TurnError,
    TurnInProgress,
    TurnResult,
)
from voice_agent.services import ServicesDep, TurnsDep
from voice_agent.speech.audio import InvalidAudio, max_wav_bytes
from voice_agent.speech.ports import AudioClip

router = APIRouter(prefix="/conversations", tags=["conversations"])

WAV_MEDIA_TYPES = {"audio/wav", "audio/x-wav", "audio/wave"}


class Audio(BaseModel):
    media_type: Literal["audio/wav"] = "audio/wav"
    wav_base64: str
    duration_ms: int


class StartResponse(BaseModel):
    conversation: Conversation
    greeting: Message
    audio: Audio | None


class TurnResponse(BaseModel):
    user_message: Message
    assistant_message: Message
    audio: Audio | None


class TextTurnRequest(BaseModel):
    text: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
    ]
    via: Literal["keyboard", "keypad"] = "keyboard"


class EndRequest(BaseModel):
    reason: EndReason = "hangup"


class ErrorDetail(BaseModel):
    code: str
    message: str


def _audio(clip: AudioClip | None) -> Audio | None:
    if clip is None:
        return None
    return Audio(
        wav_base64=base64.b64encode(clip.wav).decode(), duration_ms=clip.duration_ms
    )


def _turn_response(result: TurnResult) -> TurnResponse:
    return TurnResponse(
        user_message=result.user_message,
        assistant_message=result.assistant_message,
        audio=_audio(result.audio),
    )


def _fail(status_code: int, code: str, message: str) -> NoReturn:
    raise HTTPException(
        status_code, ErrorDetail(code=code, message=message).model_dump()
    )


def _turn_errors(error: TurnError | InvalidAudio) -> NoReturn:
    match error:
        case ConversationNotFound():
            _fail(status.HTTP_404_NOT_FOUND, "not_found", "No such conversation.")
        case ConversationEnded():
            _fail(status.HTTP_409_CONFLICT, "conversation_ended", "The call has ended.")
        case TurnInProgress():
            _fail(
                status.HTTP_409_CONFLICT,
                "turn_in_progress",
                "The previous message is still being answered.",
            )
        case NoSpeech():
            _fail(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "no_speech",
                "Sorry, I didn't catch that.",
            )
        case InvalidAudio():
            _fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_audio", str(error))
        case _:
            raise error


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {"model": ErrorDetail},
    status.HTTP_409_CONFLICT: {"model": ErrorDetail},
}


@router.post("", status_code=status.HTTP_201_CREATED)
async def start_conversation(turns: TurnsDep) -> StartResponse:
    """Start a call: the conversation and its spoken greeting."""
    started = await turns.start()
    return StartResponse(
        conversation=started.conversation,
        greeting=started.greeting,
        audio=_audio(started.audio),
    )


@router.post(
    "/{conversation_id}/turns/voice",
    responses=ERROR_RESPONSES,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "audio/wav": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def voice_turn(
    conversation_id: UUID, request: Request, turns: TurnsDep, services: ServicesDep
) -> TurnResponse:
    """Answer a recording: WAV with 16 kHz mono 16-bit PCM."""
    media_type = request.headers.get("content-type", "").split(";")[0].strip()
    if media_type not in WAV_MEDIA_TYPES:
        _fail(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "invalid_audio",
            "Send the recording as audio/wav.",
        )
    limit = max_wav_bytes(services.settings.max_recording_s)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            _fail(
                status.HTTP_413_CONTENT_TOO_LARGE,
                "invalid_audio",
                "The recording is too long.",
            )
    try:
        return _turn_response(await turns.voice_turn(conversation_id, bytes(body)))
    except (TurnError, InvalidAudio) as error:
        _turn_errors(error)


@router.post("/{conversation_id}/turns/text", responses=ERROR_RESPONSES)
async def text_turn(
    conversation_id: UUID, turn: TextTurnRequest, turns: TurnsDep
) -> TurnResponse:
    """Answer a typed message or digits entered on the keypad."""
    try:
        return _turn_response(
            await turns.text_turn(conversation_id, turn.text, turn.via)
        )
    except (TurnError, InvalidAudio) as error:
        _turn_errors(error)


@router.post(
    "/{conversation_id}/end",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=ERROR_RESPONSES,
)
async def end_conversation(
    conversation_id: UUID, turns: TurnsDep, end: EndRequest | None = None
) -> None:
    """Hang up. Waits for a running turn; ending twice changes nothing."""
    try:
        await turns.end(conversation_id, (end or EndRequest()).reason)
    except (TurnError, InvalidAudio) as error:
        _turn_errors(error)


@router.get("")
async def list_conversations(
    services: ServicesDep, limit: Annotated[int, Query(ge=1, le=100)] = 20
) -> list[ConversationSummary]:
    return await services.repository.list_conversations(limit)


@router.get("/{conversation_id}", responses=ERROR_RESPONSES)
async def get_conversation(
    conversation_id: UUID, services: ServicesDep
) -> ConversationDetail:
    detail = await services.repository.get_detail(conversation_id)
    if detail is None:
        _fail(status.HTTP_404_NOT_FOUND, "not_found", "No such conversation.")
    return detail
