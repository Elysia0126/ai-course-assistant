from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SourceRef(BaseModel):
    """Where a piece of an answer/question came from. ``index`` is the [n] citation number in answers."""

    index: int | None = None
    chunk_id: str | None = None
    document_id: str
    filename: str
    file_type: str
    page_number: int | None = None
    section: str | None = None
    location: str | None = None
    snippet: str
    score: float | None = None
    vector_score: float | None = None
    keyword_score: float | None = None
    cited: bool = False


class ErrorBody(BaseModel):
    code: str
    message: str
    details: object | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
