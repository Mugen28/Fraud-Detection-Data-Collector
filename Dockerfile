FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install system dependencies for build tools, TLS, and Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium and its required system OS libraries
RUN playwright install --with-deps chromium

# Copy project source code
COPY . .

RUN chmod +x /app/docker-entrypoint.sh

# Fail fast when a missing session file was mounted as a directory, then exec the pipeline.
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["python3", "run_pipeline.py"]

