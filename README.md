# Voice Agent

Voice agent for automotive customer complaints

## Setup

Requires Docker with Compose v2.

The `make` targets are only shortcuts. Without `make`, run the commands from the matching target in the [Makefile](Makefile) yourself, e.g. `docker compose up --build` instead of `make run`.

```sh
make run   # production-like (nginx + backend) on http://localhost:8080
make dev   # hot reload on http://localhost:8080, backend also on http://localhost:8000
make logs  # follow the container logs
make down  # stop and remove the containers
```

Run `make` to list all targets.

## Local development

### Prerequisites

Python, uv, Node.js and pnpm in the versions listed in [.tool-versions](.tool-versions). You can install them any way you like.

Optionally, [asdf](https://asdf-vm.com/) installs exactly these versions:

```sh
asdf plugin add python
asdf plugin add uv
asdf plugin add nodejs
asdf plugin add pnpm
asdf install
```

### Install dependencies

Installs the backend and frontend dependencies from the lockfiles and the pre-commit git hook:

```sh
make init
```

### Run

Backend (FastAPI on http://127.0.0.1:8000, API docs at http://127.0.0.1:8000/docs):

```sh
uv --directory backend run fastapi dev voice_agent/main.py
```

Frontend (Vite on http://127.0.0.1:5173, proxies `/api` to the backend):

```sh
pnpm --dir frontend dev
```

### Checks and tests

```sh
make check       # format, lint (with fixes) and type-check backend and frontend
make pre-commit  # run all pre-commit hooks on all files
make test        # run backend and frontend tests
```
