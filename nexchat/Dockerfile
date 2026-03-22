#  NexChat Dockerfile 
# Multi-stage build: keeps the final image lean.
# Daphne (ASGI) serves both HTTP and WebSocket traffic.
#
# Build context must be the nexchat/ directory:
#   docker compose up --build   (docker-compose.yml already sets this)

FROM python:3.11-slim AS base

# Prevent .pyc files and enable unbuffered stdout for clean Docker logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps — mysqlclient needs default-libmysqlclient-dev + gcc
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        default-libmysqlclient-dev \
        gcc \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

#  Dependencies 
FROM base AS deps

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

#  Final image 
FROM deps AS final

COPY . .

# Create logs directory so the app can write log files on startup
RUN mkdir -p logs

EXPOSE 8000

# collectstatic + migrate are run at container start (not build time)
# so that env vars (SECRET_KEY, DJANGO_ENV, etc.) are available.
# Daphne handles HTTP + WebSocket via ASGI.
CMD ["sh", "-c", \
    "python manage.py migrate --noinput && \
     python manage.py collectstatic --noinput && \
     uvicorn nexchat.asgi:application --host 0.0.0.0 --port 8000 --workers 4"]
