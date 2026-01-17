#!/bin/bash
# Run e2e tests with auto-started Flask app
# Used by tox -e all

set -e

PORT=${PORT:-8002}
BASE_URL=${BASE_URL:-http://localhost:$PORT}

# Start the app in background
PORT=$PORT python app.py &
APP_PID=$!

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

# Stop the app
kill $APP_PID 2>/dev/null || true

exit $TEST_EXIT_CODE
