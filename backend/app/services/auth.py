"""Accounts, password hashing, login sessions and password resets.

Passwords are hashed with Argon2id (pwdlib). Sessions and reset tokens are random 256-bit values handed to
the browser once; the database only keeps their SHA-256 digests.
"""

import logging
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache

from email_validator import EmailNotValidError, validate_email
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError, ConflictError, InputError, PermissionDeniedError
from app.core.security import new_token, token_digest
from app.db.types import utcnow
from app.models import AuthSession, PasswordResetToken, RateLimitCounter, Role, User

logger = logging.getLogger(__name__)

_password_hash = PasswordHash((Argon2Hasher(),))
# A session's last_seen_at is refreshed at most this often (idle-timeout precision vs. one write per request).
TOUCH_INTERVAL = timedelta(seconds=60)
# Revoked/expired sessions and used/expired reset tokens are kept this long for auditing, then purged.
RETENTION = timedelta(days=7)


class InvalidCredentialsError(AppError):
    status_code = 401
    code = "invalid_credentials"

    def __init__(self) -> None:
        # Deliberately identical for unknown emails and wrong passwords.
        super().__init__("Incorrect email or password.")


class InvalidResetTokenError(AppError):
    status_code = 400
    code = "invalid_reset_token"

    def __init__(self) -> None:
        super().__init__("This password reset link is invalid or has expired. Request a new one.")


# --- Normalisation & policy -------------------------------------------------------------------------------


def canonical_email(value: str) -> str:
    """The lookup key for an email address: trimmed and lower-cased."""
    return value.strip().lower()


def normalize_email(value: str) -> str:
    """Validate the syntax of a new address (no DNS lookups) and return its canonical form."""
    try:
        info = validate_email(value.strip(), check_deliverability=False)
    except EmailNotValidError as exc:
        raise InputError("email", "Enter a valid email address.") from exc
    return canonical_email(info.normalized)


def normalize_password(password: str) -> str:
    # NFKC so the same passphrase typed on different keyboards/IMEs hashes the same. Never trimmed.
    return unicodedata.normalize("NFKC", password)


def check_new_password(settings: Settings, password: str, confirm: str, *, email: str | None) -> str:
    """Length-based policy (no composition rules), then confirmation. Returns the normalised password."""
    normalized = normalize_password(password)
    if len(normalized) < settings.password_min_length:
        raise InputError("password", f"Use at least {settings.password_min_length} characters.")
    if len(normalized) > settings.password_max_length:
        raise InputError("password", f"Use at most {settings.password_max_length} characters.")
    if len(set(normalized)) < 3 or (email and normalized.casefold() == email.casefold()):
        raise InputError("password", "This password is too easy to guess.")
    if normalize_password(confirm) != normalized:
        raise InputError("password_confirm", "The passwords don't match.")
    return normalized


def hash_password(password: str) -> str:
    return _password_hash.hash(normalize_password(password))


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return _password_hash.hash("timing-equalisation-only")


def verify_password(password: str, password_hash: str | None) -> tuple[bool, str | None]:
    """(valid, rehashed). Unknown users still pay for one Argon2 verification, so timing doesn't reveal them."""
    if password_hash is None:
        _password_hash.verify(normalize_password(password), _dummy_hash())
        return False, None
    try:
        return _password_hash.verify_and_update(normalize_password(password), password_hash)
    except Exception:  # malformed hash in the database
        logger.warning("Unverifiable password hash encountered")
        return False, None


# --- Users -------------------------------------------------------------------------------------------------


def find_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == canonical_email(email)))


