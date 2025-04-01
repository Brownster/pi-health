# pi-health

![image](https://github.com/user-attachments/assets/80bf8ed1-ad65-4255-85be-8d0ef8b20ab9)


RUN
docker run -d \
-p 8080:8080 \
-v /proc:/host_proc \
-v /sys:/host_sys \
-v /var/run/docker.sock:/var/run/docker.sock \
--name pi-health-dashboard \
brownster/pi-health:latest


DOCKER COMPOSE
services:
  pi-health-dashboard:
    image: brownster/pi-health:latest
    container_name: pi-health-dashboard
    environment:
      - TZ=${TIMEZONE}
      - DISK_PATH=/mnt/storage
      - DOCKER_COMPOSE_PATH=/config/docker-compose.yml
      - ENV_FILE_PATH=/config/.env
      - BACKUP_DIR=/config/backups
    ports:
      - 8080:8080
    volumes:
      - /proc:/host_proc:ro
      - /sys:/host_sys:ro
      - /var/run/docker.sock:/var/run/docker.sock
      - ./config:/config
      - /mnt/storage:/mnt/storage #disk to monitor for storage space
    restart: unless-stopped
