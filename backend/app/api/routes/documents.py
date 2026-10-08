from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import (
    CurrentUser,
    DbSession,
    EmbedderDep,
    SessionFactoryDep,
    SettingsDep,
    get_chunk_or_404,
    get_course_or_404,
    get_document_or_404,
)
from app.core.errors import AppError, ConflictError, NotFoundError
from app.models import Chunk, Document, DocumentStatus
from app.schemas.document import ChunkDetail, ChunkOut, DocumentOut, UploadError, UploadResult
from app.services.documents import delete_document_file, read_and_validate, store_document
from app.services.embeddings import embedding_signature
from app.services.ingestion import ingest_document

router = APIRouter(tags=["documents"])
MAX_FILES_PER_UPLOAD = 20
# Original uploads are private: never stored by browsers or shared caches.
PRIVATE_FILE_HEADERS = {"Cache-Control": "private, no-store"}


def _out(document: Document, signature: str) -> DocumentOut:
    out = DocumentOut.model_validate(document)
    out.needs_reindex = document.status == DocumentStatus.READY and document.embedding_signature != signature
    return out


@router.get("/courses/{course_id}/documents", response_model=list[DocumentOut], summary="List course materials")
def list_documents(course_id: str, db: DbSession, embedder: EmbedderDep, user: CurrentUser) -> list[DocumentOut]:
    get_course_or_404(db, course_id, user)
    signature = embedding_signature(embedder)
    documents = db.scalars(select(Document).where(Document.course_id == course_id).order_by(Document.created_at.desc()))
    return [_out(d, signature) for d in documents]


@router.post(
    "/courses/{course_id}/reindex",
    response_model=list[DocumentOut],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-index every document in a course (e.g. after changing the embedding model)",
)
def reindex_course(
    course_id: str,
    background_tasks: BackgroundTasks,
    db: DbSession,
    settings: SettingsDep,
    session_factory: SessionFactoryDep,
    embedder: EmbedderDep,
    user: CurrentUser,
) -> list[DocumentOut]:
    get_course_or_404(db, course_id, user)
    documents = list(
        db.scalars(
            select(Document).where(Document.course_id == course_id, Document.status != DocumentStatus.PROCESSING)
        )
    )
    for document in documents:
        document.status = DocumentStatus.PENDING
        document.error_message = None
    db.commit()
    for document in documents:
        background_tasks.add_task(ingest_document, session_factory, settings, embedder, document.id, owner_id=user.id)
    return [_out(d, embedding_signature(embedder)) for d in documents]


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
    user: CurrentUser,
    files: list[UploadFile] = File(..., description="One or more course files"),
) -> UploadResult:
    get_course_or_404(db, course_id, user)
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise AppError(f"Upload at most {MAX_FILES_PER_UPLOAD} files at a time.", code="too_many_files")

    created: list[Document] = []
    errors: list[tuple[AppError, str]] = []
    for upload in files:
        try:
            validated = await read_and_validate(upload, settings)
            if any(d.sha256 == validated.sha256 for d in created):
                raise ConflictError(f"'{validated.filename}' was included twice.", code="duplicate_document")
            try:
                document = store_document(db, settings, course_id, validated)
                db.commit()  # per file, so one failure can't roll back the others
            except IntegrityError as exc:
                # Two concurrent uploads of the same file: the unique constraint is the final arbiter.
                db.rollback()
                raise ConflictError(
                    f"'{validated.filename}' has already been uploaded to this course.", code="duplicate_document"
                ) from exc
            created.append(document)
        except AppError as exc:
            errors.append((exc, upload.filename or "upload"))

    if not created and errors:
        if len(errors) == 1:
            raise errors[0][0]
        raise AppError(
            "None of the files could be uploaded.",
            code="upload_failed",
            details=[{"filename": name, "code": e.code, "message": e.message} for e, name in errors],
        )

    for document in created:
        background_tasks.add_task(ingest_document, session_factory, settings, embedder, document.id, owner_id=user.id)
    return UploadResult(
        documents=[_out(d, embedding_signature(embedder)) for d in created],
        errors=[UploadError(filename=name, code=e.code, message=e.message) for e, name in errors],
    )


@router.get("/documents/{document_id}", response_model=DocumentOut, summary="Get document status")
def get_document(document_id: str, db: DbSession, embedder: EmbedderDep, user: CurrentUser) -> DocumentOut:
    return _out(get_document_or_404(db, document_id, user), embedding_signature(embedder))


@router.get("/chunks/{chunk_id}", response_model=ChunkDetail, summary="Full text of one indexed passage")
def get_chunk(chunk_id: str, db: DbSession, user: CurrentUser) -> ChunkDetail:
    chunk = get_chunk_or_404(db, chunk_id, user)
    detail = ChunkDetail.model_validate(chunk)
    detail.filename = chunk.document.filename
    detail.file_type = chunk.document.file_type
    return detail


@router.get("/documents/{document_id}/file", summary="Download/view the original file")
def get_document_file(document_id: str, db: DbSession, user: CurrentUser) -> FileResponse:
    document = get_document_or_404(db, document_id, user)
    path = Path(document.storage_path)
    if not path.exists():
        raise NotFoundError("The stored file is missing.")
    # Inline so PDFs open in the browser viewer, where '#page=N' deep links work.
    return FileResponse(
        path,
        media_type=document.mime_type,
        filename=document.filename,
        content_disposition_type="inline",
        headers=PRIVATE_FILE_HEADERS,
    )


@router.get("/documents/{document_id}/chunks", response_model=list[ChunkOut], summary="Inspect indexed chunks")
def list_chunks(
    document_id: str,
    db: DbSession,
    user: CurrentUser,
    page: int | None = Query(default=None, ge=1, description="Only chunks from this page/slide"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[Chunk]:
    get_document_or_404(db, document_id, user)
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
    user: CurrentUser,
) -> Document:
    document = get_document_or_404(db, document_id, user)
    if document.status == DocumentStatus.PROCESSING:
        raise ConflictError("This document is already being processed.")
    document.status = DocumentStatus.PENDING
    document.error_message = None
    db.commit()
    background_tasks.add_task(ingest_document, session_factory, settings, embedder, document.id, owner_id=user.id)
    return document


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a document")
def delete_document(document_id: str, db: DbSession, user: CurrentUser) -> Response:
    document = get_document_or_404(db, document_id, user)
    db.delete(document)
    db.commit()
    delete_document_file(document)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
