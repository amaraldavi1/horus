FROM python:3.11-slim

# ffmpeg does all decode/remux heavy lifting; the extra VAAPI/QSV driver
# packages make hardware decode available when /dev/dri is passed through
# (see docker-compose.yml). They are small and harmless on hosts without it.
# intel-media-va-driver-non-free lives in Debian's non-free component, so it
# is enabled first; the install falls back to the free driver if unavailable.
RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i 's/^Components: main.*/Components: main contrib non-free non-free-firmware/' \
            /etc/apt/sources.list.d/debian.sources; \
    fi \
    && apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libgl1 \
        libglib2.0-0 \
        va-driver-all \
        usbutils \
    && { apt-get install -y --no-install-recommends intel-media-va-driver-non-free \
         || apt-get install -y --no-install-recommends intel-media-va-driver \
         || echo "No Intel media driver available; QSV decode disabled"; } \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY engine ./engine
COPY models /models

ENV PYTHONUNBUFFERED=1 \
    MEDIA_ROOT=/media \
    MODEL_PATH=/models/yolov8n.onnx

# SIGTERM triggers a clean shutdown (workers + ffmpeg children).
STOPSIGNAL SIGTERM

CMD ["python", "-m", "engine.main"]
