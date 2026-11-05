# Voice Agent

A minimal voice conversation app that works like a phone call. Press the green button to call, tap the microphone, speak, tap again and hear the answer. You can also type, or enter digits on the keypad. The red button hangs up. Every conversation is stored in PostgreSQL.

- **Speech recognition:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (English `small.en` by default), on the CPU
- **Speech synthesis:** [Piper](https://github.com/OHF-Voice/piper1-gpl) (voice `en_US-lessac-medium` by default), on the CPU
- **Language model:** [PydanticAI](https://ai.pydantic.dev/) with OpenAI, [Requesty](https://www.requesty.ai/) or [OpenRouter](https://openrouter.ai/). It answers plainly, with no tools or agent logic yet. The `echo` provider repeats the caller and needs no key.
- **Storage:** PostgreSQL with SQLAlchemy and Alembic migrations

Everything runs in Docker Compose. The speech models live in [backend/models](backend/models), which the backend container mounts read-write. Whatever is missing there is downloaded at startup, at pinned revisions; on the host, the same code uses the same folder.

## Quick start

Requires Docker with Compose v2.

```sh
cp .env.example .env   # optional: choose a language model, see below
make run               # production-like stack on http://localhost:8080
```

Open http://localhost:8080. Browsers allow the microphone on `localhost`. The first start downloads about 520 MB of speech models into `backend/models`, which takes a minute or two; later starts reuse them.

Without a `.env`, the app uses the `echo` provider: the whole voice loop works and the assistant repeats what you said. For real answers, set a provider, a model and its key in `.env`:

```sh
VOICE_AGENT_LLM_PROVIDER=requesty                    # openai, requesty, openrouter or echo
VOICE_AGENT_LLM_MODEL=azure/gpt-4.1-mini@francecentral
VOICE_AGENT_REQUESTY_API_KEY=...                     # or REQUESTY_API_KEY
VOICE_AGENT_REQUESTY_BASE_URL=https://router.eu.requesty.ai/v1   # if your organization requires the EU router
```

[.env.example](.env.example) describes every setting. `make llm-smoke` asks the configured model one question, which checks the provider, model ID and key without the UI. The idle screen shows which model the app uses.

The `make` targets are only shortcuts; run `make` to list them. Without `make`, run the commands from the matching target in the [Makefile](Makefile).

```sh
make run   # production-like (nginx + backend) on http://localhost:8080
make dev   # hot reload on http://localhost:8080; backend also on :8000, PostgreSQL on :5432
make logs  # follow the container logs
make down  # stop and remove the containers (the database volume stays)
make clean # also remove the database volume and the built images (the models in backend/models stay)
```

## How a call works

One call is one conversation. Each turn is one HTTP request with one complete answer:

1. **Green button.** `POST /api/conversations` creates the conversation and returns the spoken greeting.
2. **Tap the mic, speak, tap again.** The browser records 16 kHz mono PCM (an AudioWorklet downsamples the microphone) and sends it as a WAV to `POST /api/conversations/{id}/turns/voice`. Recording stops on its own at the backend's limit (30 s by default).
3. **The backend answers:**
   - Whisper transcribes the recording.
   - Silence or likely invented words (high no-speech probability) count as "nothing heard", and nothing is stored.
   - The caller's message is stored.
   - The model answers with the recent conversation as history.
   - Piper speaks the whole answer.
   - The answer is stored with its stage timings and token usage.
4. **Typing or the keypad** go to `POST /api/conversations/{id}/turns/text` instead. Keypad digits collect in the text box, and `#` sends them.
5. **One thing at a time.** While an answer is pending or playing, the microphone, the text box and the keypad are disabled. A second turn would be refused (409).
6. **Red button.** `POST /api/conversations/{id}/end` waits for a running turn, so the stored transcript is complete. Closing the tab ends the call too, as far as the browser allows (`page_closed`).

If the model fails or isn't configured, a fixed reply is spoken instead, stored with the source `template`. If speech synthesis fails, the answer is still shown.

### API

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Liveness, for the container health check |
| `GET /api/status` | Database reachable, model in use, speech models, recording limit |
| `POST /api/conversations` | Start a call: conversation, greeting and its audio |
| `POST /api/conversations/{id}/turns/voice` | A recording (`audio/wav`, 16 kHz mono 16-bit) → caller message, answer and audio |
| `POST /api/conversations/{id}/turns/text` | Typed text or keypad digits (`{"text", "via"}`) → the same |
| `POST /api/conversations/{id}/end` | Hang up (`{"reason": "hangup" \| "page_closed"}`); ending twice changes nothing |
| `GET /api/conversations`, `GET /api/conversations/{id}` | Stored conversations with their messages |

Interactive docs: http://localhost:8000/docs in development mode.

### Stored data

- **`conversations`:** start and end, end reason, and the configuration the call ran with (provider, model, speech recognition model, voice), so answers stay comparable across setups.
- **`messages`:** role, source and text for each message:
  - **Sources:** `voice`, `keyboard`, `keypad`, `llm` or `template`.
  - **Timings in milliseconds:** speech recognition, model, synthesis and total.
  - **Recognition metrics:** audio length, average log probability, no-speech probability.
  - **Token usage** of the answer.

Audio is not stored.

## Services

| Service | Role |
|---|---|
| `postgres` | PostgreSQL 18; data in the `database` volume |
| `migrate` | Runs `alembic upgrade head` once, then exits; the backend starts after it |
| `backend` | FastAPI, one process: speech models, language model, conversation storage |
| `frontend` | nginx serving the React/Mantine app and forwarding `/api` (in development: Vite) |

The backend container runs as the owner of the mounted `backend/models` folder ([entrypoint.sh](backend/entrypoint.sh)), usually you, so the downloaded models belong to you on the host.

The backend is a single process on purpose. The speech models are loaded once at startup and warmed up. Only one recognition and one synthesis run at a time, so concurrent calls queue for the CPU.

## Development

`make dev` runs the stack with the working tree mounted read-only. The backend reloads on changes, and Vite updates the page in place. Changed dependencies or new migrations need another `make dev`.

Python, uv, Node.js and pnpm in the versions from [.tool-versions](.tool-versions) are needed for the tools on the host (tests, checks, migrations). [asdf](https://asdf-vm.com/) can install exactly these versions (`asdf plugin add python|uv|nodejs|pnpm`, then `asdf install`).

```sh
make init         # install backend and frontend dependencies and the pre-commit hook
make check        # format, lint (with fixes) and type-check backend and frontend
make pre-commit   # run all pre-commit hooks on all files
make test         # backend and frontend tests (storage in memory, no containers)
make test-speech  # Piper speaks, Whisper listens: the real models (downloaded into backend/models if missing)
```

### Database migrations

```sh
make dev                                  # the dev database on 127.0.0.1:5432
make db-revision m="add something"        # autogenerate a migration from the models; review it
make db-upgrade                           # apply migrations without restarting everything
make psql                                 # a psql shell on the dev database
```

The tests keep the conversations in memory (`tests/fakes.py`) and need no database. The real PostgreSQL path is checked in CI: the containers job migrates a fresh database, checks that the models and the migrations agree (`alembic check`), and makes a call through the running stack.

## Measured latency

Warm turns on the development machine (28 CPU threads), for a 3.8 s spoken question:

| Model | Speech recognition | Model | Speech synthesis | Whole turn |
|---|---|---|---|---|
| `echo` | 0.74 s | – | 0.05 s | 0.8 s |
| Requesty `azure/gpt-4.1-mini@francecentral` (EU router) | 0.85 s | 0.96 s | 0.10 s | 1.9 s |

A reasoning model such as `gpt-5-mini` took about 4 s for its answer alone. These are single manual measurements, not a benchmark. Each stored message carries its own timings.

## Limits

- Push-to-talk only. The caller can't talk over the assistant, and turns aren't detected automatically yet.
- The whole answer is generated before speech starts. There is no streaming yet.
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
