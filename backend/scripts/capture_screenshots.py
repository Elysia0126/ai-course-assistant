"""End-to-end UI walkthrough that also captures the README screenshots.

Drives a real browser through every feature, entirely through the web app (and its /api proxy):
dashboard → one-click demo course → materials + retrieval inspector → streaming chat with citations →
full-passage viewer → quiz generation, answering and grading → flashcard study session → mobile layout.

    pip install playwright httpx            # uses your installed Edge/Chrome, no browser download
    python scripts/capture_screenshots.py --web http://localhost:3000

Screenshots go to ../docs/screenshots/.
"""

import argparse
import time
from pathlib import Path

import httpx
from playwright.sync_api import Page, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "screenshots"
COURSE_NAME = "Machine Learning Foundations"


def reset_demo(web: str) -> None:
    client = httpx.Client(base_url=f"{web.rstrip('/')}/api", timeout=60)
    for course in client.get("/courses").json():
        if course["name"] == COURSE_NAME:
            client.delete(f"/courses/{course['id']}").raise_for_status()


def wait_until_indexed(web: str, course_id: str) -> None:
    client = httpx.Client(base_url=f"{web.rstrip('/')}/api", timeout=60)
    deadline = time.time() + 300
    while time.time() < deadline:
        docs = client.get(f"/courses/{course_id}/documents").json()
        if docs and all(d["status"] == "ready" for d in docs):
            return
        if any(d["status"] == "failed" for d in docs):
            raise RuntimeError(f"Ingestion failed: {docs}")
        time.sleep(1)
    raise TimeoutError("Documents were not indexed in time")


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


def run(web: str, channel: str, headed: bool) -> None:
    base = web.rstrip("/")
    reset_demo(base)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel=channel, headless=not headed)
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        page.on("dialog", lambda dialog: dialog.accept())

        print("Dashboard → one-click demo course")
        page.goto(base)
        page.get_by_role("button", name="Demo course", exact=False).first.click()
        page.wait_for_url("**/courses/*/materials")
        course_id = page.url.rstrip("/").split("/")[-2]
        wait_until_indexed(base, course_id)
        page.goto(base)
        expect(page.get_by_role("heading", name=COURSE_NAME)).to_be_visible()
        shot(page, "dashboard")

        print("Materials + retrieval inspector")
        page.goto(f"{base}/courses/{course_id}/materials")
        expect(page.get_by_text("Lecture03_Gradient_Descent.pdf")).to_be_visible()
        page.get_by_placeholder("e.g. what is momentum?").fill("how does momentum speed up optimization?")
        page.get_by_role("button", name="Search").click()
        expect(page.get_by_text("rrf").first).to_be_visible()
        shot(page, "materials")

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

        print("Mobile layout (390 × 844): no horizontal overflow on any page")
        mobile = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True)
        for path in (
            "",
            f"/courses/{course_id}/materials",
            f"/courses/{course_id}/quiz",
            f"/courses/{course_id}/flashcards",
        ):
            mobile.goto(f"{base}{path}")
            mobile.wait_for_timeout(800)
            overflow = mobile.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
            assert overflow <= 0, f"horizontal overflow of {overflow}px on mobile at {path or '/'}"
        mobile.goto(f"{base}/courses/{course_id}/ask")
        mobile_box = mobile.get_by_placeholder("Ask a question about your course", exact=False)
        mobile_box.fill("What does warmup do?")
        mobile_box.press("Enter")
        expect(mobile.get_by_text("Cited sources")).to_be_visible(timeout=120_000)
        overflow = mobile.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        assert overflow <= 0, f"horizontal overflow of {overflow}px on mobile"
        # Content can also be clipped inside a scroll container without overflowing the page.
        clipped = mobile.evaluate(
            """() => [...document.querySelectorAll('[id^="src-"]')]
                 .filter((el) => el.getBoundingClientRect().right > document.documentElement.clientWidth).length"""
        )
        assert clipped == 0, f"{clipped} source cards are clipped on mobile"
        mobile.wait_for_timeout(600)  # let the auto-scroll to the newest message finish first
        scroll_chat_to_top(mobile)
        shot(mobile, "mobile")

        browser.close()
    print("Walkthrough passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--web", default="http://localhost:3000")
    parser.add_argument("--channel", default="msedge", help="installed browser: msedge or chrome")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    run(args.web, args.channel, args.headed)
