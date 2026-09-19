# syntax=docker/dockerfile:1.7
# One image: API + web UI + the collector package developers install from it.

# --- Web UI ---------------------------------------------------------------
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# --- Collector wheel (served to developers by the server itself) -----------
FROM python:3.12-slim AS collector
WORKDIR /collector
RUN pip install --no-cache-dir --disable-pip-version-check build==1.2.2
COPY collector/ ./
RUN python -m build --wheel --outdir /dist

# --- Server virtualenv -------------------------------------------------------
FROM python:3.12-slim AS server
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
RUN python -m venv /venv
COPY server/pyproject.toml /src/pyproject.toml
COPY server/src /src/src
RUN /venv/bin/pip install /src

# --- Runtime -----------------------------------------------------------------
FROM python:3.12-slim
LABEL org.opencontainers.image.title="Flockit" \
      org.opencontainers.image.description="Every coding session, human and AI, in one self-hosted view." \
      org.opencontainers.image.source="https://github.com/giladlevy1/flockit" \
      org.opencontainers.image.licenses="Apache-2.0"

ENV PATH="/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLOCKIT_WEB_DIST=/app/static \
    FLOCKIT_COLLECTOR_DIST=/app/collector

RUN useradd --system --uid 10001 --home /app flockit
COPY --from=server /venv /venv
COPY --from=web /web/dist /app/static
COPY --from=collector /dist /app/collector
USER flockit
WORKDIR /app
EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=2).status == 200 else 1)"

CMD ["flockit-server", "serve", "--host", "0.0.0.0", "--port", "8080"]
