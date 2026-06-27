import importlib.util
from pathlib import Path

from werkzeug.security import check_password_hash


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "generate_password_hash.py"


def test_generated_password_hash_is_werkzeug_compatible():
    spec = importlib.util.spec_from_file_location("generate_password_hash", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    password_hash = module.generate_password_hash("correct horse battery staple")

    assert password_hash.startswith("pbkdf2:sha256:600000$")
    assert check_password_hash(password_hash, "correct horse battery staple")
    assert not check_password_hash(password_hash, "wrong")
