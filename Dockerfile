FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY space/ ./space/
RUN mkdir -p policy

# Create data directory
RUN mkdir -p /data/receipts /data/policy

# Expose port
EXPOSE 7860

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV HF_RUNTIME_TOKEN=${HF_RUNTIME_TOKEN:-default-token-change-me}

# Run the application
CMD ["uvicorn", "space.app:app", "--host", "0.0.0.0", "--port", "7860"]
