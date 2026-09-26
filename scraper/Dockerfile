# Official Playwright image ships Firefox/Chromium + all OS deps preinstalled,
# so we don't need to hand-roll apt-get chromium/chromium-driver like the old Selenium setup did.
# The image tag's version MUST match the `playwright` pin in requirements.txt —
# the pip package refuses to launch a browser build from a different version.
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Runs as the image's own non-root user rather than root (the Playwright base
# image's default) — Firefox launches fine under it with no extra sandbox
# flags (verified). Two log-dir paths because docker-compose and the k8s
# Deployment mount volumes at different paths (see docker-compose.yml vs.
# api.tf's APOLLO_LOG_DIR) — chowning both here covers a fresh container
# either way; a pre-existing Kubernetes PVC mounted over one still needs its
# own ownership fix — see api.tf's `fs_group` security context, which
# handles that at the volume level.
RUN mkdir -p /data/lake /data/logs /var/log/apollo && chown -R pwuser:pwuser /data /var/log/apollo /app
USER pwuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
