"""The messages of a live call (WS /api/call), mirrored by hand in
frontend/src/api/callProtocol.ts.

Besides these JSON messages, the browser sends the microphone as binary
frames: 16 kHz mono PCM16, little-endian.
"""

from dataclasses import dataclass
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, TypeAdapter

from voice_agent.conversation.records import EndReason, Source

# Largest accepted binary frame (about 2 s of audio)
MAX_AUDIO_FRAME_BYTES = 64 * 1024

CallState = Literal["listening", "thinking", "speaking"]


# --- Browser to server ---------------------------------------------------------


@dataclass(frozen=True)
class AudioFrame:
    """A piece of the microphone stream (a binary frame)."""

    pcm: bytes


class TextInput(BaseModel):
    """Typed text or keypad digits."""

    type: Literal["text"]
    text: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
    ]
    via: Literal["keyboard", "keypad"] = "keyboard"


class Played(BaseModel):
    """A clip played to the end (or nearly: at least 90 % of it)."""

    type: Literal["played"]
    clip: int


class Mute(BaseModel):
    """The caller muted or unmuted the microphone.

    Muting drops a partly heard utterance; no binary frames follow until
    the caller unmutes.
    """

    type: Literal["mute"]
    muted: bool


class Hangup(BaseModel):
    type: Literal["hangup"]


ClientMessage = Annotated[
    TextInput | Played | Mute | Hangup, Field(discriminator="type")
]
CLIENT_MESSAGE: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)

ClientEvent = AudioFrame | TextInput | Played | Mute | Hangup


# --- Server to browser ---------------------------------------------------------


class CallStarted(BaseModel):
    """The first message of every call."""

    type: Literal["call_started"] = "call_started"
    conversation_id: UUID


class StateChanged(BaseModel):
    type: Literal["state"] = "state"
    state: CallState


class CallerSpeech(BaseModel):
    """The caller started or stopped talking (as the voice detection hears it)."""

    type: Literal["caller_speech"] = "caller_speech"
    active: bool


class UserMessage(BaseModel):
    """The caller's stored message."""

    type: Literal["user_message"] = "user_message"
    id: int
    text: str
    source: Source


class AssistantDelta(BaseModel):
    """More text of the reply in turn `turn`, as the model writes it."""

    type: Literal["assistant_delta"] = "assistant_delta"
    turn: int
    text: str


class AudioClip(BaseModel):
    """One spoken sentence of turn `turn`; clips play in order of `clip`."""

    type: Literal["audio"] = "audio"
    clip: int
    turn: int
    text: str
    duration_ms: int
    wav_base64: str


class AssistantMessage(BaseModel):
    """The stored reply, once it has played, or was interrupted."""

    type: Literal["assistant_message"] = "assistant_message"
    id: int
    turn: int
    text: str
    source: Source
    interrupted: bool


class Interrupted(BaseModel):
    """The caller talked over the reply: stop playing, drop queued clips."""

    type: Literal["interrupted"] = "interrupted"
    turn: int


class TurnDone(BaseModel):
    type: Literal["turn_done"] = "turn_done"
    turn: int
    timings_ms: dict[str, int]


ErrorCode = Literal["invalid_message", "stt_failed", "busy"]


class CallError(BaseModel):
    """Something went wrong, but the call goes on."""

    type: Literal["error"] = "error"
    code: ErrorCode
    message: str


class CallEnded(BaseModel):
    """The last message before the server closes the connection."""

    type: Literal["call_ended"] = "call_ended"
    reason: EndReason


ServerMessage = (
    CallStarted
    | StateChanged
    | CallerSpeech
    | UserMessage
    | AssistantDelta
    | AudioClip
    | AssistantMessage
    | Interrupted
    | TurnDone
    | CallError
    | CallEnded
)
