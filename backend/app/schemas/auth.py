from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ORMModel


class StrictModel(BaseModel):
    # Unknown fields are rejected (422), so a client can't sneak in "role", "is_active" or "owner_id".
    model_config = ConfigDict(extra="forbid")


class RegisterRequest(StrictModel):
    email: str = Field(max_length=320)
    # Upper bounds only stop absurd payloads; the real policy (PASSWORD_MIN/MAX_LENGTH) is checked server-side.
    # Passwords are never trimmed.
    password: str = Field(max_length=1024)
    password_confirm: str = Field(max_length=1024)
    display_name: str | None = Field(default=None, max_length=100)


class LoginRequest(StrictModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)
    remember_me: bool = False


class ForgotPasswordRequest(StrictModel):
    email: str = Field(max_length=320)


class ResetPasswordRequest(StrictModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(max_length=1024)
    password_confirm: str = Field(max_length=1024)


class UserOut(ORMModel):
    """Public view of an account — never includes the password hash or any token."""

    id: str
    email: str
    display_name: str | None
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


class AuthResponse(BaseModel):
    user: UserOut
    # The X-CSRF-Token value for this session (the session secret itself only lives in an HttpOnly cookie).
    csrf_token: str


class CsrfResponse(BaseModel):
    csrf_token: str


class MessageResponse(BaseModel):
    message: str


class AdminUserOut(UserOut):
    course_count: int = 0


class AdminUserUpdate(StrictModel):
    is_active: bool
