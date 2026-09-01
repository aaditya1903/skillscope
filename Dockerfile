# Build the API image from an official Python base with uv for locked installs.
FROM python:3.12-slim-trixie AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Install dependencies before the source so a code change does not refetch them.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

COPY src ./src
COPY README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev


FROM python:3.12-slim-trixie AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN useradd --create-home --uid 10001 skillscope
WORKDIR /app

COPY --from=builder --chown=skillscope:skillscope /app/.venv /app/.venv
COPY --chown=skillscope:skillscope src ./src
COPY --chown=skillscope:skillscope alembic.ini ./
COPY --chown=skillscope:skillscope migrations ./migrations
COPY --chown=skillscope:skillscope config ./config
COPY --chown=skillscope:skillscope reports ./reports
# Manifests and demonstration fixtures are identifiers, hashes and original
# content only. No upstream skill body is copied into the image.
COPY --chown=skillscope:skillscope data ./data

# Docker seeds a named volume from the image directory it covers, and creates
# that directory root-owned when the image has none. Both mount points are
# written at runtime by an unprivileged user, so they must already exist.
RUN mkdir -p /app/data/demo/generated /app/config/demo \
    && chown -R skillscope:skillscope /app/data /app/config

USER skillscope
EXPOSE 8000

# The application's own structured access log replaces Uvicorn's, which would
# otherwise record raw query strings.
CMD ["uvicorn", "skillscope.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
