# The agent as AgentCore Runtime runs it: linux/arm64, serving /ws, /ping and /invocations on port 8080
#   docker buildx build --platform linux/arm64 -t radagent-agent .      (scripts/deploy-agent.sh builds and pushes)
# AgentCore takes images up to 2 GB, so the build tools stay in the first stage and only headless Chromium is installed

FROM python:3.13-slim-bookworm AS build

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, so editing the agent doesn't reinstall them
# No .python-version: it isn't committed, and the base image's Python is the one to use
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# The agent itself goes into the environment as a package, so the runtime stage needs nothing but .venv
COPY README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable


FROM python:3.13-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
    DOCKER_CONTAINER=1 \
    PATH=/app/.venv/bin:$PATH

COPY --from=build /app/.venv /app/.venv

# Headless Chromium for read_page and /research, with the system libraries it needs (needs root, so before USER)
RUN playwright install --with-deps --only-shell chromium \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

# cloudflared, for reaching the sandbox through a Cloudflare Tunnel (sandbox/README.md), from Cloudflare's signed repository
ADD https://pkg.cloudflare.com/cloudflare-main.gpg /usr/share/keyrings/cloudflare-main.gpg
RUN chmod 644 /usr/share/keyrings/cloudflare-main.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" \
        > /etc/apt/sources.list.d/cloudflared.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends cloudflared \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

# The agent's shell and file tools work in its own home, not in the app
RUN useradd --create-home --shell /bin/bash agent
USER agent
WORKDIR /home/agent

EXPOSE 8080
CMD ["radagent", "--serve", "--host", "0.0.0.0", "--port", "8080"]
