from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORMModel

CourseColor = Literal["indigo", "blue", "emerald", "amber", "rose", "violet", "cyan", "slate"]


class CourseBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    code: str | None = Field(default=None, max_length=50)
    term: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=2000)
    color: CourseColor = "indigo"

    @field_validator("name", "code", "term", "description", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
        return value


class CourseCreate(CourseBase):
    @field_validator("code", "term", "description")
    @classmethod
    def _empty_to_none(cls, value: str | None) -> str | None:
        return value or None


class CourseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    code: str | None = Field(default=None, max_length=50)
    term: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=2000)
    color: CourseColor | None = None


class CourseStats(BaseModel):
    document_count: int = 0
    ready_document_count: int = 0
    chunk_count: int = 0
    quiz_count: int = 0
    deck_count: int = 0
    due_card_count: int = 0
    chat_count: int = 0


class CourseOut(ORMModel):
    id: str
    name: str
    code: str | None
    term: str | None
    description: str | None
    color: str
    created_at: datetime
    updated_at: datetime
    stats: CourseStats = Field(default_factory=CourseStats)
