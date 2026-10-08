"""Make TestClient behave like the web app in a browser: same-origin requests with the CSRF header."""

import httpx
from fastapi.testclient import TestClient

PASSWORD = "correct horse battery staple"
ORIGIN = "http://testserver"  # APP_PUBLIC_URL in the test settings
CSRF_COOKIE = "aica_csrf"
SESSION_COOKIE = "aica_session"


def browserlike(client: TestClient) -> TestClient:
    """State-changing requests get the page's Origin and echo the CSRF token (kept in the cookie jar here;
    the real frontend keeps it in memory from /api/auth/csrf or the login response)."""

    def add_headers(request: httpx.Request) -> None:
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return
        request.headers.setdefault("origin", ORIGIN)
        token = client.cookies.get(CSRF_COOKIE)
        if token and "x-csrf-token" not in request.headers:
            request.headers["x-csrf-token"] = token

    client.event_hooks["request"].append(add_headers)
    return client


def set_cookie(client: TestClient, name: str, value: str) -> None:
    """Replace a cookie the way a browser would see it (TestClient stores host-only cookies for
    'testserver' under 'testserver.local')."""
    client.cookies.delete(name)
    client.cookies.set(name, value, domain="testserver.local")


def csrf(client: TestClient) -> str:
    response = client.get("/api/auth/csrf")
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


def register(client: TestClient, email: str, password: str = PASSWORD, **extra: object) -> dict:
    csrf(client)
    response = client.post(
        "/api/auth/register", json={"email": email, "password": password, "password_confirm": password, **extra}
    )
    assert response.status_code == 201, response.text
    return response.json()


def login(client: TestClient, email: str, password: str = PASSWORD, *, remember: bool = False) -> httpx.Response:
    csrf(client)
    return client.post("/api/auth/login", json={"email": email, "password": password, "remember_me": remember})
