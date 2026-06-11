#!/bin/sh
# Keeps SSH local port-forwards open to cameras reachable only through a jump
# host. Each line of tunnels.conf becomes -L 0.0.0.0:LOCAL:CAMERA_IP:PORT, so
# other services reach the camera at camera-proxy:LOCAL.
set -eu

CONF=${TUNNELS_FILE:-/config/tunnels.conf}
if [ ! -f "$CONF" ]; then
    echo "[camera-proxy] FATAL: tunnel config not found at $CONF" >&2
    exit 1
fi
if [ -z "${SSH_HOST:-}" ] || [ -z "${SSH_USER:-}" ]; then
    echo "[camera-proxy] FATAL: TUNNEL_SSH_HOST / TUNNEL_SSH_USER not set in .env" >&2
    exit 1
fi

# ssh refuses keys readable by others; the bind mount may arrive as 0644.
install -m 600 /config/ssh_key /tmp/ssh_key

FORWARDS=""
COUNT=0
while IFS=" 	" read -r local_port remote_host remote_port _; do
    case "$local_port" in ""|\#*) continue ;; esac
    FORWARDS="$FORWARDS -L 0.0.0.0:$local_port:$remote_host:$remote_port"
    echo "[camera-proxy] tunnel: camera-proxy:$local_port -> $remote_host:$remote_port"
    COUNT=$((COUNT + 1))
done < "$CONF"

if [ "$COUNT" -eq 0 ]; then
    echo "[camera-proxy] FATAL: no tunnels configured in $CONF" >&2
    exit 1
fi

echo "[camera-proxy] connecting to ${SSH_USER}@${SSH_HOST}:${SSH_PORT:-22} with $COUNT tunnel(s)"
# autossh -M 0 relies on ServerAlive keepalives to detect dead connections and
# reconnect; ExitOnForwardFailure makes a refused forward restart the session.
exec autossh -M 0 -N -T \
    -o ServerAliveInterval=15 \
    -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes \
    -o StrictHostKeyChecking=accept-new \
    -o ConnectTimeout=10 \
    -i /tmp/ssh_key \
    -p "${SSH_PORT:-22}" \
    $FORWARDS \
    "${SSH_USER}@${SSH_HOST}"
