import os
import sys
import tempfile
from pathlib import Path

import pytest
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

os.environ.pop("PIHEALTH_USERS", None)
os.environ.pop("PIHEALTH_PASSWORD", None)
os.environ["PIHEALTH_USER"] = TEST_USERNAME
os.environ["PIHEALTH_PASSWORD_HASH"] = TEST_PASSWORD_HASH
os.environ["PIHEALTH_TEST_PASSWORD"] = TEST_PASSWORD

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import AppDependencies, create_app  # noqa: E402
from auth_utils import LoginRateLimiter  # noqa: E402
from operation_manager import OperationRegistry  # noqa: E402


@pytest.fixture
def app():
    dependencies = AppDependencies(
        users={TEST_USERNAME: TEST_PASSWORD_HASH},
        login_rate_limiter=LoginRateLimiter(),
        docker_client=None,
        operation_registry=OperationRegistry(),
    )
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "INIT_PLUGINS": False,
            "START_SCHEDULERS": False,
        },
        dependencies,
    )


@pytest.fixture
def client(app):
    with app.test_client() as test_client:
        yield test_client


@pytest.fixture
def authenticated_client(client):
    with client.session_transaction() as session:
        session["authenticated"] = True
        session["username"] = "testuser"
        session["csrf_token"] = "test-csrf-token"
    client.environ_base["HTTP_X_CSRF_TOKEN"] = "test-csrf-token"
    return client
