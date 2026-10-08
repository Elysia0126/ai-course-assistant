"""Registration, sign-in/out, the current user, CSRF tokens and password reset.

The session token is set as an HttpOnly cookie and never appears in a response body; responses carry only
the derived CSRF token the browser must echo in ``X-CSRF-Token``.
"""

from fastapi import APIRouter, BackgroundTasks, Request, Response, status

from app.api.deps import AuthDep, CurrentUser, DbSession, MailerDep, SettingsDep
from app.core.config import Settings
from app.core.errors import PermissionDeniedError, ServiceUnavailableError
from app.core.security import (
    clear_auth_cookies,
    clear_session_cookie,
    client_ip,
    csrf_token_for_session,
    is_well_formed_token,
    new_token,
    set_csrf_cookie,
    set_session_cookie,
)
from app.db.types import utcnow
from app.models import AuthSession, User
from app.schemas.auth import (
    AuthResponse,
    CsrfResponse,
    ForgotPasswordRequest,
    LoginRequest,
    MessageResponse,
    RegisterRequest,
    ResetPasswordRequest,
    UserOut,
)
from app.services import auth as auth_service
from app.services.mailer import deliver, password_reset_email
from app.services.rate_limit import RateLimiter

router = APIRouter(prefix="/auth", tags=["auth"])

RESET_REQUESTED = (
    "If an account exists for that email, we've sent a link to reset its password. Check your inbox and spam folder."
)


def _start_session(
    response: Response, db: DbSession, settings: Settings, user: User, *, remember: bool, previous: AuthSession | None
) -> AuthResponse:
    """Always a fresh session id (no fixation); the browser's previous session, if any, is revoked."""
    if previous is not None:
        previous.revoked_at = utcnow()
    session, token = auth_service.create_session(db, settings, user, remember=remember)
    db.commit()
    csrf = csrf_token_for_session(token)
    set_session_cookie(response, settings, token, session.expires_at)
    set_csrf_cookie(response, settings, csrf, session.expires_at)
    return AuthResponse(user=UserOut.model_validate(user), csrf_token=csrf)


@router.get("/csrf", response_model=CsrfResponse, summary="CSRF token to send as X-CSRF-Token")
def csrf(request: Request, response: Response, auth: AuthDep, settings: SettingsDep) -> CsrfResponse:
    if auth.token and auth.session:
        token = csrf_token_for_session(auth.token)
        set_csrf_cookie(response, settings, token, auth.session.expires_at)
    else:
        token = request.cookies.get(settings.csrf_cookie_name) or ""
        if not is_well_formed_token(token):
            token = new_token()
        set_csrf_cookie(response, settings, token)
    return CsrfResponse(csrf_token=token)


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account and sign in",
)
def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: DbSession,
    settings: SettingsDep,
    auth: AuthDep,
) -> AuthResponse:
    if not settings.registration_enabled:
        raise PermissionDeniedError(
            "Sign-up is closed on this server. Ask an administrator for an account.", code="registration_disabled"
        )
    RateLimiter(db, settings).hit("register:ip", client_ip(request, settings), "register_ip")
    user = auth_service.create_user(
        db,
        settings,
        email=payload.email,
        password=payload.password,
        password_confirm=payload.password_confirm,
        display_name=payload.display_name,
    )
    return _start_session(response, db, settings, user, remember=False, previous=auth.session)


@router.post("/login", response_model=AuthResponse, summary="Sign in with email and password")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DbSession,
    settings: SettingsDep,
    auth: AuthDep,
) -> AuthResponse:
    limiter = RateLimiter(db, settings)
    limiter.hit("login:ip", client_ip(request, settings), "login_ip")
    # Keyed on the normalised address whether or not the account exists, so the limit itself reveals nothing.
    account = auth_service.canonical_email(payload.email)
    limiter.check("login:account", account, "login_account")
    try:
        user = auth_service.authenticate(db, payload.email, payload.password)
    except auth_service.InvalidCredentialsError:
        limiter.hit("login:account", account, "login_account", enforce=False)
        raise
    limiter.reset("login:account", account, "login_account")
    return _start_session(response, db, settings, user, remember=payload.remember_me, previous=auth.session)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out (revokes this session)")
def logout(db: DbSession, settings: SettingsDep, auth: AuthDep) -> Response:
    if auth.session is not None:
        auth.session.revoked_at = utcnow()
        db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_auth_cookies(response, settings)
    return response


@router.get("/me", response_model=UserOut, summary="The signed-in user")
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Email a password-reset link (same answer whether or not the account exists)",
)
def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: DbSession,
    settings: SettingsDep,
    mailer: MailerDep,
) -> MessageResponse:
    if settings.mail_backend == "disabled":
        raise ServiceUnavailableError(
            "Password reset by email isn't set up on this server. Ask an administrator.",
            code="password_reset_unavailable",
        )
    limiter = RateLimiter(db, settings)
    limiter.hit("forgot:ip", client_ip(request, settings), "forgot_ip")
    email = auth_service.normalize_email(payload.email)
    limiter.hit("forgot:account", email, "forgot_account")
    user = auth_service.find_user_by_email(db, email)
    if user is not None and user.is_active:
        token = auth_service.create_reset_token(db, settings, user)
        db.commit()
        # Sent after the response, so the reply time doesn't depend on whether the account exists.
        background_tasks.add_task(deliver, mailer, password_reset_email(settings, user.email, token))
    return MessageResponse(message=RESET_REQUESTED)


@router.post("/reset-password", response_model=MessageResponse, summary="Set a new password with a reset token")
def reset_password(
    payload: ResetPasswordRequest,
    request: Request,
    response: Response,
    db: DbSession,
    settings: SettingsDep,
    auth: AuthDep,
) -> MessageResponse:
    RateLimiter(db, settings).hit("reset:ip", client_ip(request, settings), "reset_ip")
    user = auth_service.reset_password(db, settings, payload.token, payload.password, payload.password_confirm)
    if auth.session is not None and auth.session.user_id == user.id:
        clear_session_cookie(response, settings)  # that session was just revoked with all the others
    return MessageResponse(message="Your password has been changed. Sign in with your new password.")
