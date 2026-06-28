import os
import tempfile

from werkzeug.security import generate_password_hash


TEST_RUNTIME_ROOT = os.path.join(
    tempfile.gettempdir(),
    f"limeos-test-runtime-{os.getpid()}",
)
os.environ["LIMEOS_CONFIG_DIR"] = os.path.join(TEST_RUNTIME_ROOT, "config")
os.environ["LIMEOS_STATE_DIR"] = os.path.join(TEST_RUNTIME_ROOT, "state")
os.environ["LIMEOS_LOG_DIR"] = os.path.join(TEST_RUNTIME_ROOT, "log")
os.environ["LIMEOS_CREDENTIALS_FILE"] = os.path.join(
    TEST_RUNTIME_ROOT,
    "config",
    "credentials.env",
)


TEST_USERNAME = os.getenv("PIHEALTH_USER", "admin")
TEST_PASSWORD = os.getenv("PIHEALTH_PASSWORD", "pihealth")
TEST_PASSWORD_HASH = generate_password_hash(
    TEST_PASSWORD,
    method="pbkdf2:sha256:600000",
)

# app.py validates credentials during import, so the test process must have an
# explicit hash before pytest imports application-backed test modules.
os.environ.pop("PIHEALTH_USERS", None)
os.environ.pop("PIHEALTH_PASSWORD", None)
os.environ["PIHEALTH_USER"] = TEST_USERNAME
os.environ["PIHEALTH_PASSWORD_HASH"] = TEST_PASSWORD_HASH
os.environ["PIHEALTH_TEST_PASSWORD"] = TEST_PASSWORD
