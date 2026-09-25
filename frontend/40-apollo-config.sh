#!/bin/sh
# Runs automatically at container start (nginx's own docker-entrypoint.sh
# executes every *.sh in /docker-entrypoint.d/ before starting nginx).
# Generates config.js from the API_BASE_URL env var so the API's address can
# be set per-deployment (docker-compose / k8s manifest) without rebuilding
# this image.
set -eu

cat > /usr/share/nginx/html/config.js <<EOF
window.APOLLO_API_BASE = "${API_BASE_URL}";
EOF
