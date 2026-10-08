"""Minimal administration: list accounts and enable/disable them.

Admins are created or promoted only with the CLI (``python -m app.cli create-user --admin`` /
``set-role``); there is no default admin and the first sign-up is an ordinary user. Course data stays
private even to admins: these endpoints expose account metadata, never course content.
"""

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import AdminUser, DbSession
from app.core.errors import ConflictError, NotFoundError
from app.models import Course, User
from app.schemas.auth import AdminUserOut, AdminUserUpdate
from app.services.auth import active_admin_count, revoke_user_sessions

router = APIRouter(prefix="/admin", tags=["admin"])


def _out(user: User, course_count: int) -> AdminUserOut:
    return AdminUserOut.model_validate(user).model_copy(update={"course_count": course_count})


def _course_count(db: DbSession, user_id: str) -> int:
    return db.scalar(select(func.count(Course.id)).where(Course.owner_id == user_id)) or 0


@router.get("/users", response_model=list[AdminUserOut], summary="List accounts (admin only)")
def list_users(
    admin: AdminUser,
    db: DbSession,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[AdminUserOut]:
    rows = db.execute(
        select(User, func.count(Course.id))
        .outerjoin(Course, Course.owner_id == User.id)
        .group_by(User.id)
        .order_by(User.created_at)
        .limit(limit)
        .offset(offset)
    ).all()
    return [_out(user, count) for user, count in rows]


@router.patch("/users/{user_id}", response_model=AdminUserOut, summary="Enable or disable an account (admin only)")
def update_user(user_id: str, payload: AdminUserUpdate, admin: AdminUser, db: DbSession) -> AdminUserOut:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found.")
    if not payload.is_active and user.is_active:
        if user.id == admin.id:
            raise ConflictError("You can't disable your own account.", code="cannot_disable_self")
        if user.is_admin and active_admin_count(db) <= 1:
            raise ConflictError("At least one active administrator must remain.", code="last_admin")
        user.is_active = False
        revoke_user_sessions(db, user.id)  # signed out everywhere, immediately
    elif payload.is_active:
        user.is_active = True
    db.commit()
    return _out(user, _course_count(db, user.id))
