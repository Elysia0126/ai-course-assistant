"""Upload validation and file storage."""

import hashlib
import io
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError, ConflictError, FileTooLargeError, UnsupportedFileError
from app.models import Document, DocumentStatus
from app.services.parsing import SUPPORTED_TYPES, file_type_for

_READ_BLOCK = 1024 * 1024
_ZIP_MAGIC = b"PK\x03\x04"


@dataclass
class ValidatedUpload:
    filename: str
    file_type: str
    mime_type: str
    data: bytes
    sha256: str


def _safe_filename(name: str | None) -> str:
    name = Path(name or "upload").name.strip() or "upload"
    return name[:255]


async def read_and_validate(upload: UploadFile, settings: Settings) -> ValidatedUpload:
    filename = _safe_filename(upload.filename)
    suffix = Path(filename).suffix.lower()
    if suffix in {".ppt", ".doc"}:
        raise UnsupportedFileError(
            f"Legacy {suffix} files are not supported. Save the file as {suffix}x and upload again."
        )
    if suffix not in SUPPORTED_TYPES:
        allowed = ", ".join(sorted({s for s in SUPPORTED_TYPES if s != ".markdown"}))
        raise UnsupportedFileError(f"'{filename}' is not a supported file type. Allowed: {allowed}.")

    chunks: list[bytes] = []
    size = 0
    while block := await upload.read(_READ_BLOCK):
        size += len(block)
        if size > settings.max_upload_bytes:
            raise FileTooLargeError(f"'{filename}' exceeds the {settings.max_upload_mb} MB upload limit.")
        chunks.append(block)
    data = b"".join(chunks)
    if not data:
        raise AppError(f"'{filename}' is empty.", code="empty_file")

    file_type = file_type_for(filename)
    # Cheap content sniffing catches renamed files before the parser chokes on them.
    if file_type == "pdf" and not data[:1024].lstrip().startswith(b"%PDF"):
        raise UnsupportedFileError(f"'{filename}' does not look like a valid PDF.")
    if file_type in {"pptx", "docx"}:
        if not data.startswith(_ZIP_MAGIC):
            raise UnsupportedFileError(f"'{filename}' does not look like a valid .{file_type} file.")
        # Office files are zip archives; refuse "zip bombs" that inflate far beyond their upload size.
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                expanded = sum(info.file_size for info in archive.infolist())
        except zipfile.BadZipFile as exc:
            raise UnsupportedFileError(f"'{filename}' is not a readable .{file_type} file.") from exc
        if expanded > settings.max_unzipped_mb * 1024 * 1024:
            raise FileTooLargeError(f"'{filename}' expands to more than {settings.max_unzipped_mb} MB.")

    return ValidatedUpload(
        filename=filename,
        file_type=file_type,
        mime_type=SUPPORTED_TYPES[suffix],
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
    )


def store_document(session: Session, settings: Settings, course_id: str, upload: ValidatedUpload) -> Document:
    existing = session.scalar(select(Document).where(Document.course_id == course_id, Document.sha256 == upload.sha256))
    if existing is not None:
        raise ConflictError(
            f"'{upload.filename}' has already been uploaded to this course (as '{existing.filename}').",
            code="duplicate_document",
            details={"document_id": existing.id},
        )

    document = Document(
        course_id=course_id,
        filename=upload.filename,
        file_type=upload.file_type,
        mime_type=upload.mime_type,
        size_bytes=len(upload.data),
        sha256=upload.sha256,
        storage_path="",
        status=DocumentStatus.PENDING,
    )
    session.add(document)
    session.flush()  # assigns the id used in the storage path

    course_dir = settings.upload_dir / course_id
    course_dir.mkdir(parents=True, exist_ok=True)
    path = course_dir / f"{document.id}.{upload.file_type}"
    path.write_bytes(upload.data)
    document.storage_path = str(path)
    return document


def delete_document_file(document: Document) -> None:
    Path(document.storage_path).unlink(missing_ok=True)


def delete_course_files(settings: Settings, course_id: str) -> None:
    shutil.rmtree(settings.upload_dir / course_id, ignore_errors=True)
