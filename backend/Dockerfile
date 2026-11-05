FROM ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 AS uv

FROM python:3.12.16-slim-trixie@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30 AS base
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
# Runs everything as the owner of the mounted models folder (see the script)
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
ENTRYPOINT ["entrypoint.sh"]
# The first start downloads the speech models (about 520 MB) into the mounted
# backend/models; later starts only load and warm them up
HEALTHCHECK --interval=10s --timeout=3s --start-period=10m --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"]

FROM base AS builder
COPY --from=uv /uv /usr/local/bin/uv
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev

FROM builder AS dev
ENV PYTHONDONTWRITEBYTECODE=1
COPY pyproject.toml ./
COPY migrations migrations
COPY voice_agent voice_agent
EXPOSE 8000
CMD ["fastapi", "dev", "voice_agent/main.py", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS runtime
# The unprivileged user when no models folder is mounted (e.g. for migrations)
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app \
    && mkdir models && chown app:app models
COPY --from=builder /opt/venv /opt/venv
# pyproject.toml holds the Alembic configuration
COPY pyproject.toml ./
COPY migrations migrations
COPY voice_agent voice_agent
EXPOSE 8000
CMD ["fastapi", "run", "voice_agent/main.py", "--host", "0.0.0.0", "--port", "8000"]
