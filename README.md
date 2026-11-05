# Voice Agent

A minimal voice conversation app that works like a phone call. Press the green button to call and just talk: the assistant notices when you pause, starts speaking its answer while it's still writing it, and stops when you talk over it. You can also type, or enter digits on the keypad. The red button hangs up. Every conversation is stored in PostgreSQL.

- **Speech recognition:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (English `small.en` by default), on the CPU. Or OpenAI: `gpt-live-transcribe` over the Realtime API while the caller speaks, `gpt-4o-mini-transcribe` for whole recordings
- **Turn detection:** the [Silero VAD](https://github.com/snakers4/silero-vad) model that faster-whisper ships, via ONNX Runtime
- **Speech synthesis:** [Piper](https://github.com/OHF-Voice/piper1-gpl) (voice `en_US-lessac-medium` by default), on the CPU. Or OpenAI: `gpt-4o-mini-tts` (voice `marin`), played as it's generated
- **Language model:** [PydanticAI](https://ai.pydantic.dev/) with OpenAI, [Requesty](https://www.requesty.ai/) or [OpenRouter](https://openrouter.ai/). By default `gpt-6.1-sol` on Azure in Germany, through Requesty's EU router. It answers plainly, with no tools or agent logic yet. The `echo` provider repeats the caller and needs no key.
- **Storage:** PostgreSQL with SQLAlchemy and Alembic migrations

Everything runs in Docker Compose. The speech models live in [backend/models](backend/models), which the backend container mounts read-write. Whatever is missing there is downloaded at startup, at pinned revisions; on the host, the same code uses the same folder.

## Quick start

Requires Docker with Compose v2.

```sh
cp .env.example .env   # optional: choose a language model, see below
make run               # production-like stack on http://localhost:8080
```

Open http://localhost:8080. Browsers allow the microphone on `localhost`. Use headphones if you can: the browser's echo cancellation keeps most of the assistant's voice out of the microphone, but what gets through can sound like you talking over it. The first start downloads about 520 MB of speech models into `backend/models`, which takes a minute or two; later starts reuse them.

Without a `.env`, the app talks to `gpt-6.1-sol` through Requesty, which needs only `REQUESTY_API_KEY`; without the key, a fixed reply says the model isn't configured. `VOICE_AGENT_LLM_PROVIDER=echo` repeats what you said and needs no key. Another provider or model is set in `.env`:

```sh
REQUESTY_API_KEY=...                                       # enough for the default model
VOICE_AGENT_LLM_PROVIDER=requesty                          # openai, requesty, openrouter or echo
VOICE_AGENT_LLM_MODEL=azure/gpt-6.1-sol@germanywestcentral # model ID as the provider lists it
VOICE_AGENT_REQUESTY_BASE_URL=https://router.eu.requesty.ai/v1   # the default; global: https://router.requesty.ai/v1
```

[.env.example](.env.example) shows the choices for the language model and the speech models; [config.py](backend/voice_agent/config.py) describes every setting. `make llm-smoke` asks the configured model one question, which checks the provider, model ID and key without the UI. The panel next to the phone shows the models the app uses, and what the current call consumed (see [Usage and costs](#usage-and-costs)).

### OpenAI speech

The speech models run locally by default, so the app needs no key. To use OpenAI's speech models instead, set in the same file:

```sh
VOICE_AGENT_STT_PROVIDER=openai   # speech recognition
VOICE_AGENT_TTS_PROVIDER=openai   # speech synthesis
OPENAI_API_KEY=...                # needs API credit on platform.openai.com
```

Either one can be switched on its own. With OpenAI, the caller's audio and the answers' text go to OpenAI; with `local`, speech stays on this machine. No speech model is downloaded for a provider that isn't `local`. The defaults follow the tuning of the earlier German prototype: the voice `marin` at speed 1.25 (1.0 sounds slow on the phone) with instructions for a friendly, brisk phone manner. `VOICE_AGENT_OPENAI_BASE_URL` points both the speech models and the `openai` language model at another endpoint, e.g. Azure OpenAI's v1 API (not tested here). `make test-openai` checks the key and the models with a short spoken sentence (a few cents).

The `make` targets are only shortcuts; run `make` to list them. Without `make`, run the commands from the matching target in the [Makefile](Makefile).

```sh
make run   # production-like (nginx + backend) on http://localhost:8080
make dev   # hot reload on http://localhost:8080; backend also on :8000, PostgreSQL on :5432
make logs  # follow the container logs
make down  # stop and remove the containers (the database volume stays)
make clean # also remove the database volume and the built images (the models in backend/models stay)
```

## How a call works

A call is one WebSocket connection (`/api/call`), and one conversation. Connecting starts it, losing the connection ends it:

1. **Green button.** The browser connects and opens the microphone. The backend creates the conversation and speaks the greeting.
2. **Just talk.** The browser streams the microphone continuously as 16 kHz mono PCM (an AudioWorklet downsamples it), in 32 ms frames. The backend scores each frame with Silero VAD: 160 ms of speech start an utterance, and a pause of 800 ms ends it.
3. **The backend answers:**
   - Whisper transcribes the utterance. Silence or likely invented words (high no-speech probability) count as "nothing heard", and nothing is stored. With OpenAI, the utterance's audio goes to a Realtime transcription session while the caller speaks, and the pause commits it, so the transcript arrives shortly after; if that fails, the recording is transcribed as a file. An empty transcript counts as "nothing heard".
   - The caller's message is stored.
   - The model streams its answer with the recent conversation as history; the text appears as it's written.
   - Each finished sentence is spoken right away: the synthesizer speaks sentence 1 while the model still writes sentence 2. Its audio goes to the browser in pieces as it's generated (Piper: one piece per sentence; OpenAI: 100 ms pieces). The browser plays the sentences (clips) in order, each once 0.3 s of it has arrived or it's complete.
   - The answer is stored once it has played, with its stage timings and token usage.
4. **Talking over the answer** stops it: after 400 ms of speech the backend tells the browser to stop playing, cancels the model and the synthesis, and stores the answer as interrupted, with the part the caller heard (the clips the browser reported as played). The model's next prompt says what the caller heard. Shorter sounds such as "mhm", a cough or echo don't interrupt.
5. **Typing or the keypad** work at any time. Keypad digits collect in the text box, and `#` sends them. What arrives while an answer is being worked on is answered next; speech that ends while the backend is still thinking joins the next turn.
6. **Mute** stops sending the microphone. **Red button** hangs up. Closing the tab, losing the connection and the call limit (15 minutes) end the call too.

If the model fails or isn't configured, a fixed reply is spoken instead, stored with the source `template`; what the model said before failing stays as an interrupted message. If speech synthesis fails, the answer is still shown.

The backend decides the call's state and announces it: `listening`, `thinking` (from the end of the caller's turn) and `speaking` (from the first clip until the last one has played). A clip whose "played" message never arrives can't hold the call: playback counts as over 1.5 s after the clips' length.

### API

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Liveness, for the container health check |
| `GET /api/status` | Database reachable, model in use, speech models (with the fallback recognizer and the speaking pace), recording limit |
| `WS /api/call` | A live call, see below |
| `POST /api/conversations` | Push-to-talk call over HTTP: conversation, greeting and its audio |
| `POST /api/conversations/{id}/turns/voice` | A recording (`audio/wav`, 16 kHz mono 16-bit) → caller message, answer and audio |
| `POST /api/conversations/{id}/turns/text` | Typed text or keypad digits (`{"text", "via"}`) → the same |
| `POST /api/conversations/{id}/end` | Hang up (`{"reason": "hangup" \| "page_closed"}`); waits for a running turn; ending twice changes nothing |
| `GET /api/conversations`, `GET /api/conversations/{id}` | Stored conversations with their messages |

The HTTP conversation endpoints answer one complete request at a time, without streaming or turn detection. The page uses the WebSocket; the HTTP endpoints remain for scripts and tests. Interactive docs: http://localhost:8000/docs in development mode.

The live call's messages ([protocol.py](backend/voice_agent/conversation/protocol.py), mirrored in [callProtocol.ts](frontend/src/api/callProtocol.ts)):

| Direction | Message | Meaning |
|---|---|---|
| → | binary frame | Microphone audio: 16 kHz mono PCM16, little-endian, up to 64 KiB |
| → | `{"type": "text", "text", "via"}` | Typed text (`keyboard`) or keypad digits (`keypad`) |
| → | `{"type": "played", "clip"}` | A clip played to the end (or at least 90 % of it) |
| → | `{"type": "mute", "muted"}` | Microphone muted or unmuted; muting drops a partly heard utterance |
| → | `{"type": "hangup"}` | Red button |
| ← | `call_started {conversation_id}` | First message |
| ← | `state {state}` | `listening`, `thinking` or `speaking` |
| ← | `caller_speech {active}` | The voice detection hears the caller start or stop talking |
| ← | `user_message {id, text, source}` | The caller's stored message |
| ← | `assistant_delta {turn, text}` | More of the answer, as the model writes it |
| ← | `audio {clip, turn, sample_rate, pcm_base64}` | More audio of a spoken sentence: mono PCM16, little-endian |
| ← | `audio_end {clip, turn, text, duration_ms}` | The sentence's last piece has been sent |
| ← | `assistant_message {id, turn, text, source, interrupted}` | The stored answer |
| ← | `interrupted {turn}` | The caller talked over the answer: stop playing, drop queued clips |
| ← | `turn_done {turn, timings_ms, usage}` | Stage timings of the turn, and what its model calls consumed |
| ← | `usage {usage}` | Consumption outside of a turn: recognizing speech that turned out to be nothing |
| ← | `error {code, message}` | `invalid_message`, `stt_failed` or `busy`; the call goes on |
| ← | `call_ended {reason}` | Last message before the backend closes the connection |

Only pages of this app may connect: a browser's `Origin` must match the `Host` (nginx and Vite pass it on). If the database isn't reachable, the backend closes the connection with code 1011; an oversized frame closes it with 1009.

### Stored data

- **`conversations`:** start and end, end reason (`hangup`, `page_closed`, `disconnect`, `timeout` or `error`), and the configuration the call ran with (provider, model, speech recognition model, voice; OpenAI models as e.g. `openai/gpt-live-transcribe` and `openai/gpt-4o-mini-tts/marin`), so answers stay comparable across setups.
- **`messages`:** role, source and text for each message:
  - **Sources:** `voice`, `keyboard`, `keypad`, `llm` or `template`.
  - **Interrupted answers:** `interrupted`, and in `heard_text` the part the caller heard.
  - **Timings in milliseconds:** for push-to-talk turns `stt`, `llm`, `tts` and `total`. For live calls `stt` (on the caller's message), `llm_first_token` and `llm_total` (from the request to the model's first text and to its end), and `first_audio` and `total` (from the end of the caller's turn to the first clip and to the last one).
  - **Recognition metrics:** audio length, average log probability, no-speech probability (the last two only from Whisper).
  - **Token usage** of the answer.
  - **Usage per service and model** (`usage`): calls, tokens in and out, audio seconds heard or spoken, the calls' time and their cost in USD. Speech recognition is stored on the caller's message, the language model and speech synthesis on the answer.

Audio is not stored.

### Usage and costs

Every model call reports what it consumed, and its time is measured around it:

| Service | Tokens | Audio | Cost |
|---|---|---|---|
| Speech recognition | OpenAI file transcription: audio in, text out | Length of the utterance | [genai-prices](https://github.com/pydantic/genai-prices); live transcription is billed by audio duration, $0.017 per minute |
| Language model | As the provider reports them | – | Requesty: its own price list (`/models`, read at startup, including its margin); OpenAI and OpenRouter: genai-prices; `echo`: free |
| Speech synthesis | OpenAI: text in, audio out (from the speech stream's last event) | Length of the spoken audio | genai-prices |

Local models (faster-whisper, Piper) report audio and time and cost nothing. A cost is unknown (`null`) when there's no price for the model; the page then shows the known part as a lower bound ("≥"). The panel next to the phone adds up the call: per service the calls, tokens, audio, time and cost, the total cost, and the mean and last time of each stage of a turn (transcript ready, the model's first text, first audio, whole answer). In a measured call with OpenAI speech and `gpt-6.1-sol`, one 9 s question and its 12 s answer cost about $0.008: recognition $0.0026, the model $0.0011, synthesis $0.0046.

## Services

| Service | Role |
|---|---|
| `postgres` | PostgreSQL 18; data in the `database` volume |
| `migrate` | Runs `alembic upgrade head` once, then exits; the backend starts after it |
| `backend` | FastAPI, one process: speech models, language model, conversation storage |
| `frontend` | nginx serving the React/Mantine app and forwarding `/api` (in development: Vite) |

The backend container runs as the owner of the mounted `backend/models` folder ([entrypoint.sh](backend/entrypoint.sh)), usually you, so the downloaded models belong to you on the host.

The backend is a single process on purpose. The local speech models are loaded once at startup and warmed up. Only one local recognition and one local synthesis run at a time, so concurrent calls queue for the CPU; OpenAI's models have no such queue. Each live call with OpenAI recognition holds its own Realtime session. The state of a live call and the per-conversation turn locks live in memory.

## Development

`make dev` runs the stack with the working tree mounted read-only. The backend reloads on changes, and Vite updates the page in place. Changed dependencies or new migrations need another `make dev`.

Python, uv, Node.js and pnpm in the versions from [.tool-versions](.tool-versions) are needed for the tools on the host (tests, checks, migrations). [asdf](https://asdf-vm.com/) can install exactly these versions (`asdf plugin add python|uv|nodejs|pnpm`, then `asdf install`).

```sh
make init         # install backend and frontend dependencies and the pre-commit hook
make check        # format, lint (with fixes) and type-check backend and frontend
make pre-commit   # run all pre-commit hooks on all files
make test         # backend and frontend tests (storage in memory, no containers)
make test-speech  # Piper speaks, the voice detection and Whisper listen: the real models (downloaded into backend/models if missing)
make test-openai  # OpenAI speaks, its file and live transcription listen (needs OPENAI_API_KEY; a few cents)
make call-smoke   # a scripted live call against the running stack (args="--speak question.wav" speaks a 16 kHz WAV)
```

### Database migrations

```sh
make dev                                  # the dev database on 127.0.0.1:5432
make db-revision m="add something"        # autogenerate a migration from the models; review it
make db-upgrade                           # apply migrations without restarting everything
make psql                                 # a psql shell on the dev database
```

The tests keep the conversations in memory (`tests/fakes.py`) and need no database; live calls run over the test client's WebSocket with a fake voice detection (loud frames are speech). The real PostgreSQL path is checked in CI: the containers job migrates a fresh database, checks that the models and the migrations agree (`alembic check`), and makes a push-to-talk call and a live call through the running stack.

## Measured latency

Push-to-talk turns, warm, on the development machine (28 CPU threads), for a 3.8 s spoken question:

| Model | Speech recognition | Model | Speech synthesis | Whole turn |
|---|---|---|---|---|
| `echo` | 0.74 s | – | 0.05 s | 0.8 s |
| Requesty `azure/gpt-4.1-mini@francecentral` (EU router) | 0.85 s | 0.96 s | 0.10 s | 1.9 s |

A reasoning model such as `gpt-5-mini` took about 4 s for its answer alone.

Live calls, `echo`, for a 2.3 s spoken question streamed in real time (`make call-smoke args="--speak ..."`, three calls):

| Stage | Time |
|---|---|
| Pause until the turn ends (`VOICE_AGENT_VAD_SILENCE_MS`, then 700) | 0.7 s |
| Speech recognition | 0.60–0.64 s |
| Model's first text, first sentence synthesized and sent (`first_audio` − `stt`) | 0.05 s |
| **End of the recording → first audio, as the caller hears it** | **1.18–1.23 s** |

The recording ends with Piper's own trailing silence of about 0.2 s, which already counts toward the pause, so the stages add up to a bit more than the measured total.

Compared with push-to-talk, the caller no longer taps, but waits for the pause instead (0.8 s by default, as in the earlier German prototype). In exchange, speech starts after the model's first sentence rather than after the whole answer and its synthesis: with a real model, the first audio comes at about `stt` + time to the model's first sentence + one sentence of synthesis (about 0.05–0.1 s), however long the answer is. The live-call numbers with a hosted model are still to be measured.

Live calls with OpenAI speech (live transcription, `gpt-4o-mini-tts`), `echo`, for an 8.4 s spoken question, four calls:

| Stage | Time |
|---|---|
| Pause until the turn ends (then 700 ms) | 0.7 s |
| Live transcript ready (`stt`) | 0.48–0.75 s |
| First sentence's first audio piece sent (`first_audio` − `stt`) | 1.1–1.9 s |
| **End of the recording → first audio sent** | **1.95–2.93 s** |

Live transcription is about as fast as local Whisper on this machine, so its gain is offloading the CPU, not latency. Synthesis is the slow stage: OpenAI's speech stream starts with about 85 ms of audio 0.5–1 s after the request, then pauses for another 0.25–0.5 s, which is why the browser buffers 0.3 s before it starts a sentence. Piper takes 0.05–0.1 s per sentence. Push-to-talk with OpenAI, same question: transcription 1.1 s, synthesis of the whole 5.9 s answer 1.8 s.

These are single manual measurements, not a benchmark. They were taken with a 0.7 s pause; the default is now 0.8 s, which adds 0.1 s to every live-call answer. Each stored message carries its own timings.

## Limits

- Echo: without headphones, the assistant's voice can reach the microphone. Short echo is ignored, but loud speakers can interrupt the assistant with its own voice.
- Local recognition only starts when the caller's turn has ended. OpenAI's live transcription listens while the caller speaks, but partial transcripts aren't shown.
- OpenAI announced the shutdown of `gpt-4o-mini-tts` on 2027-01-06 and of `gpt-4o-mini-transcribe` on 2027-02-26. The named transcription successor `gpt-transcribe` is a setting away (`VOICE_AGENT_OPENAI_STT_MODEL`); the named speech successor `gpt-realtime-2.1-mini` runs only on the Realtime API and would need its own synthesizer.
- A call that loses its connection can't be resumed: it has ended, like a phone call.
- No login: the app is published on `localhost` only.
- One backend process; per-conversation turn locks live in memory.
- English only.

## Third-party licences

This project's own code is MIT-licensed. The backend uses third-party components that keep their own licences:
- [Piper](https://github.com/OHF-Voice/piper1-gpl) (GPL-3.0)
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (MIT)
- the Whisper model weights (MIT)
- the selected Piper voice; the default `en_US-lessac-medium` was trained on the [Blizzard 2013 Lessac dataset](https://www.cstr.ed.ac.uk/projects/blizzard/2013/lessac_blizzard2013/license.html) under its own licence, and each voice's model card names its dataset

These components are installed during the image build or downloaded into `backend/models` at startup, and aren't part of this repository. This project doesn't publish or distribute built images or models. If you distribute images or models obtained through it, check these licences first.
