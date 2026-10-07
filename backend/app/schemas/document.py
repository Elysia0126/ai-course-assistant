from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import ORMModel


class DocumentOut(ORMModel):
    id: str
    course_id: str
    filename: str
    file_type: str
    size_bytes: int
    status: str
    error_message: str | None
    page_count: int | None
    chunk_count: int
    created_at: datetime
    processed_at: datetime | None
    embedding_signature: str | None = None
    # True when the document was indexed with a different embedding model than the one now configured.
    needs_reindex: bool = False


class UploadError(BaseModel):
    filename: str
    code: str
    message: str


class UploadResult(BaseModel):
    documents: list[DocumentOut]
    errors: list[UploadError]


class ChunkOut(ORMModel):
    id: str
    chunk_index: int
    content: str
    page_number: int | None
    section: str | None
    char_count: int


class ChunkDetail(ChunkOut):
    document_id: str
    filename: str = ""
    file_type: str = ""
