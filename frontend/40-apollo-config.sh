#!/bin/sh
# Runs automatically at container start (nginx's own docker-entrypoint.sh
# executes every *.sh in /docker-entrypoint.d/ before starting nginx).
# Generates config.js from the API_BASE_URL/API_PORT env vars — see the
# comment on API_BASE_URL in ../frontend/Dockerfile for why this is a port,
# not a full baked-in address, by default.
set -eu

cat > /usr/share/nginx/html/config.js <<EOF
window.APOLLO_API_BASE = "${API_BASE_URL}";
window.APOLLO_API_PORT = "${API_PORT}";
EOF
