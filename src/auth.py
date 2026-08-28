from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.config import JWT_ALGORITHM, JWT_EXPIRY_HOURS, JWT_SECRET_KEY
from src.users_store import get_user_by_username

# auto_error=False so a missing Authorization header reaches
# get_current_user() as None instead of FastAPI's default 403 -- criterion
# 3 requires 401 for both "no token" and "invalid token", not a mix of 403/401.
_security = HTTPBearer(auto_error=False)


def check_jwt_secret_configured() -> None:
    """JWT_SECRET_KEY is read (possibly as None) in config.py without
    validation. Checked here, once, at API startup -- same fail-fast
    pattern as indexer.check_qdrant_reachable() -- so a missing secret is
    an obvious startup error, not a confusing failure on the first
    login/signup call."""
    if not JWT_SECRET_KEY:
        raise RuntimeError(
            "JWT_SECRET_KEY is not set. Set it as an environment variable "
            "before starting the API (e.g. `setx JWT_SECRET_KEY <random-value>` "
            "on Windows, then reopen the shell)."
        )


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_access_token(username: str) -> str:
    payload = {
        "sub": username,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> str:
    """Returns the username ("sub" claim). Raises jwt.PyJWTError (or a
    subclass, e.g. ExpiredSignatureError) on an invalid/expired/malformed
    token -- caught by get_current_user() below, not handled here, so
    callers that don't need HTTP semantics (e.g. tests) can catch the
    plain jwt exception."""
    payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    return payload["sub"]


def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(_security)) -> dict:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        username = decode_access_token(credentials.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = get_user_by_username(username)
    if user is None:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return user
