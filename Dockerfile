FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.8.5 \
    POETRY_VIRTUALENVS_CREATE=false \
    ENVIRONMENT=production \
    LOCALSTORE_USE_CWD=True

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        ffmpeg \
        graphviz \
        libffi-dev \
        libglib2.0-0 \
        libgl1 \
        libgomp1 \
        libsndfile1 \
        nodejs \
    && python -m pip install --no-cache-dir --upgrade pip "poetry==${POETRY_VERSION}" \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml poetry.lock ./
RUN poetry install --only main --no-interaction --no-ansi
RUN python -m playwright install --with-deps chromium

COPY bot.py ./
COPY src ./src
COPY laws ./laws

RUN mkdir -p /app/data /app/cache /app/config

CMD ["python", "bot.py"]
