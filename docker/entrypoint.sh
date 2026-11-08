#!/bin/sh
# TablePlan container entrypoint.
#
# The server runs as the unprivileged "tableplan" user (uid/gid 1000). Older
# releases ran as root, so an existing /data volume may be owned by root. When
# the container starts as root, hand /data to uid 1000 and drop privileges.
# If that is impossible (e.g. CAP_CHOWN dropped, read-only or squashed network
# share), keep running as root with a warning rather than failing to start.
set -eu

DATA_DIR="${DATA_DIR:-/data}"
RUN_USER=tableplan

if [ "$(id -u)" = "0" ]; then
  mkdir -p "$DATA_DIR"
  # Only walk the tree when something isn't already ours (cheap on every restart).
  if [ -n "$(find "$DATA_DIR" ! -user "$RUN_USER" -print 2>/dev/null | head -n 1)" ]; then
    echo "entrypoint: giving $DATA_DIR to $RUN_USER (uid 1000)" >&2
    chown -R "$RUN_USER:$RUN_USER" "$DATA_DIR" 2>/dev/null \
      || echo "entrypoint: warning: could not change ownership of $DATA_DIR" >&2
  fi
  if su-exec "$RUN_USER" test -w "$DATA_DIR"; then
    export HOME=/home/tableplan
    exec su-exec "$RUN_USER" "$@"
  fi
  echo "entrypoint: warning: $DATA_DIR is not writable by uid 1000; running as root" >&2
fi

exec "$@"
