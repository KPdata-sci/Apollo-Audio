# Standalone static front end, decoupled from the API (scraper/). Serves the
# same scraper/app/static/index.html but talks to the API over the network
# via window.APOLLO_API_BASE (see docker-entrypoint.d script below) instead of
# relying on same-origin relative fetches. Build context must be the repo
# root so this can reach scraper/app/static/ — see docker-compose.yml.
FROM nginx:1.27-alpine

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY scraper/app/static/index.html /usr/share/nginx/html/index.html
COPY frontend/40-apollo-config.sh /docker-entrypoint.d/40-apollo-config.sh
RUN chmod +x /docker-entrypoint.d/40-apollo-config.sh

# Explicit override for the API's origin, e.g. "https://api.example.com".
# Leave empty (the default) unless you have a reason to hardcode one — with
# it empty, the page instead derives the API's address at *runtime* from
# whatever host/IP the browser used to load this page, combined with
# API_PORT below. That's what makes one deployment work correctly whether a
# viewer reaches it via a LAN IP, a Tailscale IP, or localhost: those are all
# different addresses for the same box, and the API is reachable on the same
# one, just a different port — hardcoding one address here would only ever
# work for viewers on that one network path.
ENV API_BASE_URL=""
# The API's port on that same host — NodePort's api Service in
# infra/terraform-k8s/api.tf defaults to 30800; docker-compose's api service
# is 8000 (see docker-compose.yml, which overrides this).
ENV API_PORT="30800"

EXPOSE 80
