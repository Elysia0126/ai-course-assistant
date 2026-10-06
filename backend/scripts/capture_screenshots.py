"""End-to-end UI walkthrough that also captures the README screenshots.

Drives a real browser through every feature: dashboard → materials (+ retrieval inspector) → streaming
chat with citations → quiz generation, answering and grading → flashcard study session.

    pip install playwright                       # uses your installed Edge/Chrome, no browser download
    python scripts/capture_screenshots.py --web http://localhost:3000 --api http://localhost:8000

It (re)creates the demo course from ../sample_data first. Screenshots go to ../docs/screenshots/.
"""

import argparse
import time
from pathlib import Path

import httpx
from playwright.sync_api import Page, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "sample_data"
OUT = ROOT / "docs" / "screenshots"
COURSE_NAME = "Machine Learning Foundations"
MIME = {
    ".pdf": "application/pdf",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".md": "text/markdown",
}


def seed(api: str) -> str:
    client = httpx.Client(base_url=f"{api.rstrip('/')}/api", timeout=120)
    for course in client.get("/courses").json():
        if course["name"] == COURSE_NAME:
            client.delete(f"/courses/{course['id']}")
    course = client.post(
        "/courses",
        json={
            "name": COURSE_NAME,
            "code": "ML 101",
            "term": "Fall 2026",
            "description": "Optimization, neural networks and regularization — lecture slides, notes and readings.",
            "color": "indigo",
        },
    ).json()
    files = [("files", (p.name, p.read_bytes(), MIME[p.suffix])) for p in sorted(SAMPLES.iterdir()) if p.suffix in MIME]
    client.post(f"/courses/{course['id']}/documents", files=files).raise_for_status()
    deadline = time.time() + 300
    while time.time() < deadline:
        docs = client.get(f"/courses/{course['id']}/documents").json()
        if all(d["status"] == "ready" for d in docs):
            return course["id"]
        if any(d["status"] == "failed" for d in docs):
            raise RuntimeError(f"Ingestion failed: {docs}")
        time.sleep(1)
    raise TimeoutError("Documents were not indexed in time")


def shot(page: Page, name: str, full_page: bool = False) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    # Hide transient toasts so they don't cover the content.
    page.add_style_tag(content="[data-sonner-toaster]{display:none !important}")
    page.wait_for_timeout(400)  # let transitions settle
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=full_page)
    print(f"  saved docs/screenshots/{name}.png")


def run(web: str, api: str, channel: str, headed: bool) -> None:
    course_id = seed(api)
    print(f"Seeded demo course {course_id}")
    base = web.rstrip("/")

    with sync_playwright() as p:
        browser = p.chromium.launch(channel=channel, headless=not headed)
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        page.on("dialog", lambda dialog: dialog.accept())

        print("Dashboard")
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

        print("Ask (streaming RAG with citations)")
        page.goto(f"{base}/courses/{course_id}/ask")
        box = page.get_by_placeholder("Ask a question about your course", exact=False)
        box.fill("Why do gradients vanish in deep networks, and how can we fix it?")
        box.press("Enter")
        expect(page.get_by_text("Cited sources")).to_be_visible(timeout=120_000)
        # Show the conversation from the top: question, answer with citation chips, then sources.
        page.evaluate(
            """() => {
                const pane = [...document.querySelectorAll('div')].find(
                    (d) => getComputedStyle(d).overflowY === 'auto' && d.innerText.includes('Cited sources'));
                if (pane) pane.scrollTop = 0;
            }"""
        )
        page.get_by_role("button", name="Show source 1").first.hover()
        shot(page, "chat")

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

        browser.close()
    print("Walkthrough passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--web", default="http://localhost:3000")
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--channel", default="msedge", help="installed browser: msedge or chrome")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    run(args.web, args.api, args.channel, args.headed)
