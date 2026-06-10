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
COPY alembic.ini entrypoint.sh ./
RUN chmod +x entrypoint.sh

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

# Waits for the database, applies migrations, then execs uvicorn.
CMD ["./entrypoint.sh"]
