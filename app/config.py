import base64
import os

VAULT_DIR = os.environ.get("VAULT_DIR", "/vault")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text:latest")
WHISPER_URL = os.environ.get("WHISPER_URL", "http://whisper:9000")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
AUTH_USERNAME = os.environ.get("AUTH_USERNAME", "sean")
AUTH_PASSWORD_HASH = os.environ.get("AUTH_PASSWORD_HASH", "")
# A real bcrypt hash starts with $2a/$2b/$2y. If AUTH_PASSWORD_HASH is empty or got
# mangled (e.g. PowerShell double-quotes eating the $ segments), fall back to the
# $-free base64 form so a broken value can never silently override the good one.
if not AUTH_PASSWORD_HASH.startswith("$2"):
    _b64 = os.environ.get("AUTH_PASSWORD_HASH_B64", "").strip()
    if _b64:
        AUTH_PASSWORD_HASH = base64.b64decode(_b64).decode()
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "true").lower() == "true"
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh")
# Where runtime settings (morning prompt config) are stored. Defaults inside the vault
# under .prayervault/ — add that folder to your vault's .gitignore if you don't want it synced.
SETTINGS_FILE = os.environ.get("SETTINGS_FILE", "")
SESSION_MAX_AGE = int(os.environ.get("SESSION_MAX_AGE", str(60 * 60 * 24 * 14)))
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "300"))

# --- Google sign-in / Drive backup (optional; features hidden when unset) ---
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
DOMAIN = os.environ.get("DOMAIN", "")
# Public base URL of the app (used for the OAuth redirect URI). Must match the
# redirect URI registered in Google Cloud Console exactly.
PUBLIC_URL = os.environ.get(
    "PUBLIC_URL", f"https://{DOMAIN}" if DOMAIN else "http://localhost:8000"
).rstrip("/")
# Where Google users' prayer folders live (the admin keeps VAULT_DIR).
USERS_DIR = os.environ.get("USERS_DIR", "users")

if not SESSION_SECRET:
    raise RuntimeError("SESSION_SECRET is not set. See .env.example.")
if not AUTH_PASSWORD_HASH:
    raise RuntimeError("AUTH_PASSWORD_HASH is not set. Run scripts/hash_password.py.")
