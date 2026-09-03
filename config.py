"""
Central configuration.

Everything that is likely to break when StockMock changes its UI lives in
SELECTORS below. You should only need to edit that one dict.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------- paths ----

ROOT = Path(__file__).parent
RESULTS_DIR = ROOT / "results"
DEBUG_DIR = ROOT / "debug"
SESSION_FILE = ROOT / "session.json"

RESULTS_DIR.mkdir(exist_ok=True)
DEBUG_DIR.mkdir(exist_ok=True)

CSV_PATH = RESULTS_DIR / "backtest_summary.csv"
JSON_PATH = RESULTS_DIR / "backtest_summary.json"

# Dry runs write here instead, so validation never pollutes real results.
DRY_CSV_PATH = RESULTS_DIR / "dry_run_summary.csv"
DRY_JSON_PATH = RESULTS_DIR / "dry_run_summary.json"

# ------------------------------------------------------------- runtime ----

BASE_URL = os.getenv("STOCKMOCK_BASE_URL", "https://www.stockmock.in")

# StockMock is a hash-bang SPA. The backtest builder lives at /#!/home
# (confirmed from the address bar). The plain /backtest.html path is a
# marketing page, not the app.
BUILDER_URL = os.getenv("STOCKMOCK_BUILDER_URL", f"{BASE_URL}/#!/home")

# Guard against a truncated URL. python-dotenv strips an inline comment when a
# space precedes the '#', so "…/ #!/home" silently becomes "…/" and the script
# would open the marketing homepage instead of the app.
if "#!" not in BUILDER_URL:
    raise SystemExit(
        f"STOCKMOCK_BUILDER_URL looks wrong: {BUILDER_URL!r}\n"
        "It should contain '#!', e.g. https://www.stockmock.in/#!/home\n"
        "If you set it in .env, wrap it in double quotes so the '#' survives."
    )

# Milliseconds. Playwright's default is 30s which is usually fine, but a
# backtest run can take longer than a normal page interaction.
DEFAULT_TIMEOUT_MS = int(os.getenv("DEFAULT_TIMEOUT_MS", 30_000))
RESULT_TIMEOUT_MS = int(os.getenv("RESULT_TIMEOUT_MS", 120_000))

# Retries for a single flaky interaction (not for a whole run).
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 2.0

# Politeness delay between runs, in seconds. Do not set this to 0.
DELAY_BETWEEN_RUNS = float(os.getenv("DELAY_BETWEEN_RUNS", 4.0))

# StockMock is behind Cloudflare, which blocks headless Chromium with a
# "Sorry, you have been blocked" interstitial. Every browser this project
# opens is therefore visible. There is no headless option by design.

# Save a screenshot + page HTML for every run that fails to parse.
SAVE_DEBUG_ARTIFACTS = True

# ----------------------------------------------------------- selectors ----
#
# Fill these in from DevTools. Prefer stable attributes (data-testid, id,
# name, aria-label) over generated class names, which change on every deploy.
#
# Anything set to None is treated as "skip this step", which is useful when a
# field already defaults to the value you want.

SELECTORS = {
    # Login selectors are no longer here: session_manager.py detects the
    # logged-in state by visible text, which survives UI changes better.

    # ---- Strategy builder ----
    #
    # The time dropdowns are located by XPath relative to their visible label,
    # so you do NOT need to dig out element ids for them. Each time is three
    # <select> elements: hour, minute, second.
    "entry_time_anchor": "Entry Time:",
    "exit_time_anchor": "Exit Time:",

    "range_breakout_checkbox": "input[type='checkbox']",
    "range_breakout_label": "Range Breakout",

    # With Range Breakout ticked, the range is defined by TIME only (there are
    # no price fields). The first row IS the entry time, the second row sits
    # under the word "Until".
    #   Entry Time:  [9] : [22] : [00]
    #                     Until
    #                [9] : [31] : [00]
    "range_start_anchor": "Entry Time:",
    "range_end_anchor": "Until",

    # StockMock prints a sentence confirming the window it will actually use,
    # e.g. "High & Low of the Range will be considered between 9:22 open and
    # 9:30 closing time." The runner logs this before each run so you can see
    # exactly what the platform understood.
    "range_helper_text": "text=/High & Low of the Range/",

    "intraday_button": "text=INTRADAY",
    "run_button": "text=START BACKTEST",

    # Live credit cost indicator at the bottom right. Read before each run.
    "credit_notice": "text=/will consume .* Credit/",

    # ---- Results ----
    # Confirmed from the live page. __result__container wraps the whole result
    # block; the tighter div.__average__box holds just the stats grid and may
    # omit Estimated Margin.
    "results_container": "div.__result__container.col-md-12",
    "loading_spinner": ".loading-overlay",
}

# Nothing here needs setting when reusing a manually configured page.
FORM_VALUES = {
    "instrument": "Nifty",
    "strike": "ATM",
    "expiry": "Weekly",
    "total_lot": "1",
}

# StockMock's actual result labels. Note that it reports DAY-wise stats, not
# trade-wise: "Win% (Days)" is the share of profitable days, not trades.
METRIC_LABELS = {
    "estimated margin": "estimated_margin",
    "overall profit": "overall_profit",
    "avg day profit": "avg_day_profit",
    "max profit": "max_profit",
    "max loss": "max_loss",
    "win%": "win_pct_days",
    "loss%": "loss_pct_days",
    "avg monthly profit": "avg_monthly_profit",
    "avg profit on win days": "avg_profit_win_days",
    "avg loss on loss days": "avg_loss_loss_days",
    "max drawdown": "max_drawdown",
    "return to mdd": "return_to_mdd",
    "max winning streak": "max_winning_streak",
    "max losing streak": "max_losing_streak",
    "expectancy": "expectancy",
}
