# syntax=docker/dockerfile:1.7
FROM public.ecr.aws/docker/library/python:3.13.14-slim-trixie

WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN apt-get update \
    && apt-get -y upgrade \
    && apt-get install -y --no-install-recommends bash \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

ARG BUILD_ENV=PROD

COPY pyproject.toml uv.lock ./
RUN if [ "$BUILD_ENV" = "DEV" ] || [ "$BUILD_ENV" = "dev" ]; then \
        uv sync --frozen; \
    else \
        uv sync --frozen --no-dev; \
    fi

COPY . /app

EXPOSE 80

CMD ["bin/boot.sh"]
