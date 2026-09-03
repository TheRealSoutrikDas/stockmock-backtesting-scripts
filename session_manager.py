"""
Create and check the saved browser session.

    python session_manager.py            # log in, verify, save session.json
    python session_manager.py --check    # is the saved session still valid?

NOTE: everything runs in a VISIBLE browser. StockMock sits behind Cloudflare,
which serves a "you have been blocked" page to headless Chromium. Headed
works fine. --headless exists only to demonstrate that difference; it will
almost certainly fail.

StockMock logs in with a phone number and password in the browser. This script
holds no credentials: it opens a window, you log in yourself, and it saves the
cookies and localStorage afterwards.

It will NOT save a session that does not look logged in, so a session.json on
disk means the login really worked.
"""

from __future__ import annotations

import argparse
import json
import sys

from playwright.sync_api import sync_playwright

import config


# Text that only appears once you are logged in. "Backtest" is NOT usable:
# it is in the nav on the logged-out marketing site too.
LOGGED_IN_MARKERS = [
    "text=Free Credits",
    "text=Buy Plans",
    "text=Dashboard",
]

# Text that means we are looking at a logged-out page.
LOGGED_OUT_MARKERS = [
    "text=SignUp",
    "text=Sign Up",
]


def find_marker(page, selectors: list[str], timeout: int = 8_000) -> str | None:
    """Return the first selector that is visible, or None."""
    for sel in selectors:
        try:
            page.wait_for_selector(sel, timeout=timeout, state="visible")
            return sel
        except Exception:
            continue
    return None


def describe_state(page) -> str:
    hit = find_marker(page, LOGGED_IN_MARKERS, timeout=8_000)
    if hit:
        return f"logged in (found {hit})"
    out = find_marker(page, LOGGED_OUT_MARKERS, timeout=3_000)
    if out:
        return f"logged OUT (found {out})"
    return "unclear (no known marker found)"


def report_storage(state: dict) -> None:
    cookies = state.get("cookies", [])
    origins = state.get("origins", [])
    n_local = sum(len(o.get("localStorage", [])) for o in origins)
    print(f"  cookies saved:      {len(cookies)}")
    print(f"  origins saved:      {len(origins)}")
    print(f"  localStorage items: {n_local}")
    if not cookies and not n_local:
        print("  WARNING: nothing was captured. You were probably not logged in")
        print("  in THIS window. The login must happen in the window this script")
        print("  opened, not in your normal browser.")


def create_session() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        print(f"Opening {config.BASE_URL} ...")
        page.goto(config.BASE_URL, wait_until="domcontentloaded")

        print()
        print("Log in IN THIS WINDOW with your phone number and password.")
        print("It must be this window, not your normal browser, or nothing is saved.")
        input("Press Enter once you can see the dashboard... ")

        # Verify before saving, so a saved file always means a real session.
        print()
        print(f"Checking the page... {describe_state(page)}")

        if not find_marker(page, LOGGED_IN_MARKERS, timeout=8_000):
            print()
            print("This does not look logged in, so nothing was saved.")
            print("Finish logging in, then run this script again.")
            browser.close()
            return 1

        state = context.storage_state(path=str(config.SESSION_FILE))
        print(f"Saved session to {config.SESSION_FILE}")
        report_storage(state)

        browser.close()
        return 0


def check_session(headless: bool = False) -> int:
    if not config.SESSION_FILE.exists():
        print("No session.json found. Run: python session_manager.py")
        return 1

    saved = json.loads(config.SESSION_FILE.read_text())
    print("Saved session contents:")
    report_storage(saved)
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        if headless:
            print("WARNING: headless mode is blocked by Cloudflare on this site.")
        context = browser.new_context(storage_state=str(config.SESSION_FILE))
        page = context.new_page()

        print(f"Opening {config.BUILDER_URL} ...")
        page.goto(config.BUILDER_URL, wait_until="domcontentloaded")

        # A hash-bang SPA needs time to boot before any marker exists.
        page.wait_for_timeout(5_000)

        state = describe_state(page)
        print(f"Landed on: {page.url}")
        print(f"State:     {state}")

        ok = state.startswith("logged in")
        if not ok:
            shot = config.DEBUG_DIR / "session_check.png"
            try:
                page.screenshot(path=str(shot), full_page=True)
                print(f"Screenshot written to {shot}")
                print("Open it to see what the browser actually got.")
            except Exception:
                pass
            print()
            print("If the screenshot shows a Cloudflare 'you have been blocked'")
            print("page, you are running headless. Drop --headless.")
            print("If it shows you logged IN, the marker list here needs updating.")
            print("If it shows a login page, the session did not carry over.")

        browser.close()
        return 0 if ok else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="validate the saved session")
    parser.add_argument("--headless", action="store_true",
                        help="force headless (blocked by Cloudflare; for demonstration)")
    args = parser.parse_args()

    sys.exit(check_session(args.headless) if args.check else create_session())
