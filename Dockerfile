FROM python:3.12-alpine

ARG VERSION=dev
LABEL org.opencontainers.image.title="TablePlan" \
      org.opencontainers.image.description="Household recipes, meal plans, smart pantry and grocery lists" \
      org.opencontainers.image.source="https://github.com/thomasjvalenzuela/tableplan" \
      org.opencontainers.image.version="${VERSION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    LISTEN_PORT=8080

# tzdata so TZ=America/Chicago etc. gives correct local dates for use-by math
RUN apk add --no-cache tzdata
# yt-dlp reads public Instagram / TikTok / YouTube / Facebook recipe videos (caption + audio)
RUN pip install --no-cache-dir -U yt-dlp

WORKDIR /app
COPY app/ /app/
RUN echo "${VERSION}" > /app/VERSION && python -m compileall -q /app

VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4)"

CMD ["python", "-I", "/app/server.py"]
