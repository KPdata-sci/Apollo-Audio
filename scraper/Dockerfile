# Official Playwright image ships Firefox/Chromium + all OS deps preinstalled,
# so we don't need to hand-roll apt-get chromium/chromium-driver like the old Selenium setup did.
# The image tag's version MUST match the `playwright` pin in requirements.txt —
# the pip package refuses to launch a browser build from a different version.
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
RUN chown -R pwuser:pwuser /app

# Runs the actual server as the image's own non-root pwuser rather than root
# (the Playwright base image's default) — Firefox launches fine under it
# with no extra sandbox flags (verified) — but the container itself still
# *starts* as root, via docker-entrypoint.sh, because the actual /data and
# log paths are volumes mounted at runtime (a docker-compose bind mount or a
# Kubernetes PVC), not something a build-time chown here can ever reach. The
# entrypoint fixes ownership of whatever's really mounted there, then drops
# to pwuser before exec'ing the real command — see that script's own comment
# for why this is a fresh-clone-breaking bug, not just a migration nicety.
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh
ENTRYPOINT ["/docker-entrypoint.sh"]

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
