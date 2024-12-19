# pi-health
RUN
docker run -d \
  -p 8080:8080 \
  -v /proc:/host_proc \
  -v /sys:/host_sys \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --name pi-health-dashboard \
  <your-docker-image>

DOCKER COMPOSE
pi-health-dashboard:
  image: brownster/pi-health:latest
  container_name: pi-health
  ports:
    - "8080:8080"
  volumes:
    - /proc:/host_proc:ro        # Mount the host's /proc directory (read-only)
    - /sys:/host_sys:ro          # Mount the host's /sys directory (read-only)
    - /var/run/docker.sock:/var/run/docker.sock # Mount Docker socket for container management
  restart: unless-stopped
