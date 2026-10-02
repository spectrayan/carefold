# Carefold Multi-Stage Dockerfile
# Supports target 'backend', target 'web', and default 'all-in-one'
# Build: docker build -f docker/Dockerfile .

# ==========================================
# Stage 1: Python FastAPI Backend
# ==========================================
FROM python:3.12-slim AS backend
WORKDIR /app

RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/ ./backend/
RUN pip install --no-cache-dir ./backend \
    && pip cache purge \
    && rm -rf /root/.cache /usr/local/lib/python3.12/site-packages/pip* /usr/local/bin/pip*

COPY agents/ ./agents/
COPY skills/ ./skills/

ENV CAREFOLD_WORKSPACE=/app \
    CAREFOLD_DATA=/data \
    PORT=8000 \
    PYTHONUNBUFFERED=1

RUN mkdir -p /data

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')" || exit 1

CMD ["uvicorn", "carefold.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ==========================================
# Stage 2: Web Build & Runner
# ==========================================
FROM node:22-alpine AS web-builder
WORKDIR /app

# Enable pnpm
RUN corepack enable && corepack prepare pnpm@latest --activate

COPY package.json pnpm-workspace.yaml pnpm-lock.yaml* tsconfig.base.json ./
COPY scripts/ ./scripts/
COPY packages/ ./packages/
COPY apps/web/ ./apps/web/
RUN mkdir -p /app/apps/web/public

RUN pnpm install --frozen-lockfile || pnpm install
RUN pnpm --filter @carefold/web build
RUN pnpm prune --prod

FROM node:22-alpine AS web
WORKDIR /app

ENV NODE_ENV=production \
    PORT=3000

# Remove unneeded npm, yarn, and corepack packages from runtime container image
RUN apk upgrade --no-cache \
    && rm -rf /usr/local/lib/node_modules/npm /usr/local/bin/npm /usr/local/bin/npx /opt/yarn* /usr/local/bin/yarn* /usr/local/bin/corepack

COPY --from=web-builder /app/apps/web/package.json ./apps/web/
COPY --from=web-builder /app/packages ./packages/
COPY --from=web-builder /app/node_modules ./node_modules
COPY --from=web-builder /app/apps/web/node_modules ./apps/web/node_modules
COPY --from=web-builder /app/apps/web/.next ./apps/web/.next
COPY --from=web-builder /app/apps/web/public ./apps/web/public
COPY agents/ ./agents/
COPY skills/ ./skills/

EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1:3000/api/health || exit 1

CMD ["node", "node_modules/.bin/next", "start", "apps/web", "-p", "3000"]

# ==========================================
# Stage 3: Combined All-In-One Default Target
# ==========================================
FROM python:3.12-slim AS all-in-one
WORKDIR /app

RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 22
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /usr/local/lib/node_modules/npm /usr/bin/npm /usr/bin/npx

COPY backend/ ./backend/
RUN pip install --no-cache-dir ./backend \
    && pip cache purge \
    && rm -rf /root/.cache /usr/local/lib/python3.12/site-packages/pip* /usr/local/bin/pip*

COPY agents/ ./agents/
COPY skills/ ./skills/
COPY evals/ ./evals/

COPY --from=web-builder /app/apps/web/package.json ./apps/web/
COPY --from=web-builder /app/packages ./packages/
COPY --from=web-builder /app/node_modules ./node_modules
COPY --from=web-builder /app/apps/web/node_modules ./apps/web/node_modules
COPY --from=web-builder /app/apps/web/.next ./apps/web/.next
COPY --from=web-builder /app/apps/web/public ./apps/web/public

ENV CAREFOLD_WORKSPACE=/app \
    CAREFOLD_DATA=/data \
    NODE_ENV=production \
    PORT=3000 \
    BACKEND_PORT=8000 \
    PYTHONUNBUFFERED=1

RUN mkdir -p /data

EXPOSE 8000 3000

# Copy startup script
RUN printf '#!/bin/sh\n\
uvicorn carefold.main:app --host 0.0.0.0 --port 8000 &\n\
BACKEND_PID=$!\n\
node node_modules/.bin/next start apps/web -p 3000 &\n\
WEB_PID=$!\n\
trap "kill -TERM $BACKEND_PID $WEB_PID" SIGINT SIGTERM\n\
wait $BACKEND_PID $WEB_PID\n' > /app/entrypoint.sh && chmod +x /app/entrypoint.sh

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')" || exit 1

CMD ["/app/entrypoint.sh"]
