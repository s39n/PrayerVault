# Ensures the repo root (and thus the `app` package) is importable in tests.
import os
import tempfile

os.environ["SESSION_SECRET"] = "test-secret"
os.environ["AUTH_USERNAME"] = "sean"
# bcrypt hash of "testpass" generated at import time
import bcrypt  # noqa: E402

os.environ["AUTH_PASSWORD_HASH"] = bcrypt.hashpw(b"testpass", bcrypt.gensalt(4)).decode()
os.environ["VAULT_DIR"] = tempfile.mkdtemp()
os.environ["USERS_DIR"] = tempfile.mkdtemp()
os.environ["COOKIE_SECURE"] = "false"
