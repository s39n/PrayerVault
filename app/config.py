import os

VAULT_DIR = os.environ.get("VAULT_DIR", "/vault")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
AUTH_USERNAME = os.environ.get("AUTH_USERNAME", "sean")
AUTH_PASSWORD_HASH = os.environ.get("AUTH_PASSWORD_HASH", "")
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "true").lower() == "true"
SESSION_MAX_AGE = int(os.environ.get("SESSION_MAX_AGE", str(60 * 60 * 24 * 14)))
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "300"))

if not SESSION_SECRET:
    raise RuntimeError("SESSION_SECRET is not set. See .env.example.")
if not AUTH_PASSWORD_HASH:
    raise RuntimeError("AUTH_PASSWORD_HASH is not set. Run scripts/hash_password.py.")
