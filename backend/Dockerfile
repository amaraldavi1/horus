FROM python:3.11-slim

# curl is required by the docker-compose healthcheck. All Python dependencies
# (asyncpg, bcrypt, cryptography, lxml via onvif-zeep-async, uvloop) ship
# manylinux wheels for py3.11, so no compiler toolchain is needed.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

# Apply migrations, then start the API. `exec` makes uvicorn PID 1 so it
# receives SIGTERM for a clean shutdown.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
