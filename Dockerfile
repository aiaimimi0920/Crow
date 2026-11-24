ARG PYTHON_BASE_IMAGE=python:3.12-slim@sha256:a0e2dd78cc679ddfffea960fe45ecfcff9ac2f68d67917a0edfcde5c2100151b
ARG NODE_BASE_IMAGE=node:22-alpine@sha256:b6f26b36c8ff49624cfdac716b8ea1138d606df02586a77d364bb5536a634f85

FROM ${NODE_BASE_IMAGE} AS collector_desktop_builder

WORKDIR /collector-desktop

COPY collector-desktop/package*.json ./
RUN npm ci

COPY collector-desktop/index.html ./index.html
COPY collector-desktop/src ./src
RUN npm run build

FROM ${PYTHON_BASE_IMAGE}

ARG FAPAI_BUILD_VERSION=development
ARG FAPAI_BUILD_COMMIT=unknown
ARG FAPAI_BUILD_TIME=unknown
ARG FAPAI_SOURCE_DIGEST=unknown

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    FAPAI_RUN_MODE=seed-collector \
    FAPAI_OUTPUT_DIR=/data/output/seed_collector \
    FAPAI_CDP_ENDPOINT=http://host.docker.internal:9223

WORKDIR /app

COPY requirements.txt requirements.lock ./
COPY vendor/wheels/ /tmp/wheels/
RUN if [ -d /tmp/wheels ] && [ "$(find /tmp/wheels -type f -name '*.whl' | head -n 1)" ]; then \
        pip install --no-cache-dir --require-hashes --no-index --find-links=/tmp/wheels -r requirements.lock; \
    else \
        pip install --no-cache-dir --require-hashes -r requirements.lock; \
    fi \
    && playwright install --with-deps chromium

ENV FAPAI_BUILD_VERSION=${FAPAI_BUILD_VERSION} \
    FAPAI_BUILD_COMMIT=${FAPAI_BUILD_COMMIT} \
    FAPAI_BUILD_TIME=${FAPAI_BUILD_TIME} \
    FAPAI_SOURCE_DIGEST=${FAPAI_SOURCE_DIGEST}

COPY . .
COPY --from=collector_desktop_builder /collector-desktop/dist /app/collector-desktop/dist

RUN mkdir -p /data/output /data/datas /data/jobs /data/secrets \
    && mkdir -p /app/output /app/jobs \
    && if [ ! -e /app/datas ]; then ln -s /data/datas /app/datas; fi

EXPOSE 8001

CMD ["python", "tools/docker_entrypoint.py"]
