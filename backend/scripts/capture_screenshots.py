"""End-to-end walkthrough in a real browser that also captures the README screenshots.

Everything goes through the web app and its same-origin /api proxy, exactly as a user would:

  protected page → sign-in redirect → sign up → refresh (session kept) → one-click demo course → upload →
  retrieval inspector → streaming chat with citations → passage viewer → original PDF through the proxy →
  quiz → flashcards → mobile layout → sign out → old cookie replay refused → protected page redirect →
  sign in again (back to the requested page) → forgot password → reset email via a local SMTP server →
  reset page (token stripped from the URL, no-referrer) → old password refused → new password works.

The backend must send mail by SMTP to the catcher this script starts (MAIL_BACKEND=smtp, SMTP_HOST=127.0.0.1,
SMTP_PORT=2525, SMTP_STARTTLS=false) and APP_PUBLIC_URL must equal --web.

    pip install playwright httpx aiosmtpd       # uses your installed Edge/Chrome, no browser download
    python scripts/capture_screenshots.py --web http://localhost:3000

A fresh account (random password) is created on every run. Screenshots go to ../docs/screenshots/.
"""

import argparse
import re
import secrets
import tempfile
import time
from email import message_from_bytes
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "screenshots"
COURSE_NAME = "Machine Learning Foundations"
DISPLAY_NAME = "Alex Student"


class MailCatcher:
    """A local SMTP server that keeps every message it receives."""

    def __init__(self, port: int):
        from aiosmtpd.controller import Controller

        self.messages: list = []
        catcher = self

        class Handler:
            async def handle_DATA(self, server, session, envelope):
                catcher.messages.append(message_from_bytes(envelope.content))
                return "250 OK"

        self.controller = Controller(Handler(), hostname="127.0.0.1", port=port)

    def __enter__(self) -> "MailCatcher":
        self.controller.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.controller.stop()

    def wait_for_link(self, pattern: str, timeout: float = 20) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            for message in reversed(self.messages):
                for part in message.walk():
                    if part.get_content_type() == "text/plain":
                        match = re.search(pattern, part.get_payload(decode=True).decode())
                        if match:
                            return match.group(0)
            time.sleep(0.25)
        raise TimeoutError("No password-reset email arrived — is the backend's SMTP pointed at this catcher?")


def shot(page: Page, name: str, full_page: bool = False) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    page.add_style_tag(content="[data-sonner-toaster]{display:none !important}")  # hide transient toasts
    page.wait_for_timeout(400)  # let transitions settle
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=full_page)
    print(f"  saved docs/screenshots/{name}.png")


def scroll_chat_to_top(page: Page) -> None:
    page.evaluate(
        """() => {
            const pane = [...document.querySelectorAll('div')].find(
                (d) => getComputedStyle(d).overflowY === 'auto' && d.innerText.includes('Cited sources'));
            if (pane) pane.scrollTop = 0;
        }"""
    )


def horizontal_overflow(page: Page) -> int:
    return page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")


def wait_until_indexed(context: BrowserContext, base: str, course_id: str) -> list[dict]:
    """Poll through the proxy with the browser's own session cookie."""
    deadline = time.time() + 300
    while time.time() < deadline:
        response = context.request.get(f"{base}/api/courses/{course_id}/documents")
        assert response.ok, response.status
        docs = response.json()
        if docs and all(d["status"] == "ready" for d in docs):
            return docs
        if any(d["status"] == "failed" for d in docs):
            raise RuntimeError(f"Ingestion failed: {docs}")
        time.sleep(1)
    raise TimeoutError("Documents were not indexed in time")


def sign_in(page: Page, email: str, password: str, *, remember: bool = False) -> None:
    page.get_by_label("Email").fill(email)
    page.get_by_label("Password", exact=True).fill(password)
    if remember:
        page.get_by_label("Remember me").check()
    page.get_by_role("button", name="Sign in", exact=True).click()


def assert_mobile_pages(browser: Browser, base: str, paths: list[str], storage_state: dict | None = None) -> Page:
    context = browser.new_context(
        viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, storage_state=storage_state
    )
    mobile = context.new_page()
    for path in paths:
        mobile.goto(f"{base}{path}")
        mobile.wait_for_timeout(800)
        assert horizontal_overflow(mobile) <= 0, f"horizontal overflow on mobile at {path or '/'}"
    return mobile


