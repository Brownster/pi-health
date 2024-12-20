FROM python:3.10-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV APP_NAME="pi-health-dashboard"
ENV APP_PORT=8080

# Install Python dependencies
RUN apt-get update && \
    apt-get install -y python3-pip && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy application files into the container
COPY ./ /app

# Install Python libraries from requirements.txt
RUN pip install -r requirements.txt

# Expose the application port
EXPOSE 8080

# Command to run the Flask app
CMD ["python3", "app.py"]
