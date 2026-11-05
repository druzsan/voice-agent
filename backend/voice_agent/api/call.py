"""WS /api/call: a live call. Connecting starts it, disconnecting ends it."""

import logging
from urllib.parse import urlsplit

import anyio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError

from voice_agent.conversation.call_session import Disconnected
from voice_agent.conversation.protocol import (
    CLIENT_MESSAGE,
    MAX_AUDIO_FRAME_BYTES,
    AudioFrame,
    CallError,
    ClientEvent,
    ServerMessage,
)
from voice_agent.services import Services

logger = logging.getLogger(__name__)

router = APIRouter(tags=["call"])


class WebSocketTransport:
    """The call's messages over a WebSocket: JSON text frames and binary audio."""

    def __init__(self, websocket: WebSocket) -> None:
        self._websocket = websocket
        # The session sends from more than one task
        self._sending = anyio.Lock()
        self._open = True

    async def receive(self) -> ClientEvent:
        while True:
            if not self._open:
                raise Disconnected
            try:
                frame = await self._websocket.receive()
            except (WebSocketDisconnect, RuntimeError):
                frame = {"type": "websocket.disconnect"}
            if frame["type"] == "websocket.disconnect":
                self._open = False
                raise Disconnected
            data = frame.get("bytes")
            if isinstance(data, bytes):
                if len(data) > MAX_AUDIO_FRAME_BYTES:
                    await self.close(status.WS_1009_MESSAGE_TOO_BIG)
                    raise Disconnected("error")
                return AudioFrame(data)
            try:
                return CLIENT_MESSAGE.validate_json(frame.get("text") or "")
            except ValidationError as error:
                await self.send(
                    CallError(
                        code="invalid_message",
                        message=f"Invalid message: {error.errors()[0]['msg']}",
                    )
                )

    async def send(self, message: ServerMessage) -> None:
        async with self._sending:
            if not self._open:
                return
            try:
                await self._websocket.send_text(message.model_dump_json())
            except (WebSocketDisconnect, RuntimeError, OSError):
                self._open = False

    async def close(self, code: int = status.WS_1000_NORMAL_CLOSURE) -> None:
        async with self._sending:
            if not self._open:
                return
            self._open = False
            try:
                await self._websocket.close(code)
            except (WebSocketDisconnect, RuntimeError, OSError):
                pass


def _same_origin(websocket: WebSocket) -> bool:
    """Whether the page that connects comes from this app.

    Browsers always send the Origin of a WebSocket, so this stops other
    sites from placing calls; clients without one (scripts) aren't browsers.
    nginx and Vite pass the original Host on.
    """
    origin = websocket.headers.get("origin")
    if origin is None:
        return True
    return urlsplit(origin).netloc == websocket.headers.get("host")


@router.websocket("/call")
async def call(websocket: WebSocket) -> None:
    if not _same_origin(websocket):
        logger.warning("Refused a call from %s", websocket.headers.get("origin"))
        # Before accepting, this answers the handshake with 403
        await websocket.close(status.WS_1008_POLICY_VIOLATION)
        return
    services: Services = websocket.app.state.services
    await websocket.accept()
    transport = WebSocketTransport(websocket)
    session = services.call(transport)
    try:
        await session.start()
    except Exception:
        logger.exception("Couldn't start a call")
        await transport.close(status.WS_1011_INTERNAL_ERROR)
        return
    await session.run()
    await transport.close()
