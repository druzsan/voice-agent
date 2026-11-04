# Voice Agent

Voice agent for automotive customer complaints

## Prerequisites

Python, uv, Node.js and pnpm in the versions listed in [.tool-versions](.tool-versions). You can install them any way you like.

Optionally, [asdf](https://asdf-vm.com/) installs exactly these versions:

```sh
asdf plugin add python
asdf plugin add uv
asdf plugin add nodejs
asdf plugin add pnpm
asdf install
```

## Install dependencies

```sh
uv --directory backend sync
pnpm --dir frontend install
```

## Run

Backend (FastAPI on http://127.0.0.1:8000, API docs at http://127.0.0.1:8000/docs):

```sh
uv --directory backend run fastapi dev voice_agent/main.py
```

Frontend (Vite on http://127.0.0.1:5173, proxies `/api` to the backend):

```sh
pnpm --dir frontend dev
```

## Checks and tests

Backend:

```sh
uv --directory backend run ruff format --check .
uv --directory backend run ruff check .
uv --directory backend run pyright
uv --directory backend run pytest
```

Frontend:

```sh
pnpm --dir frontend format:check
pnpm --dir frontend lint
pnpm --dir frontend typecheck
pnpm --dir frontend test
```
