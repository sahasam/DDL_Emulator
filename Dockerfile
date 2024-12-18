# Use official Python image as base
FROM python:3-slim

# Install system dependencies including git
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /deploy

# Copy deployment scripts and requirements
COPY requirements.txt /deploy/requirements.txt
RUN pip install --no-cache-dir --root-user-action=ignore -r requirements.txt

# Create directories
RUN mkdir -p /app /deploy/logs /root/.ssh

# Default command
CMD ["python3", "/app/main.py", "--config-file", "/deploy/config/node_config.yml"]