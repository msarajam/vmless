# Use an official slim Python image
FROM python:3.11-slim

# avoid buffering issues with Python prints
ENV PYTHONUNBUFFERED=1

# Install system deps (git, build tools if needed)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy only requirements first for better cache
COPY requirements.txt /app/requirements.txt

# Install Python deps
RUN pip install --upgrade pip \
 && pip install --no-cache-dir -r /app/requirements.txt

# Copy the application code
COPY . /app

# Expose the port
EXPOSE 9090

# Run with gunicorn (web_ui exposes the Flask `app` variable)
# Use 1 worker by default for simplicity; bump if needed.
CMD ["gunicorn", "--bind", "0.0.0.0:9090", "--workers", "1", "web_ui:app"]
