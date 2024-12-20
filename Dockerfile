FROM python:3.10-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV APP_NAME="pi-health-dashboard"
ENV APP_PORT=8080

# Install system dependencies
RUN apt-get update && \
    apt-get install -y python3-pip && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy all application files, including the static folder
COPY ./ /app

# Install Python dependencies from requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Expose the application port
EXPOSE 8080

# Command to run the Flask app
CMD ["python3", "app.py"]
