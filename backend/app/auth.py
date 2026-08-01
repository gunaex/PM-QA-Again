import os
import secrets
import hashlib
import logging
from datetime import datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from . import models
from .database import get_master_db

logger = logging.getLogger("auth")

# JWT signing secret. In production this MUST be set via `fly secrets set` —
# never committed. Falls back to a per-process random secret for local dev
# so `uvicorn` still runs with zero config; that means restarting the dev
# server invalidates existing sessions, which is fine for local dev but is
# exactly why production needs a real, persistent one.
#
# QA-Again has its own JWT_SECRET_KEY, entirely separate from PM-Again's —
# no shared sessions between the two apps (rebuild prompt section 2).
JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
if not JWT_SECRET_KEY:
    JWT_SECRET_KEY = secrets.token_urlsafe(32)
    logger.warning(
        "JWT_SECRET_KEY not set — using an ephemeral per-process secret. "
        "Sessions will NOT survive a server restart. Set JWT_SECRET_KEY "
        "before deploying."
    )

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_MINUTES = 30
REFRESH_TOKEN_DAYS = 7

# Cookies must be Secure (HTTPS-only) in production, and SameSite=None so
# they're sent on cross-site requests (frontend on Cloudflare Pages, backend
# on Fly — different hostnames even under the same kanphong.com apex).
# Locally, the Vite dev server proxies same-origin, so Secure=False /
# SameSite=Lax works without needing HTTPS in dev.
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"
COOKIE_SAMESITE = "none" if COOKIE_SECURE else "lax"


# ---------- Password hashing ----------


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


# ---------- JWT access tokens ----------


def create_access_token(user: models.User) -> str:
    now = datetime.utcnow()
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Access token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid access token")
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")
    return payload


# ---------- Opaque refresh tokens (DB-backed, revocable) ----------


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def issue_refresh_token(db: Session, user: models.User) -> str:
    raw_token = secrets.token_urlsafe(48)
    record = models.RefreshToken(
        user_id=user.id,
        token_hash=_hash_token(raw_token),
        expires_at=datetime.utcnow() + timedelta(days=REFRESH_TOKEN_DAYS),
    )
    db.add(record)
    db.commit()
    return raw_token


def consume_refresh_token(db: Session, raw_token: str) -> models.RefreshToken:
    """Validates a refresh token and revokes it (rotation — each refresh
    issues a brand new refresh token, the old one can't be reused)."""
    token_hash = _hash_token(raw_token)
    record = (
        db.query(models.RefreshToken)
        .filter(models.RefreshToken.token_hash == token_hash, models.RefreshToken.revoked == False)  # noqa: E712
        .first()
    )
    if not record or record.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    record.revoked = True
    db.commit()
    return record


def revoke_refresh_token(db: Session, raw_token: str) -> None:
    token_hash = _hash_token(raw_token)
    record = db.query(models.RefreshToken).filter(models.RefreshToken.token_hash == token_hash).first()
    if record:
        record.revoked = True
        db.commit()


def set_auth_cookies(response, access_token: str, refresh_token: str) -> None:
    response.set_cookie(
        "access_token",
        access_token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=ACCESS_TOKEN_MINUTES * 60,
        path="/",
    )
    response.set_cookie(
        "refresh_token",
        refresh_token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=REFRESH_TOKEN_DAYS * 24 * 60 * 60,
        path="/api/auth",
    )


def clear_auth_cookies(response) -> None:
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/api/auth")


# ---------- FastAPI dependencies ----------


def _extract_access_token(request: Request) -> str | None:
    # Browser flow: httpOnly cookie. Also accept `Authorization: Bearer` so
    # the API can be exercised directly for testing.
    token = request.cookies.get("access_token")
    if token:
        return token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[len("Bearer ") :]
    return None


# Endpoints a user must still be able to reach even while must_change_password
# is set — otherwise they'd be locked out of the one flow that clears it.
_PASSWORD_CHANGE_EXEMPT_PATHS = {"/api/auth/me", "/api/auth/logout", "/api/auth/change-password"}


def get_current_user(request: Request, db: Session = Depends(get_master_db)) -> models.User:
    token = _extract_access_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_access_token(token)
    user = db.query(models.User).filter(models.User.id == int(payload["sub"])).first()
    if not user or not user.active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    if user.must_change_password and request.url.path not in _PASSWORD_CHANGE_EXEMPT_PATHS:
        raise HTTPException(status_code=403, detail="password_change_required")
    return user


def require_roles(*roles: str):
    """Dependency factory: 403s if the current user's role isn't in `roles`.
    Still requires a valid token first (get_current_user 401s before this
    ever runs), so unauthenticated requests get 401, not 403."""

    def checker(user: models.User = Depends(get_current_user)) -> models.User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail=f"Role '{user.role}' is not permitted to perform this action")
        return user

    return checker


# Convenience: anyone logged in except VIEWER — blocks the read-only role
# from write endpoints. TESTER/ADMIN can execute; only ADMIN manages users
# and projects (see require_admin).
require_tester = require_roles("ADMIN", "TESTER")
require_admin = require_roles("ADMIN")


# ---------- Runner tokens (HYB-0) ----------
# A separate credential namespace from user sessions — a QA Runner process
# is not a person and should never hold a user's cookie/JWT. See
# docs/hybrid/HYB-0-GAP-ANALYSIS.md section 5 decision 2.


def issue_runner_token(db: Session, label: str) -> tuple[str, models.RunnerToken]:
    raw_token = secrets.token_urlsafe(32)
    record = models.RunnerToken(label=label, token_hash=_hash_token(raw_token))
    db.add(record)
    db.commit()
    db.refresh(record)
    return raw_token, record


def get_current_runner(request: Request, db: Session = Depends(get_master_db)) -> models.RunnerToken:
    raw_token = request.headers.get("X-Runner-Token")
    if not raw_token:
        raise HTTPException(status_code=401, detail="Missing X-Runner-Token header")
    record = (
        db.query(models.RunnerToken)
        .filter(models.RunnerToken.token_hash == _hash_token(raw_token), models.RunnerToken.revoked == False)  # noqa: E712
        .first()
    )
    if not record:
        raise HTTPException(status_code=401, detail="Invalid or revoked runner token")
    # HYB-2: every authenticated runner call counts as a liveness signal
    # — no separate heartbeat call is required just to stay ONLINE,
    # though the runner still sends explicit heartbeats while idle
    # between jobs (see runner/src/execution/*).
    record.last_heartbeat_at = datetime.utcnow()
    db.commit()
    return record


def revoke_runner_token(db: Session, token_id: int) -> models.RunnerToken:
    record = db.query(models.RunnerToken).filter(models.RunnerToken.id == token_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Runner token not found")
    record.revoked = True
    db.commit()
    db.refresh(record)
    return record
