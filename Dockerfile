FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir xxhash

WORKDIR /app
COPY dedup.py .

ENTRYPOINT ["python", "/app/dedup.py", "/data"]
