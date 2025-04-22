FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ADD . /app

ENV PATH="/app/.venv/bin:$PATH"

RUN uv sync --locked

EXPOSE 8080

CMD uv run espminer-optim
