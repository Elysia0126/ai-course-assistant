from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import UTCDateTime, new_id, utcnow


class Role(StrEnum):
    USER = "user"
    ADMIN = "admin"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('user', 'admin')", name="role"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    # Stored normalised (trimmed, lower-cased); the unique constraint is the final arbiter for concurrent sign-ups.
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20), default=Role.USER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    sessions: Mapped[list["AuthSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN


class AuthSession(Base):
    """A signed-in browser. The cookie holds a random token; only its SHA-256 digest is stored here, so a
    database leak can't be replayed as a login. (Not to be confused with ChatSession.)"""

    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    remember: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    # Drives the idle timeout; refreshed at most once a minute to keep reads cheap.
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    user: Mapped[User] = relationship(back_populates="sessions")


class PasswordResetToken(Base):
    """Single-use, short-lived. Like sessions, only the digest of the emailed token is stored."""

    __tablename__ = "password_reset_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    user: Mapped[User] = relationship()


class RateLimitCounter(Base):
    """One fixed-window counter. Shared by every API process through the database; no Redis needed."""

    __tablename__ = "rate_limit_counters"

    # SHA-256 of "<scope>:<identifier>:<window>", so raw IPs and emails aren't kept here.
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int] = mapped_column(default=0)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
