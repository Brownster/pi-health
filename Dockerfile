# Use linuxserver.io base image
FROM lscr.io/linuxserver/baseimage:latest

# Set environment variables
ENV APP_NAME="pi-health-dashboard"
ENV APP_PORT=8080

# Copy application files
COPY ./ /app

# Set working directory
WORKDIR /app

# Expose the application port
EXPOSE ${APP_PORT}

# Command to run the Flask app
CMD ["python3", "app.py"]

