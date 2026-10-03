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
COPY pyproject.toml uv.lock .python-version ./
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

# The agent's shell and file tools work in its own home, not in the app
RUN useradd --create-home --shell /bin/bash agent
USER agent
WORKDIR /home/agent

EXPOSE 8080
CMD ["radagent", "--serve", "--host", "0.0.0.0", "--port", "8080"]
