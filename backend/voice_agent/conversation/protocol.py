"""The messages of a live call (WS /api/call), mirrored by hand in
frontend/src/api/callProtocol.ts.

Besides these JSON messages, the browser sends the microphone as binary
frames: 16 kHz mono PCM16, little-endian.
"""

from dataclasses import dataclass
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, TypeAdapter

from voice_agent.conversation.records import EndReason, Source
from voice_agent.usage import Usage

# Largest accepted binary frame (about 2 s of audio)
MAX_AUDIO_FRAME_BYTES = 64 * 1024

# on_hold: transferred to a colleague; the call waits until the caller resumes
CallState = Literal["listening", "thinking", "speaking", "on_hold"]


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


class Resume(BaseModel):
    """The caller picks the call up again after being on hold."""

    type: Literal["resume"]


ClientMessage = Annotated[
    TextInput | Played | Mute | Hangup | Resume, Field(discriminator="type")
]
CLIENT_MESSAGE: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)

ClientEvent = AudioFrame | TextInput | Played | Mute | Hangup | Resume


# --- Server to browser ---------------------------------------------------------


class CallStarted(BaseModel):
    """The first message of every call."""

    type: Literal["call_started"] = "call_started"
    conversation_id: UUID
    caller_phone: str | None
    language: str
    supported_languages: list[str]


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


class AudioPiece(BaseModel):
    """More audio of a spoken sentence (clip) of turn `turn`.

    Clips play in order of `clip`, their pieces in the order they arrive.
    """

    type: Literal["audio"] = "audio"
    clip: int
    turn: int
    sample_rate: int
    # Mono 16-bit little-endian PCM
    pcm_base64: str


class AudioEnd(BaseModel):
    """The clip's last piece has been sent."""

    type: Literal["audio_end"] = "audio_end"
    clip: int
    turn: int
    text: str
    duration_ms: int


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
    # What the turn's model calls consumed, per service and model
    usage: list[Usage] = []


class ToolActivity(BaseModel):
    """Carrie used a tool in turn `turn`: looked something up or changed it."""

    type: Literal["tool"] = "tool"
    turn: int
    name: str
    status: Literal["ok", "refused", "failed"]
    label: str
    data: dict[str, Any] = {}


class LanguageChanged(BaseModel):
    """The conversation continues in another language."""

    type: Literal["language"] = "language"
    language: str


class UsageReport(BaseModel):
    """Consumption outside of a turn, e.g. recognizing speech that was noise."""

    type: Literal["usage"] = "usage"
    usage: list[Usage]


ErrorCode = Literal["invalid_message", "stt_failed", "busy", "on_hold"]


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
    | AudioPiece
    | AudioEnd
    | AssistantMessage
    | Interrupted
    | TurnDone
    | ToolActivity
    | LanguageChanged
    | UsageReport
    | CallError
    | CallEnded
)
