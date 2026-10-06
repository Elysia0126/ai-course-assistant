from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.errors import NotFoundError
from app.models import Course
from app.services.embeddings import EmbeddingProvider
from app.services.llm import LLMBackend


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


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
SessionFactoryDep = Annotated[sessionmaker[Session], Depends(get_session_factory)]
DbSession = Annotated[Session, Depends(get_db)]
EmbedderDep = Annotated[EmbeddingProvider, Depends(get_embedder)]
LLMDep = Annotated[LLMBackend, Depends(get_llm)]


def get_course_or_404(db: Session, course_id: str) -> Course:
    course = db.get(Course, course_id)
    if course is None:
        raise NotFoundError("Course not found.")
    return course
