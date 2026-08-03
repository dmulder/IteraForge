FROM python:3.13-slim

ARG TARGETARCH
ARG OPENCODE_VERSION=1.18.10

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ITERAFORGE_CONFIG_HOME=/config \
    ITERAFORGE_DATA_HOME=/data \
    OPENCODE_DISABLE_AUTOUPDATE=true

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates curl git nodejs npm \
    && arch="${TARGETARCH:-$(dpkg --print-architecture)}" \
    && case "$arch" in \
        amd64) asset_arch=x64; checksum=6b1113da704253fb4da12b41e4236acecb9f2b62949c945f6eeacaa15111b976 ;; \
        arm64) asset_arch=arm64; checksum=41ae3041e91b894e4c0dc06a73a9a2796254bf390ffb99626a43af5e2912d170 ;; \
        *) echo "Unsupported architecture: $arch" >&2; exit 1 ;; \
    esac \
    && curl -fsSL \
        "https://github.com/anomalyco/opencode/releases/download/v${OPENCODE_VERSION}/opencode-linux-${asset_arch}.tar.gz" \
        -o /tmp/opencode.tar.gz \
    && echo "$checksum  /tmp/opencode.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/opencode.tar.gz -C /usr/local/bin opencode \
    && chmod 0755 /usr/local/bin/opencode \
    && git --version \
    && opencode --version \
    && npm install -g @openai/codex @google/gemini-cli @anthropic-ai/claude-code \
    && rm -f /tmp/opencode.tar.gz \
    && npm cache clean --force \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .
USER app
EXPOSE 8765
CMD ["uvicorn", "iteraforge.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8765"]
