from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.security import SAFE_METHODS, check_csrf_token, check_origin, csrf_token_for_session
from app.models import AuthSession, ChatSession, Chunk, Course, Document, Flashcard, FlashcardDeck, Quiz, User
from app.services import access
from app.services.auth import load_session
from app.services.embeddings import EmbeddingProvider
from app.services.llm import LLMBackend
from app.services.mailer import Mailer


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_session_factory(request: Request) -> sessionmaker[Session]:
    return request.app.state.session_factory


def get_db(request: Request) -> Iterator[Session]:
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_embedder(request: Request) -> EmbeddingProvider:
    return request.app.state.embedder


def get_llm(request: Request) -> LLMBackend:
    return request.app.state.llm


def get_mailer(request: Request) -> Mailer:
    return request.app.state.mailer


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
SessionFactoryDep = Annotated[sessionmaker[Session], Depends(get_session_factory)]
DbSession = Annotated[Session, Depends(get_db)]
EmbedderDep = Annotated[EmbeddingProvider, Depends(get_embedder)]
LLMDep = Annotated[LLMBackend, Depends(get_llm)]
MailerDep = Annotated[Mailer, Depends(get_mailer)]


# --- Authentication ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class AuthContext:
    """Who is calling. ``token`` is the raw session secret from the cookie, present only when it is valid."""

    user: User | None = None
    session: AuthSession | None = None
    token: str | None = None
    rejected: bool = False  # a session cookie was sent but is invalid, expired, revoked or idle


def get_auth(request: Request, db: DbSession, settings: SettingsDep) -> AuthContext:
    """Resolve the session cookie once per request (also called directly by the CSRF check)."""
    cached = getattr(request.state, "auth", None)
    if cached is not None:
        return cached
    context = AuthContext()
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        check = load_session(db, settings, token)
        context = (
            AuthContext(user=check.session.user, session=check.session, token=token)
            if check.session
            else AuthContext(rejected=True)
        )
    request.state.auth = context
    return context


AuthDep = Annotated[AuthContext, Depends(get_auth)]


def get_current_user(auth: AuthDep) -> User:
    if auth.user is None:
        if auth.rejected:
            raise AuthenticationError("Your session has expired. Please sign in again.", expired=True)
        raise AuthenticationError()
    return auth.user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> User:
    # The role is read from the database on every request, so a demotion takes effect immediately.
    if not user.is_admin:
        raise PermissionDeniedError("Administrator access is required.")
    return user


AdminUser = Annotated[User, Depends(require_admin)]


def csrf_protect(request: Request, db: DbSession, settings: SettingsDep) -> None:
    """Applied to every /api route. Safe methods pass; everything else needs a trusted Origin and the token."""
    if request.method in SAFE_METHODS:
        return
    check_origin(request, settings)
    auth = get_auth(request, db, settings)
    expected = csrf_token_for_session(auth.token) if auth.token else request.cookies.get(settings.csrf_cookie_name)
    check_csrf_token(request, expected)


# --- Ownership-scoped lookups (see app/services/access.py) -------------------------------------------------


def get_course_or_404(db: Session, course_id: str, user: User) -> Course:
    return access.owned_course(db, course_id, user.id)


def get_document_or_404(db: Session, document_id: str, user: User) -> Document:
    return access.owned_document(db, document_id, user.id)


def get_chunk_or_404(db: Session, chunk_id: str, user: User) -> Chunk:
    return access.owned_chunk(db, chunk_id, user.id)


def get_chat_or_404(db: Session, session_id: str, user: User) -> ChatSession:
    return access.owned_chat(db, session_id, user.id)


def get_quiz_or_404(db: Session, quiz_id: str, user: User) -> Quiz:
    return access.owned_quiz(db, quiz_id, user.id)


def get_deck_or_404(db: Session, deck_id: str, user: User) -> FlashcardDeck:
    return access.owned_deck(db, deck_id, user.id)


def get_card_or_404(db: Session, card_id: str, user: User) -> Flashcard:
    return access.owned_card(db, card_id, user.id)
