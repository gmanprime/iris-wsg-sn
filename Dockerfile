FROM python:3.13-slim

WORKDIR /app

# Install minimal system tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy and install pinned Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code, config, and fixtures
COPY . .

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Default command runs the offline fixture pipeline
CMD ["python", "src/cli.py", "--mode", "fixture"]
