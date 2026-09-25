# Standalone static front end, decoupled from the API (scraper/). Serves the
# same scraper/app/static/index.html but talks to the API over the network
# via window.APOLLO_API_BASE (see docker-entrypoint.d script below) instead of
# relying on same-origin relative fetches. Build context must be the repo
# root so this can reach scraper/app/static/ — see docker-compose.yml.
FROM nginx:1.27-alpine

COPY scraper/app/static/index.html /usr/share/nginx/html/index.html
COPY frontend/40-apollo-config.sh /docker-entrypoint.d/40-apollo-config.sh
RUN chmod +x /docker-entrypoint.d/40-apollo-config.sh

# The API's own reachable origin, e.g. "http://100.x.y.z:8000" for a Tailscale
# address or "https://api.example.com". Empty means "same origin as this
# page" — only correct if something in front (a reverse proxy) is merging the
# two under one origin; the plain docker-compose/k8s setups here don't do
# that, so set this explicitly.
ENV API_BASE_URL=""

EXPOSE 80
