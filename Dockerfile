FROM python:3.10-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV APP_NAME="pi-health-dashboard"
ENV APP_PORT=8080

# Install necessary packages
RUN apt-get update && \
    apt-get install -y python3-pip raspberrypi-kernel-headers libraspberrypi-bin && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy application files into the container
COPY ./ /app

# Install Python dependencies
RUN pip install --no-cache-dir flask psutil docker

# Expose the application port
EXPOSE 8080

# Command to run the Flask app
CMD ["python3", "app.py"]
