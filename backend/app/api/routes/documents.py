from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.api.deps import DbSession, EmbedderDep, SessionFactoryDep, SettingsDep, get_course_or_404
from app.core.errors import AppError, ConflictError, NotFoundError
from app.models import Chunk, Document, DocumentStatus
from app.schemas.document import ChunkOut, DocumentOut, UploadError, UploadResult
from app.services.documents import delete_document_file, read_and_validate, store_document
from app.services.ingestion import ingest_document

router = APIRouter(tags=["documents"])
MAX_FILES_PER_UPLOAD = 20


def _get_document(db: DbSession, document_id: str) -> Document:
    document = db.get(Document, document_id)
    if document is None:
        raise NotFoundError("Document not found.")
    return document


@router.get("/courses/{course_id}/documents", response_model=list[DocumentOut], summary="List course materials")
def list_documents(course_id: str, db: DbSession) -> list[Document]:
    get_course_or_404(db, course_id)
    return list(
        db.scalars(select(Document).where(Document.course_id == course_id).order_by(Document.created_at.desc()))
    )


@router.post(
    "/courses/{course_id}/documents",
    response_model=UploadResult,
    status_code=status.HTTP_201_CREATED,
    summary="Upload PDF / PPTX / DOCX / Markdown / TXT files",
    description="Files are validated and stored immediately; parsing, chunking and embedding run in the "
    "background. Poll the document status until it is `ready` or `failed`.",
)
async def upload_documents(
    course_id: str,
    background_tasks: BackgroundTasks,
    db: DbSession,
    settings: SettingsDep,
    session_factory: SessionFactoryDep,
    embedder: EmbedderDep,
    files: list[UploadFile] = File(..., description="One or more course files"),
) -> UploadResult:
    get_course_or_404(db, course_id)
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise AppError(f"Upload at most {MAX_FILES_PER_UPLOAD} files at a time.", code="too_many_files")

    created: list[Document] = []
    errors: list[tuple[AppError, str]] = []
    for upload in files:
        try:
            validated = await read_and_validate(upload, settings)
            if any(d.sha256 == validated.sha256 for d in created):
                raise ConflictError(f"'{validated.filename}' was included twice.", code="duplicate_document")
            created.append(store_document(db, settings, course_id, validated))
        except AppError as exc:
            errors.append((exc, upload.filename or "upload"))
    db.commit()

    if not created and errors:
        if len(errors) == 1:
            raise errors[0][0]
        raise AppError(
            "None of the files could be uploaded.",
            code="upload_failed",
            details=[{"filename": name, "code": e.code, "message": e.message} for e, name in errors],
        )

    for document in created:
        background_tasks.add_task(ingest_document, session_factory, settings, embedder, document.id)
    return UploadResult(
        documents=[DocumentOut.model_validate(d) for d in created],
        errors=[UploadError(filename=name, code=e.code, message=e.message) for e, name in errors],
    )


@router.get("/documents/{document_id}", response_model=DocumentOut, summary="Get document status")
def get_document(document_id: str, db: DbSession) -> Document:
    return _get_document(db, document_id)


@router.get("/documents/{document_id}/file", summary="Download/view the original file")
def get_document_file(document_id: str, db: DbSession) -> FileResponse:
    document = _get_document(db, document_id)
    path = Path(document.storage_path)
    if not path.exists():
        raise NotFoundError("The stored file is missing.")
    # Inline so PDFs open in the browser viewer, where '#page=N' deep links work.
    return FileResponse(
        path, media_type=document.mime_type, filename=document.filename, content_disposition_type="inline"
    )


@router.get("/documents/{document_id}/chunks", response_model=list[ChunkOut], summary="Inspect indexed chunks")
def list_chunks(
    document_id: str,
    db: DbSession,
    page: int | None = Query(default=None, ge=1, description="Only chunks from this page/slide"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[Chunk]:
    _get_document(db, document_id)
    stmt = select(Chunk).where(Chunk.document_id == document_id)
    if page is not None:
        stmt = stmt.where(Chunk.page_number == page)
    return list(db.scalars(stmt.order_by(Chunk.chunk_index).offset(offset).limit(limit)))


@router.post(
    "/documents/{document_id}/reprocess",
    response_model=DocumentOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-run parsing and indexing",
)
def reprocess_document(
    document_id: str,
    background_tasks: BackgroundTasks,
    db: DbSession,
    settings: SettingsDep,
    session_factory: SessionFactoryDep,
    embedder: EmbedderDep,
) -> Document:
    document = _get_document(db, document_id)
    if document.status == DocumentStatus.PROCESSING:
        raise ConflictError("This document is already being processed.")
    document.status = DocumentStatus.PENDING
    document.error_message = None
    db.commit()
    background_tasks.add_task(ingest_document, session_factory, settings, embedder, document.id)
    return document


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a document")
def delete_document(document_id: str, db: DbSession) -> Response:
    document = _get_document(db, document_id)
    db.delete(document)
    db.commit()
    delete_document_file(document)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
