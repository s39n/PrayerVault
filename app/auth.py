import time

import bcrypt
from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from . import config

_serializer = URLSafeTimedSerializer(config.SESSION_SECRET, salt="prayervault-session")

# --- Login rate limiting (in-memory, per IP) ---
_attempts: dict[str, list[float]] = {}
MAX_ATTEMPTS = 5
WINDOW_SECONDS = 15 * 60


def check_rate_limit(ip: str) -> None:
    now = time.time()
    recent = [t for t in _attempts.get(ip, []) if now - t < WINDOW_SECONDS]
    _attempts[ip] = recent
    if len(recent) >= MAX_ATTEMPTS:
        raise HTTPException(429, "Too many login attempts. Try again in 15 minutes.")


def record_failure(ip: str) -> None:
    _attempts.setdefault(ip, []).append(time.time())


def verify_credentials(username: str, password: str) -> bool:
    if username != config.AUTH_USERNAME:
        # Still run bcrypt to avoid timing side channel
        bcrypt.checkpw(b"x", bcrypt.hashpw(b"y", bcrypt.gensalt(4)))
        return False
    try:
        return bcrypt.checkpw(password.encode(), config.AUTH_PASSWORD_HASH.encode())
    except ValueError:
        return False


def create_session_token(username: str) -> str:
    return _serializer.dumps({"u": username})


def require_auth(request: Request) -> str:
    token = request.cookies.get("session")
    if not token:
        raise HTTPException(401, "Not authenticated")
    try:
        data = _serializer.loads(token, max_age=config.SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        raise HTTPException(401, "Session invalid or expired")
    return data["u"]
