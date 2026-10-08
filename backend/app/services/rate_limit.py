"""Fixed-window rate limiting stored in the application database.

Counters live in ``rate_limit_counters`` and are bumped with an atomic upsert, so the limits hold across
several API processes/containers without extra infrastructure. Keys are SHA-256 digests of
``scope:identifier:window``, so neither IP addresses nor email addresses are stored in clear.
"""

import hashlib
import math
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from app.core.config import RateRule, Settings
from app.core.errors import RateLimitedError
from app.db.types import utcnow
from app.models import RateLimitCounter


class RateLimiter:
    def __init__(self, db: Session, settings: Settings):
        self.db = db
        self.settings = settings

    def _window(self, scope: str, identifier: str, rule: RateRule, now: datetime) -> tuple[str, datetime, int]:
        start = int(now.timestamp()) // rule.window * rule.window
        key = hashlib.sha256(f"{scope}:{identifier}:{rule.window}:{start}".encode()).hexdigest()
        expires_at = datetime.fromtimestamp(start + rule.window, UTC)
        retry_after = math.ceil((expires_at - now).total_seconds())
        return key, expires_at, retry_after

    def hit(self, scope: str, identifier: str, rule_name: str, *, enforce: bool = True) -> None:
        """Count one attempt and (if ``enforce``) raise 429 once the window's limit is exceeded. Commits
        immediately, so the attempt still counts if the request fails afterwards."""
        if not self.settings.rate_limit_enabled:
            return
        rule = self.settings.rate_rule(rule_name)
        key, expires_at, retry_after = self._window(scope, identifier, rule, utcnow())
        dialect = self.db.get_bind().dialect.name
        insert = {"postgresql": postgresql.insert, "sqlite": sqlite.insert}[dialect]
        statement = (
            insert(RateLimitCounter)
            .values(key=key, count=1, expires_at=expires_at)
            .on_conflict_do_update(index_elements=["key"], set_={"count": RateLimitCounter.count + 1})
            .returning(RateLimitCounter.count)
        )
        count = self.db.execute(statement).scalar_one()
        self.db.commit()
        if enforce and count > rule.limit:
            raise RateLimitedError(retry_after)

    def check(self, scope: str, identifier: str, rule_name: str) -> None:
        """Raise 429 if the window is already full, without counting this request."""
        if not self.settings.rate_limit_enabled:
            return
        rule = self.settings.rate_rule(rule_name)
        key, _, retry_after = self._window(scope, identifier, rule, utcnow())
        count = self.db.scalar(select(RateLimitCounter.count).where(RateLimitCounter.key == key)) or 0
        if count >= rule.limit:
            raise RateLimitedError(retry_after)

    def reset(self, scope: str, identifier: str, rule_name: str) -> None:
        rule = self.settings.rate_rule(rule_name)
        key, _, _ = self._window(scope, identifier, rule, utcnow())
        self.db.execute(delete(RateLimitCounter).where(RateLimitCounter.key == key))
