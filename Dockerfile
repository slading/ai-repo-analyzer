# Use a lightweight official Python image
FROM python:3.11-slim as base

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# Set the working directory inside the container
WORKDIR /app

# Install system dependencies if any are needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy only requirements first to leverage Docker caching
COPY requirements.txt .

# Install dependencies in the system site-packages (or inside container)
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application files
COPY src/ /app/src/
COPY tests/ /app/tests/
COPY example_run.py /app/example_run.py

# Create a non-root user and change file ownership for security
RUN useradd -u 8888 appuser && chown -R appuser:appuser /app
USER appuser

# Default command runs the main demo runner
CMD ["python", "example_run.py"]
