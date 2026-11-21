FROM node:24-bookworm-slim

# Install Python 3.11, pip, venv, and required system libraries
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    python-is-python3 \
    build-essential \
    ca-certificates \
    curl \
  && rm -rf /var/lib/apt/lists/*

# Install uv for Python package & lockfile management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Enable pnpm via Corepack without interactive prompts
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN corepack enable && pnpm config set verify-deps-before-run false

WORKDIR /app

# 1. Install Python dependencies (both in .venv via uv and system-wide for subprocesses)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen \
  && uv pip install pytz numpy \
  && pip3 install --no-cache-dir --break-system-packages \
    "google-auth>=2.50.0" \
    "gspread>=6.2.1" \
    "pyswisseph>=2.10.3.2" \
    "requests>=2.33.1" \
    pytz \
    numpy

ENV PATH="/app/.venv/bin:${PATH}"

# 2. Copy workspace manifests and install Node/TypeScript dependencies
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc tsconfig.base.json tsconfig.json ./
COPY artifacts/api-server/package.json ./artifacts/api-server/package.json
COPY artifacts/calc-dashboard/package.json ./artifacts/calc-dashboard/package.json
COPY artifacts/mockup-sandbox/package.json ./artifacts/mockup-sandbox/package.json
COPY lib/api-client-react/package.json ./lib/api-client-react/package.json
COPY lib/api-spec/package.json ./lib/api-spec/package.json
COPY lib/api-zod/package.json ./lib/api-zod/package.json
COPY lib/db/package.json ./lib/db/package.json
COPY scripts/package.json ./scripts/package.json

RUN pnpm install --frozen-lockfile --allow-build=esbuild

# 3. Copy full project source and build shared libraries, frontend, and API server
COPY . .

RUN pnpm run typecheck:libs \
  && PORT=8080 BASE_PATH=./ pnpm --filter @workspace/calc-dashboard run build \
  && pnpm --filter @workspace/api-server run build

ENV NODE_ENV=production
ENV PORT=8080

EXPOSE 8080

CMD ["node", "--enable-source-maps", "artifacts/api-server/dist/index.mjs"]
