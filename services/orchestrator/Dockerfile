# Orchestrator Service - Multi-Agent Browser Swarm Controller
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directory mount point
RUN mkdir -p /app/data

# Expose orchestrator port
EXPOSE 8100

# Health check
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8100/health || exit 1

# Run the orchestrator
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8100"]
