#!/usr/bin/env bash
# Run e2e tests with auto-started Flask app
# Used by tox -e all

set -Eeuo pipefail

PORT=${PORT:-8002}
BASE_URL=${BASE_URL:-http://localhost:$PORT}
PIHEALTH_USER=${PIHEALTH_USER:-admin}
PIHEALTH_PASSWORD_HASH=${PIHEALTH_PASSWORD_HASH:-'pbkdf2:sha256:600000$WY9hNhygYgkvb3aQ$1d1076dc15e3201c5aaac3272ab5d7410097da87d8844ab9d5aa9e27e53ff465'}
export PIHEALTH_USER PIHEALTH_PASSWORD_HASH

RUNTIME_ROOT=$(mktemp -d)
LIMEOS_CONFIG_DIR=${LIMEOS_CONFIG_DIR:-${RUNTIME_ROOT}/config}
LIMEOS_STATE_DIR=${LIMEOS_STATE_DIR:-${RUNTIME_ROOT}/state}
LIMEOS_LOG_DIR=${LIMEOS_LOG_DIR:-${RUNTIME_ROOT}/log}
LIMEOS_CREDENTIALS_FILE=${LIMEOS_CREDENTIALS_FILE:-${LIMEOS_CONFIG_DIR}/credentials.env}
mkdir -p "$LIMEOS_CONFIG_DIR" "$LIMEOS_STATE_DIR" "$LIMEOS_LOG_DIR"
export LIMEOS_CONFIG_DIR LIMEOS_STATE_DIR LIMEOS_LOG_DIR LIMEOS_CREDENTIALS_FILE

set +e
python - "$PORT" <<'PY'
import socket
import sys

port = int(sys.argv[1])
try:
    sock = socket.socket()
    sock.bind(("127.0.0.1", port))
    sock.close()
    sys.exit(0)
except PermissionError:
    sys.exit(2)
except OSError:
    sys.exit(1)
PY
PORT_CHECK_EXIT=$?
set -e

if [ "$PORT_CHECK_EXIT" -eq 1 ]; then
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
elif [ "$PORT_CHECK_EXIT" -eq 2 ]; then
    echo "Port check skipped (socket permission denied); using $PORT for e2e."
fi

# Start the app in background
APP_LOG=$(mktemp)
env -u PIHEALTH_PASSWORD PORT=$PORT python app.py >"$APP_LOG" 2>&1 &
APP_PID=$!
trap 'kill "$APP_PID" 2>/dev/null || true; rm -f "$APP_LOG"; rm -rf "$RUNTIME_ROOT"' EXIT

# Wait for app to be ready (max 30 seconds)
echo "Waiting for app to start on port $PORT..."
for i in {1..30}; do
    if ! kill -0 "$APP_PID" 2>/dev/null; then
        if grep -q "PermissionError" "$APP_LOG" && grep -q "Operation not permitted" "$APP_LOG"; then
            echo "App failed to bind in sandbox; skipping e2e."
            exit 0
        fi
        echo "App failed to start."
        cat "$APP_LOG"
        exit 1
    fi
    if python -c "import urllib.request; urllib.request.urlopen('http://localhost:$PORT/login.html', timeout=1)" 2>/dev/null; then
        echo "App is ready!"
        break
    fi
    sleep 1
done

# Run e2e tests
set +e
E2E_OUTPUT=$(mktemp)
if (( $# > 0 )); then
    TEST_TARGETS=("$@")
else
    TEST_TARGETS=(tests/e2e)
fi
BASE_URL=$BASE_URL pytest -m e2e "${TEST_TARGETS[@]}" -v | tee "$E2E_OUTPUT"
TEST_EXIT_CODE=${PIPESTATUS[0]}
set -e

if [ "$TEST_EXIT_CODE" -ne 0 ]; then
    if grep -q "sandbox_host_linux.cc" "$E2E_OUTPUT" && grep -q "Operation not permitted" "$E2E_OUTPUT"; then
        echo "Playwright sandbox error detected; skipping e2e in this environment."
        rm -f "$E2E_OUTPUT"
        exit 0
    fi
fi

rm -f "$E2E_OUTPUT"

exit $TEST_EXIT_CODE