def create_user(
    db: Session,
    settings: Settings,
    *,
    email: str,
    password: str,
    password_confirm: str,
    display_name: str | None = None,
    role: Role = Role.USER,
) -> User:
    """Validate and insert a user (flushes, doesn't commit). Raises ConflictError for a taken email."""
    normalized_email = normalize_email(email)
    normalized_password = check_new_password(settings, password, password_confirm, email=normalized_email)
    name = (display_name or "").strip() or None
    if find_user_by_email(db, normalized_email) is not None:
        raise ConflictError("An account with this email already exists.", code="email_taken")
    user = User(
        email=normalized_email,
        password_hash=_password_hash.hash(normalized_password),
        display_name=name,
        role=role,
        is_active=True,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        # Two concurrent sign-ups with the same address: the unique constraint decides.
        db.rollback()
        raise ConflictError("An account with this email already exists.", code="email_taken") from exc
    return user


def authenticate(db: Session, email: str, password: str) -> User:
    user = find_user_by_email(db, email)
    valid, rehashed = verify_password(password, user.password_hash if user else None)
    if user is None or not valid:
        raise InvalidCredentialsError()
    if not user.is_active:
        # Only reachable with the right password, so this doesn't help enumerate accounts.
        raise PermissionDeniedError(
            "This account has been disabled. Contact an administrator.", code="account_disabled"
        )
    if rehashed:
        user.password_hash = rehashed
    return user


def active_admin_count(db: Session) -> int:
    return db.scalar(select(func.count(User.id)).where(User.role == Role.ADMIN, User.is_active.is_(True))) or 0


# --- Sessions ----------------------------------------------------------------------------------------------


def create_session(db: Session, settings: Settings, user: User, *, remember: bool) -> tuple[AuthSession, str]:
    """A brand-new random session (never reuses a client-supplied id: no session fixation)."""
    token = new_token()
    now = utcnow()
    ttl = settings.session_remember_ttl_seconds if remember else settings.session_ttl_seconds
    session = AuthSession(
        user_id=user.id,
        token_hash=token_digest(token),
        remember=remember,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(seconds=ttl),
    )
    db.add(session)
    user.last_login_at = now
    db.flush()
    return session, token


@dataclass(frozen=True)
class SessionCheck:
    session: AuthSession | None
    reason: str | None = None  # why an existing cookie was rejected


def load_session(db: Session, settings: Settings, token: str) -> SessionCheck:
    """Validate a session cookie: known, not revoked, not past its absolute or idle expiry, user active."""
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_digest(token)))
    if session is None:
        return SessionCheck(None, "unknown")
    now = utcnow()
    if session.revoked_at is not None:
        return SessionCheck(None, "revoked")
    if session.expires_at <= now:
        return SessionCheck(None, "expired")
    if session.last_seen_at + timedelta(seconds=settings.session_idle_timeout_seconds) <= now:
        session.revoked_at = now
        db.commit()
        return SessionCheck(None, "idle")
    if not session.user.is_active:
        session.revoked_at = now
        db.commit()
        return SessionCheck(None, "disabled")
    if now - session.last_seen_at >= TOUCH_INTERVAL:
        session.last_seen_at = now
        db.commit()
    return SessionCheck(session)


def revoke_user_sessions(db: Session, user_id: str) -> int:
    result = db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    return result.rowcount or 0


# --- Password reset ----------------------------------------------------------------------------------------


def create_reset_token(db: Session, settings: Settings, user: User) -> str:
    """Issue a single-use token; any older unused token of the same user stops working."""
    now = utcnow()
    db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
        .values(used_at=now)
    )
    token = new_token()
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=token_digest(token),
            created_at=now,
            expires_at=now + timedelta(seconds=settings.password_reset_ttl_seconds),
        )
    )
    db.flush()
    return token


def reset_password(db: Session, settings: Settings, token: str, password: str, password_confirm: str) -> User:
    """Consume a reset token and set a new password, atomically.

    The conditional UPDATE (``used_at IS NULL AND expires_at > now``) is the single point of truth: of two
    concurrent requests with the same token, only one can flip it, the other sees zero rows and fails.
    Every session of the user is revoked; the new password is not logged in automatically.
    """
    row = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == token_digest(token)))
    now = utcnow()
    if row is None or row.used_at is not None or row.expires_at <= now or not row.user.is_active:
        raise InvalidResetTokenError()
    user = row.user
    normalized = check_new_password(settings, password, password_confirm, email=user.email)

    consumed = db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.id == row.id,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
        .values(used_at=now)
        .execution_options(synchronize_session=False)
    )
    if consumed.rowcount != 1:
        db.rollback()
        raise InvalidResetTokenError()
    user.password_hash = _password_hash.hash(normalized)
    db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
        .values(used_at=now)
        .execution_options(synchronize_session=False)
    )
    revoke_user_sessions(db, user.id)
    db.commit()
    return user


# --- Housekeeping ------------------------------------------------------------------------------------------


def cleanup_expired(db: Session, *, now: datetime | None = None) -> dict[str, int]:
    """Delete dead sessions, reset tokens and rate-limit windows. Safe to run any time (cron/systemd timer)."""
    now = now or utcnow()
    cutoff = now - RETENTION
    removed = {
        "sessions": db.execute(
            delete(AuthSession).where(or_(AuthSession.expires_at < cutoff, AuthSession.revoked_at < cutoff))
        ).rowcount
        or 0,
        "reset_tokens": db.execute(
            delete(PasswordResetToken).where(
                or_(PasswordResetToken.expires_at < cutoff, PasswordResetToken.used_at < cutoff)
            )
        ).rowcount
        or 0,
        "rate_limit_counters": db.execute(delete(RateLimitCounter).where(RateLimitCounter.expires_at < now)).rowcount
        or 0,
    }
    db.commit()
    return removed
