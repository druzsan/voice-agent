"""A scripted live call: greeting, one turn, hang up.

    python -m scripts.call_smoke [URL] [--text TEXT | --speak WAV] [--expect TEXT]

The turn is typed text, or a recording (16 kHz mono 16-bit WAV) streamed in
real time like a microphone, followed by silence until the backend answers.
Prints the messages and the latency, and exits with an error when the call
doesn't go as expected. With the echo provider it needs no secrets, so CI
runs it against the running stack.
"""

import argparse
import asyncio
import json
import sys
import time
import wave
from pathlib import Path
from typing import Any

from websockets.asyncio.client import ClientConnection, connect

FRAME_BYTES = 1024  # 512 samples, 32 ms
FRAME_S = 0.032


class Call:
    def __init__(self, ws: ClientConnection) -> None:
        self.ws = ws
        self.first_audio_at: float | None = None

    async def next(self) -> dict[str, Any]:
        message: dict[str, Any] = json.loads(await asyncio.wait_for(self.ws.recv(), 60))
        if message["type"] == "audio":
            if self.first_audio_at is None:
                self.first_audio_at = time.perf_counter()
            # Played at once: the script doesn't listen
            await self.ws.send(json.dumps({"type": "played", "clip": message["clip"]}))
            message["wav_base64"] = f"<{message['duration_ms']} ms>"
        if message["type"] != "assistant_delta":
            print("<", json.dumps(message), flush=True)
        return message

    async def until(self, type_: str, **fields: object) -> list[dict[str, Any]]:
        seen: list[dict[str, Any]] = []
        while True:
            message = await self.next()
            seen.append(message)
            if message["type"] == type_ and all(
                message.get(key) == value for key, value in fields.items()
            ):
                return seen


async def speak(ws: ClientConnection, wav_file: Path, heard: asyncio.Event) -> float:
    """Streams the recording in real time, then silence until it's answered.

    Returns when the last frame of the recording was sent.
    """
    with wave.open(str(wav_file), "rb") as wav:
        if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (
            16000,
            1,
            2,
        ):
            raise SystemExit(f"{wav_file} isn't a 16 kHz mono 16-bit WAV")
        pcm = wav.readframes(wav.getnframes())
    start = time.perf_counter()
    frames = [pcm[i : i + FRAME_BYTES] for i in range(0, len(pcm), FRAME_BYTES)]
    for index, frame in enumerate(frames):
        await ws.send(frame)
        await asyncio.sleep(max(0, start + (index + 1) * FRAME_S - time.perf_counter()))
    ended = time.perf_counter()
    silence = bytes(FRAME_BYTES)
    for _ in range(round(10 / FRAME_S)):
        if heard.is_set():
            break
        await ws.send(silence)
        await asyncio.sleep(FRAME_S)
    return ended


async def main(url: str, text: str, wav_file: Path | None, expect: str | None) -> None:
    async with connect(url) as ws:
        call = Call(ws)
        started = await call.next()
        assert started["type"] == "call_started", started
        await call.until("state", state="listening")

        speech_ended: float | None = None
        if wav_file is None:
            print(">", text)
            await ws.send(json.dumps({"type": "text", "text": text}))
            sent = time.perf_counter()
            call.first_audio_at = None
            turn = await call.until("turn_done")
        else:
            print(">", wav_file)
            heard = asyncio.Event()
            speaking = asyncio.create_task(speak(ws, wav_file, heard))
            call.first_audio_at = None
            turn = await call.until("user_message")
            heard.set()
            turn += await call.until("turn_done")
            speech_ended = sent = await speaking

        reply = next(m for m in turn if m["type"] == "assistant_message")
        assert any(m["type"] == "audio" for m in turn), "no audio"
        if expect is not None:
            assert expect in reply["text"], f"expected {expect!r} in {reply['text']!r}"
        if call.first_audio_at is not None:
            what = "end of the recording" if speech_ended else "sending"
            print(f"First audio {call.first_audio_at - sent:.2f} s after the {what}")

        await ws.send(json.dumps({"type": "hangup"}))
        ended = (await call.until("call_ended"))[-1]
        assert ended["reason"] == "hangup", ended
        print("Conversation", started["conversation_id"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="A scripted live call: greeting, one turn, hang up."
    )
    parser.add_argument("url", nargs="?", default="ws://127.0.0.1:8080/api/call")
    turn = parser.add_mutually_exclusive_group()
    turn.add_argument("--text", default="Hello CI")
    turn.add_argument("--speak", type=Path, help="a 16 kHz mono 16-bit WAV")
    parser.add_argument("--expect", help="text the reply must contain")
    args = parser.parse_args()
    try:
        asyncio.run(main(args.url, args.text, args.speak, args.expect))
    except (AssertionError, TimeoutError) as error:
        sys.exit(f"The call failed: {error!r}")
