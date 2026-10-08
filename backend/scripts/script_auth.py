"""Sign a script's HTTP client in exactly like the web app: session cookie + trusted Origin + X-CSRF-Token.

Scripts go through the same authentication and authorisation as the browser — nothing is switched off for
them. Works with httpx.Client and FastAPI's TestClient (a subclass of it).
"""

import httpx

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def sign_in(
    client: httpx.Client,
    *,
    origin: str,
    email: str,
    password: str,
    create: bool = False,
    display_name: str | None = None,
    prefix: str = "",
) -> dict:
    """Log in (or register first when ``create`` is set and the account doesn't exist) and return the user.

    ``prefix`` is prepended to the API paths ("" when the client's base URL already ends in /api).
    """
    state: dict[str, str] = {}

    def add_headers(request: httpx.Request) -> None:
        if request.method not in SAFE_METHODS:
            request.headers.setdefault("origin", origin)
            if "csrf" in state:
                request.headers.setdefault("x-csrf-token", state["csrf"])

    client.event_hooks["request"].append(add_headers)
    csrf = client.get(f"{prefix}/auth/csrf")
    csrf.raise_for_status()
    state["csrf"] = csrf.json()["csrf_token"]

    response = None
    if create:
        response = client.post(
            f"{prefix}/auth/register",
            json={"email": email, "password": password, "password_confirm": password, "display_name": display_name},
        )
        if response.status_code == 409:  # already registered: just sign in
            response = None
    if response is None:
        response = client.post(f"{prefix}/auth/login", json={"email": email, "password": password})
    if response.status_code >= 400:
        raise SystemExit(f"Sign-in as {email} failed: {response.status_code} {response.text}")
    state["csrf"] = response.json()["csrf_token"]  # the new session's token
    return response.json()["user"]
