"""Administration commands. Run from backend/ (or `docker compose exec backend ...`):

    python -m app.cli create-user --email you@example.com --admin      # prompts for the password
    python -m app.cli set-role --email someone@example.com --role admin
    python -m app.cli set-active --email someone@example.com --disable
    python -m app.cli list-users
    python -m app.cli list-orphan-courses                                # courses from before accounts existed
    python -m app.cli assign-course --course-id <id> --email owner@example.com
    python -m app.cli assign-orphans --email owner@example.com --yes
    python -m app.cli validate-ownership                                 # once no orphans are left (PostgreSQL)
    python -m app.cli cleanup                                            # purge expired sessions/tokens/counters

Back up the database before changing ownership (see README → Accounts → Migrating existing data).
"""

import argparse
import getpass
import sys
from collections.abc import Callable

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.session import build_engine, build_session_factory
from app.models import Course, Role, User
from app.services import auth as auth_service


class CommandError(Exception):
    pass


def _user(db: Session, email: str) -> User:
    user = auth_service.find_user_by_email(db, email)
    if user is None:
        raise CommandError(f"No user with email {email!r}.")
    return user


def _read_password(args: argparse.Namespace) -> tuple[str, str]:
    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
        return password, password
    return getpass.getpass("Password: "), getpass.getpass("Repeat password: ")


def create_user(db: Session, settings: Settings, args: argparse.Namespace) -> str:
    password, confirm = _read_password(args)
    user = auth_service.create_user(
        db,
        settings,
        email=args.email,
        password=password,
        password_confirm=confirm,
        display_name=args.display_name,
        role=Role.ADMIN if args.admin else Role.USER,
    )
    db.commit()
    return f"Created {user.role} {user.email} ({user.id})."


def set_role(db: Session, settings: Settings, args: argparse.Namespace) -> str:
    user = _user(db, args.email)
    if (
        user.role == Role.ADMIN
        and args.role == Role.USER
        and user.is_active
        and auth_service.active_admin_count(db) <= 1
    ):
        raise CommandError("Refusing to demote the last active administrator.")
    user.role = args.role
    db.commit()
    return f"{user.email} is now {user.role}."


def set_active(db: Session, settings: Settings, args: argparse.Namespace) -> str:
    user = _user(db, args.email)
    if args.disable:
        if user.is_admin and user.is_active and auth_service.active_admin_count(db) <= 1:
            raise CommandError("Refusing to disable the last active administrator.")
        user.is_active = False
        revoked = auth_service.revoke_user_sessions(db, user.id)
        db.commit()
        return f"Disabled {user.email}; revoked {revoked} session(s)."
    user.is_active = True
    db.commit()
    return f"Enabled {user.email}."


def list_users(db: Session, settings: Settings, args: argparse.Namespace) -> str:
    rows = db.execute(
        select(User, func.count(Course.id))
        .outerjoin(Course, Course.owner_id == User.id)
        .group_by(User.id)
        .order_by(User.created_at)
    ).all()
    lines = [f"{'email':40} {'role':6} {'active':6} courses"]
    lines += [f"{u.email:40} {u.role:6} {'yes' if u.is_active else 'no':6} {n}" for u, n in rows]
    return "\n".join(lines)


def list_orphan_courses(db: Session, settings: Settings, args: argparse.Namespace) -> str:
    courses = db.scalars(select(Course).where(Course.owner_id.is_(None)).order_by(Course.created_at)).all()
    if not courses:
        return "No courses without an owner."
    return "\n".join(f"{c.id}  {c.name}  ({c.code or '-'}, created {c.created_at:%Y-%m-%d})" for c in courses)


def assign_course(db: Session, settings: Settings, args: argparse.Namespace) -> str:
    user = _user(db, args.email)
    course = db.get(Course, args.course_id)
    if course is None:
        raise CommandError(f"No course with id {args.course_id!r}.")
    if course.owner_id is not None and not args.force:
        raise CommandError("That course already has an owner; pass --force to transfer it.")
    course.owner_id = user.id
    db.commit()
    return f"Assigned '{course.name}' to {user.email}."


def assign_orphans(db: Session, settings: Settings, args: argparse.Namespace) -> str:
    if not args.yes:
        raise CommandError("This gives every ownerless course to one account. Re-run with --yes to confirm.")
    user = _user(db, args.email)
    result = db.execute(update(Course).where(Course.owner_id.is_(None)).values(owner_id=user.id))
    db.commit()
    return f"Assigned {result.rowcount or 0} course(s) to {user.email}."


def validate_ownership(db: Session, settings: Settings, args: argparse.Namespace) -> str:
    orphans = db.scalar(select(func.count(Course.id)).where(Course.owner_id.is_(None))) or 0
    if orphans:
        raise CommandError(f"{orphans} course(s) still have no owner. Assign them first (list-orphan-courses).")
    if db.get_bind().dialect.name != "postgresql":
        return "Every course has an owner. (The database-level check only exists on PostgreSQL.)"
    db.execute(text("ALTER TABLE courses VALIDATE CONSTRAINT ck_courses_owner_required"))
    db.commit()
    return "Every course has an owner; ck_courses_owner_required is now validated for all rows."


def cleanup(db: Session, settings: Settings, args: argparse.Namespace) -> str:
    removed = auth_service.cleanup_expired(db)
    return "Removed " + ", ".join(f"{count} {name.replace('_', ' ')}" for name, count in removed.items()) + "."


COMMANDS: dict[str, Callable[[Session, Settings, argparse.Namespace], str]] = {
    "create-user": create_user,
    "set-role": set_role,
    "set-active": set_active,
    "list-users": list_users,
    "list-orphan-courses": list_orphan_courses,
    "assign-course": assign_course,
    "assign-orphans": assign_orphans,
    "validate-ownership": validate_ownership,
    "cleanup": cleanup,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-user", help="create an account (prompts for the password)")
    p.add_argument("--email", required=True)
    p.add_argument("--display-name")
    p.add_argument("--admin", action="store_true", help="create an administrator")
    p.add_argument("--password-stdin", action="store_true", help="read the password from standard input")

    p = sub.add_parser("set-role", help="promote/demote an account")
    p.add_argument("--email", required=True)
    p.add_argument("--role", required=True, choices=[r.value for r in Role])

    p = sub.add_parser("set-active", help="enable or disable an account (disabling revokes its sessions)")
    p.add_argument("--email", required=True)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--enable", action="store_true")
    group.add_argument("--disable", action="store_true")

    sub.add_parser("list-users", help="list accounts")
    sub.add_parser("list-orphan-courses", help="list courses that have no owner yet")

    p = sub.add_parser("assign-course", help="give a course to an account")
    p.add_argument("--course-id", required=True)
    p.add_argument("--email", required=True)
    p.add_argument("--force", action="store_true", help="transfer a course that already has an owner")

    p = sub.add_parser("assign-orphans", help="give every ownerless course to one account")
    p.add_argument("--email", required=True)
    p.add_argument("--yes", action="store_true")

    sub.add_parser("validate-ownership", help="check that every course has an owner (and validate the constraint)")
    sub.add_parser("cleanup", help="delete expired sessions, reset tokens and rate-limit counters")
    return parser


def main(argv: list[str] | None = None, settings: Settings | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = settings or get_settings()
    engine = build_engine(settings.database_url)
    try:
        with build_session_factory(engine)() as db:
            print(COMMANDS[args.command](db, settings, args))
        return 0
    except (CommandError, AppError) as exc:
        print(f"error: {getattr(exc, 'message', exc)}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
