import hashlib

from fastapi import APIRouter, BackgroundTasks, Response, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, EmbedderDep, SessionFactoryDep, SettingsDep
from app.api.routes.courses import course_stats, to_out
from app.core.errors import NotFoundError
from app.models import Course
from app.schemas.course import CourseOut
from app.services.documents import ValidatedUpload, store_document
from app.services.ingestion import ingest_document
from app.services.parsing import SUPPORTED_TYPES, file_type_for

router = APIRouter(tags=["courses"])

DEMO_NAME = "Machine Learning Foundations"
DEMO_CODE = "ML 101 · demo"


@router.post(
    "/demo",
    response_model=CourseOut,
    summary="Create your demo course from the bundled sample materials (idempotent per user)",
    responses={201: {"description": "Demo course created"}, 200: {"description": "Demo course already exists"}},
)
def create_demo_course(
    response: Response,
    background_tasks: BackgroundTasks,
    db: DbSession,
    settings: SettingsDep,
    session_factory: SessionFactoryDep,
    embedder: EmbedderDep,
    user: CurrentUser,
) -> CourseOut:
    # Each user gets their own copy; the lookup is scoped to the caller so it never returns someone else's.
    existing = db.scalar(
        select(Course).where(Course.owner_id == user.id, Course.name == DEMO_NAME, Course.code == DEMO_CODE)
    )
    if existing is not None:
        return to_out(existing, course_stats(db, [existing.id])[existing.id])

    samples = (
        sorted(p for p in settings.demo_dir.glob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_TYPES)
        if settings.demo_dir.is_dir()
        else []
    )
    if not samples:
        raise NotFoundError("Demo materials are not available in this deployment.")

    course = Course(
        owner_id=user.id,
        name=DEMO_NAME,
        code=DEMO_CODE,
        term="Sample",
        description="Optimization, neural networks and regularization — a sample PDF lecture, slide deck and notes.",
        color="indigo",
    )
    db.add(course)
    db.flush()
    documents = []
    for path in samples:
        data = path.read_bytes()
        upload = ValidatedUpload(
            filename=path.name,
            file_type=file_type_for(path.name),
            mime_type=SUPPORTED_TYPES[path.suffix.lower()],
            data=data,
            sha256=hashlib.sha256(data).hexdigest(),
        )
        documents.append(store_document(db, settings, course.id, upload))
    db.commit()
    for document in documents:
        background_tasks.add_task(ingest_document, session_factory, settings, embedder, document.id, owner_id=user.id)
    response.status_code = status.HTTP_201_CREATED
    return to_out(course, course_stats(db, [course.id])[course.id])
