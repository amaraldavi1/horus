#!/bin/sh
# Enables the HTTPS server block only when certificates are mounted.
set -e

CRT=/etc/nginx/certs/server.crt
KEY=/etc/nginx/certs/server.key
SSL_CONF=/etc/nginx/horus/ssl.conf
TARGET=/etc/nginx/conf.d/ssl.conf

if [ -f "$CRT" ] && [ -f "$KEY" ]; then
    echo "horus: TLS certificates found — enabling HTTPS on :443"
    cp "$SSL_CONF" "$TARGET"
else
    echo "horus: no TLS certificates at /etc/nginx/certs — serving HTTP only"
    rm -f "$TARGET"
fi
