# Stage 1: build the React frontend to static files.
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY web/ ./
RUN npm run build

# Stage 2: the API, which also serves the built frontend.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1

# Dependencies first so code changes don't invalidate this layer.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

COPY --from=web /web/dist /app/web/dist
ENV EA_WEB_DIST=/app/web/dist

# uid 1000: Hugging Face Spaces runs containers as that user, and the
# home directory has to exist for it to write anything.
RUN useradd --create-home --uid 1000 app
USER app

EXPOSE 8000
# `serve` applies migrations, then starts the API. The worker container runs
# the same image with `exposure-auditor worker`.
CMD ["/app/.venv/bin/exposure-auditor", "serve", "--host", "0.0.0.0", "--port", "8000"]
