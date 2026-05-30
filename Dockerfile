# Use an official Python runtime as a parent image
FROM python:3.13-slim

# Set the working directory in the container
WORKDIR /app

# Install system dependencies required for building some python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Create the data and tokens directories
RUN mkdir -p /app/data /app/tokens

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV GARMINCONNECT_TOKENS=/app/tokens

# Set entrypoint to run the CLI
ENTRYPOINT ["python", "cli/garmin_ai_coach_cli.py"]
CMD ["--help"]
