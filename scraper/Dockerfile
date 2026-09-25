# Official Playwright image ships Firefox/Chromium + all OS deps preinstalled,
# so we don't need to hand-roll apt-get chromium/chromium-driver like the old Selenium setup did.
# The image tag's version MUST match the `playwright` pin in requirements.txt —
# the pip package refuses to launch a browser build from a different version.
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
