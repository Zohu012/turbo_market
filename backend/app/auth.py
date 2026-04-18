import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import settings

ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 7

_bearer = HTTPBearer()


def create_access_token(username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=TOKEN_EXPIRE_DAYS)
    return jwt.encode(
        {"sub": username, "exp": expire},
        settings.secret_key,
        algorithm=ALGORITHM,
    )


def verify_credentials(username: str, password: str) -> bool:
    ok_user = secrets.compare_digest(username, settings.app_username)
    ok_pass = secrets.compare_digest(password, settings.app_password)
    return ok_user and ok_pass


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> str:
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            credentials.credentials, settings.secret_key, algorithms=[ALGORITHM]
        )
        username: Optional[str] = payload.get("sub")
        if not username:
            raise exc
        return username
    except JWTError:
        raise exc
