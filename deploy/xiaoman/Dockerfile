FROM node:22-bookworm-slim AS web
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/index.html web/tsconfig.json web/vite.config.ts ./
COPY web/src ./src
RUN npm run build -- --base=/study/

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 DATA_DIR=/app/data XIAOMAN_MVP=1
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements.lock ./
RUN pip install -r requirements.txt -c requirements.lock
COPY VERSION ./
COPY app ./app
COPY static ./static
COPY scripts ./scripts
COPY config ./config
COPY intents ./intents
COPY --from=web /build/web/dist ./web/dist
RUN mkdir -p /app/data
EXPOSE 8787
CMD ["sh", "-c", "uvicorn app.study.dashboard.release:app --host 0.0.0.0 --port ${PORT:-8787}"]
