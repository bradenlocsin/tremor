# TREMOR: one container runs the Streamlit dashboard and the job scheduler (ADR-0016).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    TREMOR_DB=/data/tremor.sqlite

COPY --from=ghcr.io/astral-sh/uv:0.13.4 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY config ./config
COPY src ./src
RUN uv sync --frozen --no-dev

COPY deploy/start.sh /start.sh
RUN chmod +x /start.sh

EXPOSE 8501
CMD ["/start.sh"]
