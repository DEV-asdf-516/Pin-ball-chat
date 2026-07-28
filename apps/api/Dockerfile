FROM node:22.18.0-bookworm-slim AS runtime-cli

ARG CODEX_VERSION=0.145.0-alpha.27
ARG CLAUDE_VERSION=2.1.195

RUN npm install --global "@openai/codex@${CODEX_VERSION}" "@anthropic-ai/claude-code@${CLAUDE_VERSION}" \
    && rm -rf /root/.npm

FROM python:3.12-slim

ARG CODEX_VERSION=0.145.0-alpha.27
ARG CLAUDE_VERSION=2.1.195

COPY --from=runtime-cli /usr/local /usr/local

WORKDIR /app
COPY apps/api/requirements.txt /app/requirements.txt
RUN python3 -m pip install --break-system-packages --no-cache-dir -r /app/requirements.txt
COPY apps/api/src /app/src
COPY libs /app/libs
ENV PYTHONPATH=/app/src:/app/libs \
    PYTHONDONTWRITEBYTECODE=1 \
    PINBALLCHAT_RUNTIME_ROOT=/var/lib/pinballchat-runtime \
    CODEX_COMMAND=codex \
    CLAUDE_COMMAND=claude \
    CODEX_RUNTIME_VERSION=${CODEX_VERSION} \
    CLAUDE_RUNTIME_VERSION=${CLAUDE_VERSION}
RUN mkdir -p /var/lib/pinballchat-runtime/codex-home /var/lib/pinballchat-runtime/claude-home /var/lib/pinballchat-runtime/scratch /tmp/pinballchat \
    && chmod 0700 /var/lib/pinballchat-runtime /var/lib/pinballchat-runtime/codex-home /var/lib/pinballchat-runtime/claude-home /var/lib/pinballchat-runtime/scratch /tmp/pinballchat
CMD ["python3", "-m", "uvicorn", "server.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