def run(web: str, channel: str, headed: bool, smtp_port: int) -> None:
    base = web.rstrip("/")
    email = f"e2e-{int(time.time())}@example.com"
    password = f"{secrets.token_urlsafe(12)} study passphrase"  # fresh per run, never stored
    new_password = f"{secrets.token_urlsafe(12)} brand new passphrase"

    with MailCatcher(smtp_port) as mail, sync_playwright() as p:
        browser = p.chromium.launch(channel=channel, headless=not headed)
        context = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        page = context.new_page()
        page.on("dialog", lambda dialog: dialog.accept())

        print("Protected page → sign-in redirect")
        page.goto(base)
        expect(page).to_have_url(re.compile(r"/login\?next=%2F$"))
        expect(page.get_by_role("heading", name="Sign in")).to_be_visible()
        shot(page, "login")

        print("Sign up → signed in on the dashboard")
        page.get_by_role("link", name="Create an account").click()
        expect(page).to_have_url(re.compile(r"/register"))
        page.get_by_label("Name (optional)").fill(DISPLAY_NAME)
        page.get_by_label("Email").fill(email)
        page.get_by_label("Password", exact=True).fill(password)
        page.get_by_label("Confirm password", exact=True).fill(password)
        shot(page, "register")
        page.get_by_role("button", name="Create account").click()
        expect(page).to_have_url(f"{base}/")
        expect(page.get_by_test_id("current-user")).to_have_text(DISPLAY_NAME)
        cookies = {c["name"]: c for c in context.cookies()}
        session_cookie = cookies["aica_session"]
        assert session_cookie["httpOnly"] and session_cookie["sameSite"] == "Lax", session_cookie
        assert "aica_session" not in page.evaluate("document.cookie"), "session cookie must be HttpOnly"

        print("Refresh keeps the session")
        page.reload()
        expect(page.get_by_test_id("current-user")).to_have_text(DISPLAY_NAME)

        print("Dashboard → one-click demo course")
        page.get_by_role("button", name="Demo course", exact=False).first.click()
        page.wait_for_url("**/courses/*/materials")
        course_id = page.url.rstrip("/").split("/")[-2]
        wait_until_indexed(context, base, course_id)
        page.goto(base)
        expect(page.get_by_role("heading", name=COURSE_NAME)).to_be_visible()
        shot(page, "dashboard")

        print("Upload through the UI")
        page.goto(f"{base}/courses/{course_id}/materials")
        with tempfile.TemporaryDirectory() as tmp:
            notes = Path(tmp) / "Week7_Batch_Normalization.md"
            notes.write_text(
                "# Batch Normalization\n\nBatch normalization normalizes layer inputs over a mini-batch, which "
                "stabilizes and speeds up the training of deep networks.\n",
                encoding="utf-8",
            )
            page.locator('input[type="file"]').set_input_files(str(notes))
            expect(page.get_by_text("Week7_Batch_Normalization.md")).to_be_visible(timeout=60_000)
        docs = wait_until_indexed(context, base, course_id)
        assert len(docs) == 4, docs

        print("Materials + retrieval inspector")
        page.reload()
        expect(page.get_by_text("Lecture03_Gradient_Descent.pdf")).to_be_visible()
        page.get_by_placeholder("e.g. what is momentum?").fill("how does momentum speed up optimization?")
        page.get_by_role("button", name="Search").click()
        expect(page.get_by_text("rrf").first).to_be_visible()
        shot(page, "materials")

        print("Original PDF through the proxy (owner only)")
        pdf = next(d for d in docs if d["file_type"] == "pdf")
        file_url = f"{base}/api/documents/{pdf['id']}/file"
        owned = context.request.get(file_url)
        assert owned.ok and owned.headers["content-type"] == "application/pdf", owned.status
        assert owned.headers["cache-control"] == "private, no-store", owned.headers
        stranger = browser.new_context()
        assert stranger.request.get(file_url).status == 401
        stranger.close()

        print("Ask (streaming RAG with citations) → passage viewer")
        page.goto(f"{base}/courses/{course_id}/ask")
        box = page.get_by_placeholder("Ask a question about your course", exact=False)
        box.fill("Why do gradients vanish in deep networks, and how can we fix it?")
        box.press("Enter")
        expect(page.get_by_text("Cited sources")).to_be_visible(timeout=120_000)
        scroll_chat_to_top(page)
        page.get_by_role("button", name="Show source 1").first.hover()
        shot(page, "chat")
        page.get_by_role("button", name="View").first.click()
        expect(page.get_by_text("the exact passage that was retrieved")).to_be_visible()
        shot(page, "passage")
        page.keyboard.press("Escape")

        print("Quiz: generate → answer → grade")
        page.goto(f"{base}/courses/{course_id}/quiz")
        page.get_by_role("button", name="Generate quiz").click()
        expect(page.get_by_role("button", name="Submit answers")).to_be_visible(timeout=180_000)
        for card in page.locator("ol > div").all():
            textarea = card.locator("textarea")
            if textarea.count():
                textarea.fill("It controls the size of each update step taken by gradient descent.")
            else:
                card.locator("button").first.click()
        page.get_by_role("button", name="Submit answers").click()
        expect(page.get_by_role("button", name="Retake")).to_be_visible()
        page.wait_for_timeout(800)  # the page smooth-scrolls to the score card
        page.evaluate("window.scrollTo(0, 0)")
        shot(page, "quiz")

        print("Flashcards: generate → study → flip")
        page.goto(f"{base}/courses/{course_id}/flashcards")
        page.get_by_role("button", name="Generate deck").click()
        study = page.get_by_role("button", name="Study", exact=False).first
        expect(study).to_be_visible(timeout=180_000)
        study.click()
        page.get_by_role("button", name="Show answer").click()
        page.wait_for_timeout(700)
        shot(page, "flashcards")
        page.get_by_role("button", name="Good", exact=False).click()
        expect(page.get_by_text("2 /", exact=False)).to_be_visible()

        print("Mobile layout (390 × 844): no horizontal overflow, signed in and out")
        signed_in_state = context.storage_state()
        mobile = assert_mobile_pages(
            browser,
            base,
            ["", f"/courses/{course_id}/materials", f"/courses/{course_id}/quiz", f"/courses/{course_id}/flashcards"],
            storage_state=signed_in_state,
        )
        mobile.goto(f"{base}/courses/{course_id}/ask")
        mobile_box = mobile.get_by_placeholder("Ask a question about your course", exact=False)
        mobile_box.fill("What does warmup do?")
        mobile_box.press("Enter")
        expect(mobile.get_by_text("Cited sources")).to_be_visible(timeout=120_000)
        assert horizontal_overflow(mobile) <= 0, "horizontal overflow on mobile chat"
        clipped = mobile.evaluate(
            """() => [...document.querySelectorAll('[id^="src-"]')]
                 .filter((el) => el.getBoundingClientRect().right > document.documentElement.clientWidth).length"""
        )
        assert clipped == 0, f"{clipped} source cards are clipped on mobile"
        mobile.wait_for_timeout(600)  # let the auto-scroll to the newest message finish first
        scroll_chat_to_top(mobile)
        shot(mobile, "mobile")
        mobile.context.close()
        anonymous_mobile = assert_mobile_pages(browser, base, ["/login", "/register", "/forgot-password"])
        anonymous_mobile.goto(f"{base}/login")
        shot(anonymous_mobile, "mobile-login")
        anonymous_mobile.context.close()

        print("Sign out → old cookie replay refused → protected pages redirect")
        page.goto(base)
        page.get_by_role("button", name="Sign out").click()
        expect(page).to_have_url(re.compile(r"/login\?reason=signed-out"))
        expect(page.get_by_text("You've been signed out.")).to_be_visible()
        assert "aica_session" not in {c["name"] for c in context.cookies()}
        replay = browser.new_context(storage_state=signed_in_state)
        assert replay.request.get(f"{base}/api/courses").status == 401, "revoked session must not work"
        replay.close()
        page.goto(f"{base}/courses/{course_id}/materials")
        expect(page).to_have_url(re.compile(r"/login\?next=%2Fcourses%2F.+%2Fmaterials"))

        print("Sign in again → back to the requested page")
        sign_in(page, email, password, remember=True)
        page.wait_for_url(f"{base}/courses/{course_id}/materials")
        remembered = {c["name"]: c for c in context.cookies()}["aica_session"]
        assert remembered["expires"] - time.time() > 29 * 86400, "remember me should last 30 days"

        print("Forgot password → email (SMTP) → reset page → new password")
        page.get_by_role("button", name="Sign out").click()
        page.wait_for_url(re.compile(r"/login"))
        page.get_by_role("link", name="Forgot password?").click()
        page.get_by_label("Email").fill(email)
        page.get_by_role("button", name="Send reset link").click()
        expect(page.get_by_text("If an account exists for that email")).to_be_visible()
        link = mail.wait_for_link(rf"{re.escape(base)}/reset-password#token=[A-Za-z0-9_-]+")
        page.goto(link)
        expect(page.get_by_role("heading", name="Choose a new password")).to_be_visible()
        expect(page).to_have_url(f"{base}/reset-password")  # token removed from the address bar
        assert page.locator('meta[name="referrer"][content="no-referrer"]').count() == 1
        page.get_by_label("New password", exact=True).fill(new_password)
        page.get_by_label("Confirm new password", exact=True).fill(new_password)
        shot(page, "reset-password")
        page.get_by_role("button", name="Set new password").click()
        page.wait_for_url(re.compile(r"/login\?reason=reset"))
        sign_in(page, email, password)
        expect(page.get_by_role("alert").filter(has_text="Incorrect email or password.")).to_be_visible()
        page.get_by_label("Password", exact=True).fill(new_password)
        page.get_by_role("button", name="Sign in", exact=True).click()
        page.wait_for_url(f"{base}/")
        expect(page.get_by_test_id("current-user")).to_have_text(DISPLAY_NAME)

        print("Non-admins can't open the admin page")
        page.goto(f"{base}/admin")
        expect(page.get_by_text("Administrators only")).to_be_visible()

        browser.close()
    print("Walkthrough passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--web", default="http://localhost:3000")
    parser.add_argument("--channel", default="msedge", help="installed browser: msedge or chrome")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--smtp-port", type=int, default=2525, help="port of the local SMTP catcher")
    args = parser.parse_args()
    run(args.web, args.channel, args.headed, args.smtp_port)
