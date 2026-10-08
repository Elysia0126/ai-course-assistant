"""Low-level web security helpers: tokens, cookies, CSRF/origin checks and client addresses.

CSRF defence has two independent layers for every state-changing request (POST/PUT/PATCH/DELETE):

1. **Origin** — the browser-supplied ``Origin`` (or, failing that, ``Referer``) must be one of the configured
   trusted origins (scheme + host + port). A request with neither header is refused.
2. **Synchronizer token** — the ``X-CSRF-Token`` header must match a token the attacker can't read:
   for a signed-in browser it is derived from the session secret (HMAC), so it is bound to that session;
   before sign-in it must equal the random value in the ``csrf`` cookie (double-submit).
"""

import base64
import hashlib
import hmac
import ipaddress
import re
import secrets
from datetime import UTC, datetime
from functools import lru_cache

from fastapi import Request, Response

from app.core.config import Settings, origin_of
from app.core.errors import CSRFError
from app.db.types import utcnow

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "X-CSRF-Token"
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")


# --- Tokens ------------------------------------------------------------------------------------------------


def new_token() -> str:
    """256 bits from the OS CSPRNG, URL-safe."""
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    """What the database stores instead of a session or reset token."""
    return hashlib.sha256(token.encode()).hexdigest()


def is_well_formed_token(value: str | None) -> bool:
    return bool(value) and _TOKEN_RE.match(value) is not None  # type: ignore[arg-type]


def csrf_token_for_session(session_token: str) -> str:
    """HMAC keyed by the (HttpOnly) session secret: stable across tabs, useless without the session."""
    digest = hmac.new(session_token.encode(), b"aica-csrf-v1", hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


# --- Cookies -----------------------------------------------------------------------------------------------
# Host-only (no Domain attribute), Path=/, HttpOnly, SameSite=Lax by default, Secure behind HTTPS.


def _cookie_options(settings: Settings) -> dict:
    return {
        "path": "/",
        "secure": settings.session_cookie_secure,
        "httponly": True,
        "samesite": settings.session_cookie_samesite,
    }


def _seconds_until(expires_at: datetime) -> int:
    # Max-Age mirrors the session's expires_at in the database.
    return max(0, round((expires_at - utcnow()).total_seconds()))


def set_session_cookie(response: Response, settings: Settings, token: str, expires_at: datetime) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=_seconds_until(expires_at),
        expires=expires_at.astimezone(UTC),
        **_cookie_options(settings),
    )


def set_csrf_cookie(response: Response, settings: Settings, token: str, expires_at: datetime | None = None) -> None:
    if expires_at is None:  # anonymous: a browser-session cookie
        response.set_cookie(settings.csrf_cookie_name, token, **_cookie_options(settings))
        return
    response.set_cookie(
        settings.csrf_cookie_name,
        token,
        max_age=_seconds_until(expires_at),
        expires=expires_at.astimezone(UTC),
        **_cookie_options(settings),
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(settings.session_cookie_name, **_cookie_options(settings))


def clear_auth_cookies(response: Response, settings: Settings) -> None:
    clear_session_cookie(response, settings)
    response.delete_cookie(settings.csrf_cookie_name, **_cookie_options(settings))


# --- Origin & CSRF -----------------------------------------------------------------------------------------


def request_origin(request: Request) -> str | None:
    origin = request.headers.get("origin")
    if origin and origin != "null":
        return origin
    referer = request.headers.get("referer")
    if referer:
        try:
            return origin_of(referer)
        except ValueError:
            return None
    return None


def check_origin(request: Request, settings: Settings) -> None:
    origin = request_origin(request)
    if origin is None:
        raise CSRFError("State-changing requests must carry an Origin header.", code="origin_required")
    try:
        normalized = origin_of(origin)
    except ValueError:
        normalized = None
    if normalized not in settings.trusted_origins:
        raise CSRFError("Cross-origin request refused.", code="origin_not_allowed")


def check_csrf_token(request: Request, expected: str | None) -> None:
    supplied = request.headers.get(CSRF_HEADER, "")
    if not expected or not supplied or not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise CSRFError("Missing or invalid CSRF token. Reload the page and try again.")


# --- Client address ----------------------------------------------------------------------------------------


@lru_cache(maxsize=32)
def _networks(entries: tuple[str, ...]) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    return tuple(ipaddress.ip_network(entry, strict=False) for entry in entries)


def _is_trusted_peer(peer: str, settings: Settings) -> bool:
    try:
        address = ipaddress.ip_address(peer)
    except ValueError:
        return False
    return any(address in network for network in _networks(tuple(settings.trusted_proxy_ips)))


def client_ip(request: Request, settings: Settings) -> str:
    """The address rate limits are keyed on.

    X-Forwarded-For is only believed when the immediate peer is a trusted proxy: the Next.js server (which
    proves itself with APP_API_TOKEN) or an address listed in TRUSTED_PROXY_IPS. The proxy appends the
    address it saw, so the right-most entry is used; anything a client wrote further left is ignored.
    """
    peer = request.client.host if request.client else "unknown"
    if getattr(request.state, "via_trusted_proxy", False) or _is_trusted_peer(peer, settings):
        entries = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip()]
        if entries:
            try:
                return str(ipaddress.ip_address(entries[-1]))
            except ValueError:
                pass
    return peer
