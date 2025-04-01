# pi-health

![image](https://github.com/user-attachments/assets/ea6db04f-52dd-4f5a-8576-731381744f56)

![image](https://github.com/user-attachments/assets/baa2c074-9298-4208-868c-b178bcee7a1d)

![image](https://github.com/user-attachments/assets/b0c4cb0e-308e-4ec2-8715-6a03082b99d5)

![image](https://github.com/user-attachments/assets/648c5ce6-f486-4e45-88a4-3157653a8533)


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
