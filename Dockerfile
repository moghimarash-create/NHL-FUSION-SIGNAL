# Stage 1: Build Python virtualenv (including compiled pyswisseph C extension)
FROM node:24-bookworm-slim AS python-builder

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    build-essential \
    ca-certificates \
  && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/venv \
  && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
  && /opt/venv/bin/pip install --no-cache-dir \
    "google-auth>=2.50.0" \
    "gspread>=6.2.1" \
    "pyswisseph>=2.10.3.2" \
    "requests>=2.33.1" \
    pytz \
    numpy

# Stage 2: Build TypeScript libraries, React/Vite frontend, and bundled Express API server
FROM node:24-bookworm-slim AS node-builder

ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN corepack enable && pnpm config set verify-deps-before-run false

WORKDIR /app

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

COPY . .

RUN pnpm run typecheck:libs \
  && PORT=8080 BASE_PATH=./ pnpm --filter @workspace/calc-dashboard run build \
  && pnpm --filter @workspace/api-server run build

# Stage 3: Minimal production runtime (Node.js + Python 3 venv, no compiler toolchain or node_modules bloat)
FROM node:24-bookworm-slim AS runner

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    python3 \
    python-is-python3 \
    ca-certificates \
    curl \
  && rm -rf /var/lib/apt/lists/*

COPY --from=python-builder /opt/venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /app

COPY --from=node-builder /app/package.json ./package.json
COPY --from=node-builder /app/artifacts/api-server/dist ./artifacts/api-server/dist
COPY --from=node-builder /app/artifacts/api-server/python ./artifacts/api-server/python
COPY --from=node-builder /app/artifacts/api-server/data ./artifacts/api-server/data
COPY --from=node-builder /app/artifacts/calc-dashboard/dist ./artifacts/calc-dashboard/dist
COPY --from=node-builder /app/artifacts/calc-dashboard/public ./artifacts/calc-dashboard/public
COPY --from=node-builder /app/artifacts/data ./artifacts/data
COPY --from=node-builder /app/data ./data

ENV NODE_ENV=production
ENV PORT=8080
ENV DRY_RUN=true

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT:-8080}/healthz" || exit 1

CMD ["node", "--enable-source-maps", "artifacts/api-server/dist/index.mjs"]
