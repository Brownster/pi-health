#!/bin/bash
# Run e2e tests with auto-started Flask app
# Used by tox -e all

set -e

PORT=${PORT:-8002}
BASE_URL=${BASE_URL:-http://localhost:$PORT}

if ! python - "$PORT" <<'PY'
import socket, sys
port = int(sys.argv[1])
sock = socket.socket()
try:
    sock.bind(("127.0.0.1", port))
    sock.close()
    sys.exit(0)
except OSError:
    sys.exit(1)
PY
then
    PORT=$(python - <<'PY'
import socket
sock = socket.socket()
sock.bind(("127.0.0.1", 0))
port = sock.getsockname()[1]
sock.close()
print(port)
PY
)
    BASE_URL="http://localhost:$PORT"
    echo "Port 8002 busy, using $PORT for e2e."
fi

# Start the app in background
PORT=$PORT python app.py &
APP_PID=$!
trap 'kill $APP_PID 2>/dev/null || true' EXIT

# Wait for app to be ready (max 30 seconds)
echo "Waiting for app to start on port $PORT..."
for i in {1..30}; do
    if python -c "import urllib.request; urllib.request.urlopen('http://localhost:$PORT/api/theme', timeout=1)" 2>/dev/null; then
        echo "App is ready!"
        break
    fi
    sleep 1
done

# Run e2e tests
BASE_URL=$BASE_URL pytest -m e2e tests/e2e -v
TEST_EXIT_CODE=$?

exit $TEST_EXIT_CODE
