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


# --- AI usage limiting (in-memory, per user) ---
# With open Google signup anyone can create an account; this keeps one user
# from monopolizing the local model.
_ai_calls: dict[str, list[float]] = {}
AI_MAX_PER_HOUR = 30


def check_ai_limit(user: str) -> None:
    now = time.time()
    recent = [t for t in _ai_calls.get(user, []) if now - t < 3600]
    if len(recent) >= AI_MAX_PER_HOUR:
        _ai_calls[user] = recent
        raise HTTPException(429, "AI limit reached — please try again in an hour.")
    recent.append(now)
    _ai_calls[user] = recent


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
