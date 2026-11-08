# TablePlan: Python standard library server + vanilla JS PWA.
# Pinned to the 3.12 / Alpine line; Dependabot proposes base-image updates.
FROM python:3.12-alpine

ARG VERSION=dev
LABEL org.opencontainers.image.title="TablePlan" \
      org.opencontainers.image.description="Household recipes, meal plans, smart pantry and grocery lists" \
      org.opencontainers.image.source="https://github.com/thomasjvalenzuela/tableplan" \
      org.opencontainers.image.licenses="AGPL-3.0-only" \
      org.opencontainers.image.version="${VERSION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    LISTEN_PORT=8080

# tzdata: TZ=America/Chicago etc. gives correct local dates for use-by math
# su-exec: lets the entrypoint fix /data ownership, then drop to the unprivileged user
RUN apk add --no-cache tzdata su-exec \
 && addgroup -g 1000 -S tableplan \
 && adduser -u 1000 -S -D -G tableplan -h /home/tableplan -s /sbin/nologin tableplan \
 && mkdir -p /data \
 && chown tableplan:tableplan /data

# yt-dlp reads public Instagram / TikTok / YouTube / Facebook recipe videos (caption + audio)
COPY docker/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

WORKDIR /app
COPY app/ /app/
COPY docker/entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN echo "${VERSION}" > /app/VERSION \
 && python -m compileall -q /app \
 && chmod 0755 /usr/local/bin/docker-entrypoint.sh

VOLUME /data
EXPOSE 8080

# Honours PORT (Railway and similar), then LISTEN_PORT, then 8080.
HEALTHCHECK --interval=60s --timeout=5s --start-period=15s --retries=3 \
  CMD ["sh", "-c", "python -I -c \"import sys, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + sys.argv[1] + '/health', timeout=4)\" \"${PORT:-${LISTEN_PORT:-8080}}\""]

# The container starts as root only long enough for the entrypoint to make /data
# owned by uid 1000 (older installs created it as root); the server then runs as
# the unprivileged "tableplan" user.
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "-I", "/app/server.py"]
