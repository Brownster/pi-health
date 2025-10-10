# Pi-Health AI Assistant 🚀

**Smart system monitoring and AI-powered operations assistant for home servers and media centers.**

![image](https://github.com/user-attachments/assets/ea6db04f-52dd-4f5a-8576-731381744f56)

![image](https://github.com/user-attachments/assets/baa2c074-9298-4208-868c-b178bcee7a1d)

![image](https://github.com/user-attachments/assets/b0c4cb0e-308e-4ec2-8715-6a03082b99d5)

![image](https://github.com/user-attachments/assets/648c5ce6-f486-4e45-88a4-3157653a8533)

## 🎯 Quick Start

Get up and running in 3 simple steps:

```bash
# 1. Clone and setup
git clone <repository-url>
cd pi-health
./setup.sh

# 2. Add your OpenAI API key to .env (optional)
# Edit .env file: OPENAI_API_KEY=your_key_here

# 3. Start the application
python3 app.py
```

**That's it!** Visit http://localhost:8100 to access your dashboard.

### ✨ Features Available Immediately

- **System Monitoring**: Real-time CPU, memory, disk, and network stats
- **Container Management**: View and manage Docker containers (if available)
- **Smart Dashboard**: Login-protected web interface with responsive design
- **Resource Efficient**: AI assistant disabled by default to save resources

### 🤖 Enable AI Assistant (Optional)

1. Get an OpenAI API key from https://platform.openai.com/api-keys
2. Add it to your `.env` file: `OPENAI_API_KEY=your_key_here`
3. Set `ENABLE_AI_AGENT=true` in your `.env` file
4. Restart the application

The AI assistant can help with system troubleshooting, container management, and automated operations.


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

## Ops-Copilot AI Agent

The Ops-Copilot UI now talks to a lightweight AI agent that can aggregate telemetry
before answering questions. To enable cloud-backed responses, provide the following
environment variables when launching the app:

- `OPENAI_API_KEY` – API key for the OpenAI account the agent should use.
- `OPENAI_API_MODEL` (optional) – override the default `gpt-4o-mini` model name.

If the API key is omitted the agent runs in a safe offline mode, summarising the
available Model Context Protocol (MCP) tooling instead of calling the model. The
first MCP tool ships with this update and streams live system statistics into the
prompt, giving the AI immediate visibility into CPU, memory, disk, and temperature
data when analysing an incident.
