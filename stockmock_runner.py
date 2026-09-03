"""
Batch runner.

    python stockmock_runner.py --dry-run    # validate everything, 0 credits
    python stockmock_runner.py --limit 1    # one real run, 1 credit
    python stockmock_runner.py              # the full matrix
    python stockmock_runner.py --resume     # continue, skipping completed runs

ALWAYS run --dry-run first. It drives every dropdown and checks every
selector without ever clicking START BACKTEST, so a broken selector costs you
nothing instead of a credit.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from typing import Optional

import pandas as pd
from playwright.sync_api import Page, sync_playwright
from pydantic import BaseModel

import config
from params import RunParams, build_matrix


# ------------------------------------------------------------- model ------

class BacktestResult(BaseModel):
    run_id: int
    range_start: str
    range_end: str
    exit_time: str
    date_from: str
    date_to: str
    status: str = "pending"

    estimated_margin: Optional[float] = None
    overall_profit: Optional[float] = None
    avg_day_profit: Optional[float] = None
    max_profit: Optional[float] = None
    max_loss: Optional[float] = None
    win_pct_days: Optional[float] = None
    loss_pct_days: Optional[float] = None
    avg_monthly_profit: Optional[float] = None
    avg_profit_win_days: Optional[float] = None
    avg_loss_loss_days: Optional[float] = None
    max_drawdown: Optional[float] = None
    return_to_mdd: Optional[float] = None
    max_winning_streak: Optional[float] = None
    max_losing_streak: Optional[float] = None
    expectancy: Optional[float] = None

    error: Optional[str] = None


# ------------------------------------------------------------ helpers -----

def log(msg: str) -> None:
    print(msg, flush=True)


def with_retry(fn, what: str, attempts: int = config.MAX_RETRIES):
    """Run fn, retrying with exponential backoff on failure."""
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:
            last = exc
            if i == attempts - 1:
                break
            wait = config.BACKOFF_BASE_SECONDS * (2 ** i)
            log(f"    retry {i + 1}/{attempts - 1} for {what} in {wait:.0f}s ({exc.__class__.__name__})")
            time.sleep(wait)
    raise RuntimeError(f"{what} failed after {attempts} attempts") from last


# ------------------------------------------------------------ parsing -----

_NUM_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")


def parse_number(raw: Optional[str]) -> Optional[float]:
    """Pull the first number out of a value string.

    StockMock writes values like '36% (8)' and '-14775 (15 Days)', where the
    trailing parenthetical is a SECOND figure. We take only the first, so this
    matches the first numeric token rather than stripping non-digits (which
    would splice the two numbers together).

        '12,450.00'        -> 12450.0
        '36% (8)'          -> 36.0
        '-14775 (15 Days)' -> -14775.0
        '(1,200)'          -> -1200.0
        'NA'               -> None
    """
    if raw is None:
        return None
    s = raw.strip()

    m = _NUM_RE.search(s)
    if not m:
        return None

    val = float(m.group(0).replace(",", ""))

    # Accounting-style negative: brackets around the number itself. Checked on
    # the match, not the whole string, so a trailing '(15 Days)' does not flip
    # the sign of the value in front of it.
    before = s[m.start() - 1] if m.start() > 0 else ""
    after = s[m.end()] if m.end() < len(s) else ""
    if before == "(" and after == ")":
        val = -abs(val)

    return val


def extract_metrics(text: str) -> dict:
    """Pull 'Label value' pairs out of the results panel text.

    Handles the value being on the same line as the label or on the next one,
    which covers both the table and card layouts.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    found: dict = {}

    for i, line in enumerate(lines):
        low = line.lower()
        for label, field in config.METRIC_LABELS.items():
            if label not in low or field in found:
                continue

            tail = line[low.index(label) + len(label):]
            val = parse_number(tail)

            if val is None and i + 1 < len(lines):
                val = parse_number(lines[i + 1])

            if val is not None:
                found[field] = val

    return found


CREDIT_RE = re.compile(r"consume\s+(\d+)\s+Credit", re.I)


def parse_credit_cost(notice: str) -> Optional[int]:
    """'This backtest result will consume 1 Credit' -> 1"""
    m = CREDIT_RE.search(notice or "")
    return int(m.group(1)) if m else None


# --------------------------------------------------------- interactions ---

def time_selects(page: Page, anchor_text: str):
    """The hour and minute <select> elements following a time label.

    Located by XPath relative to the visible label, so no element ids needed.
    """
    base = f"xpath=//*[contains(text(),'{anchor_text}')]/following::select"
    loc = page.locator(base)
    return loc.nth(0), loc.nth(1)


def set_time(page: Page, anchor_text: str, hhmm: str, what: str) -> None:
    """Set a HH : MM pair of dropdowns, then read back to confirm it took.

    Read-back matters: select_option can silently target the wrong element if
    the XPath anchor drifts, and a wrong time is a wasted credit.
    """
    hour, minute = hhmm.split(":")

    def action():
        hour_sel, min_sel = time_selects(page, anchor_text)
        hour_sel.wait_for(timeout=config.DEFAULT_TIMEOUT_MS)

        for target, loc, part in ((hour, hour_sel, "hour"), (minute, min_sel, "minute")):
            # StockMock renders hours unpadded ('9') and minutes padded ('22'),
            # so try both forms.
            candidates = [target, target.lstrip("0") or "0", target.zfill(2)]
            for candidate in dict.fromkeys(candidates):
                try:
                    loc.select_option(label=candidate)
                    break
                except Exception:
                    continue
            else:
                raise ValueError(f"no option matching '{target}' for {what} {part}")

            # Confirm the DOM actually holds what we asked for.
            got = loc.input_value()
            if got.lstrip("0") != target.lstrip("0"):
                raise ValueError(f"{what} {part} read back as '{got}', expected '{target}'")

    with_retry(action, what)


def read_credit_notice(page: Page) -> str:
    try:
        return page.locator(config.SELECTORS["credit_notice"]).first.inner_text(timeout=3_000)
    except Exception:
        return ""


def results_text(page: Page) -> str:
    """Current results panel text, or '' if the panel is not present."""
    try:
        return page.locator(config.SELECTORS["results_container"]).first.inner_text(timeout=2_000)
    except Exception:
        return ""


def wait_for_fresh_results(page: Page, previous: str) -> str:
    """Wait for results that are NOT the previous run's.

    This is why the script does not reload the page: after run 1 the results
    container already exists, so a plain wait_for_selector returns instantly
    with STALE numbers. We poll until the text differs from what was on screen
    before the click, then until it stops changing.
    """
    deadline = time.time() + (config.RESULT_TIMEOUT_MS / 1000)

    # Phase 1: wait for the panel to differ from the previous run.
    changed = False
    while time.time() < deadline:
        current = results_text(page)
        if current.strip() and current.strip() != previous.strip():
            changed = True
            break
        page.wait_for_timeout(500)

    if not changed:
        raise TimeoutError("results did not update within the timeout")

    # Phase 2: wait for it to settle (two identical reads in a row).
    last = ""
    stable = 0
    while time.time() < deadline:
        current = results_text(page)
        if current == last and current.strip():
            stable += 1
            if stable >= 2:
                return current
        else:
            stable = 0
            last = current
        page.wait_for_timeout(500)

    raise TimeoutError("results never stabilised")


# ---------------------------------------------------------- single run ----

def configure_and_run(page: Page, p: RunParams, dry_run: bool, max_credits: int) -> str:
    """Change only the time dropdowns, then run.

    The position, dates and range-breakout settings are identical across every
    run, so you set them up ONCE in the browser and the script leaves them
    alone. That keeps the calendar widgets out of the automation entirely.
    """
    s = config.SELECTORS

    if s["range_start_anchor"]:
        set_time(page, s["range_start_anchor"], p.range_start, "range start")
    if s["range_end_anchor"]:
        set_time(page, s["range_end_anchor"], p.range_end, "range end")

    set_time(page, s["exit_time_anchor"], p.exit_time, "exit time")

    # StockMock states the window it will actually use. Log it so any
    # off-by-one between the dropdowns and the real range is visible.
    helper = s.get("range_helper_text")
    if helper:
        try:
            print(f"    {page.locator(helper).first.inner_text(timeout=3_000).strip()}")
        except Exception:
            pass

    # Credit guard. Refuse to click if this run costs more than expected.
    notice = read_credit_notice(page)
    cost = parse_credit_cost(notice)
    if cost is None:
        log("    WARNING: could not read the credit notice, cost unverified")
    else:
        log(f"    credit cost for this run: {cost}")
        if cost > max_credits:
            raise ValueError(
                f"run would consume {cost} credits, limit is {max_credits}. "
                f"Shorten the date range or raise --max-credits-per-run."
            )

    if dry_run:
        return "DRY RUN: START BACKTEST not clicked"

    before = results_text(page)
    with_retry(lambda: page.click(s["run_button"]), "start backtest")
    return wait_for_fresh_results(page, before)


SUGGEST_JS = """
() => {
  const want = ['Overall Profit', 'Win%', 'Max Drawdown'];
  const hits = [];
  for (const el of document.querySelectorAll('div,section,main,table,article')) {
    const t = el.innerText || '';
    if (!want.every(w => t.includes(w))) continue;
    hits.push({
      tag: el.tagName.toLowerCase(),
      id: el.id || null,
      cls: (el.className && typeof el.className === 'string') ? el.className : null,
      len: t.length
    });
  }
  // Smallest element containing all the stats is the tightest container.
  hits.sort((a, b) => a.len - b.len);
  return hits.slice(0, 3);
}
"""


def suggest_results_container(page: Page) -> None:
    """Find the element that actually wraps the stats and print a selector.

    Saves a DevTools trip: if results_container is wrong, this tells you what
    it should be, using the page already on screen.
    """
    try:
        hits = page.evaluate(SUGGEST_JS)
    except Exception:
        return
    if not hits:
        log("    Could not locate the stats panel to suggest a selector.")
        return

    log("    Suggested results_container values (smallest match first):")
    for h in hits:
        if h.get("id"):
            sel = f"#{h['id']}"
        elif h.get("cls"):
            sel = h["tag"] + "." + ".".join(h["cls"].split()[:2])
        else:
            sel = h["tag"]
        log(f"      {sel}    (wraps {h['len']} chars)")
    log("    Put the first one in config.SELECTORS['results_container'].")


def save_debug(page: Page, run_id: int) -> None:
    if not config.SAVE_DEBUG_ARTIFACTS:
        return
    try:
        page.screenshot(path=str(config.DEBUG_DIR / f"run_{run_id:02d}.png"), full_page=True)
        (config.DEBUG_DIR / f"run_{run_id:02d}.html").write_text(page.content(), encoding="utf-8")
    except Exception:
        pass


# ------------------------------------------------------------- output -----

def write_outputs(results: dict[int, BacktestResult], dry: bool = False) -> None:
    """Write the results file. Dry runs go to a separate path so that
    validation passes never overwrite or pollute real backtest results."""
    csv_path = config.DRY_CSV_PATH if dry else config.CSV_PATH
    json_path = config.DRY_JSON_PATH if dry else config.JSON_PATH
    rows = [results[k].model_dump() for k in sorted(results)]
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    json_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def load_existing() -> dict[int, BacktestResult]:
    """Rows already in the CSV, keyed by run_id.

    Needed so --resume MERGES with earlier results instead of overwriting
    them. Without this, resuming would rewrite completed rows as empty
    "skipped" placeholders and silently destroy work from a previous day.
    """
    if not config.CSV_PATH.exists():
        return {}
    df = pd.read_csv(config.CSV_PATH)
    out: dict[int, BacktestResult] = {}
    for row in df.to_dict("records"):
        clean = {k: (None if pd.isna(v) else v) for k, v in row.items()}
        try:
            out[int(clean["run_id"])] = BacktestResult(**clean)
        except Exception:
            continue
    return out


# ----------------------------------------------------------- preflight ----

def preflight(matrix: list[RunParams]) -> None:
    """Catch misconfigurations that would silently waste credits.

    The big one: if the range anchors are not configured, the script never
    touches the range fields, so every run uses whatever range you set by
    hand. You would pay for 9 runs and get 3 distinct results.
    """
    s = config.SELECTORS
    problems = []

    varies_range = len({(p.range_start, p.range_end) for p in matrix}) > 1
    if varies_range and not (s["range_start_anchor"] and s["range_end_anchor"]):
        problems.append(
            "The matrix varies the range window, but range_start_anchor / "
            "range_end_anchor are not set in config.SELECTORS. Every run would "
            "use the same range, so you would pay for duplicate results.\n"
            "    Fix: tick Range Breakout in the UI, note the label text beside "
            "the range time dropdowns, and set those two anchors."
        )

    if len({p.exit_time for p in matrix}) > 1 and not s["exit_time_anchor"]:
        problems.append("The matrix varies exit time but exit_time_anchor is not set.")

    if problems:
        log("PREFLIGHT FAILED\n")
        for prob in problems:
            log(f"  - {prob}\n")
        raise SystemExit(1)


# --------------------------------------------------------------- main -----

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="only run the first N combinations")
    parser.add_argument("--resume", action="store_true", help="skip completed runs")
    parser.add_argument("--dry-run", action="store_true",
                        help="drive every control but never click START BACKTEST (0 credits)")
    parser.add_argument("--max-failures", type=int, default=2,
                        help="abort after this many consecutive failures (default 2)")
    parser.add_argument("--max-credits-per-run", type=int, default=1,
                        help="abort if a run would cost more than this (default 1)")
    args = parser.parse_args()

    if not config.SESSION_FILE.exists():
        raise SystemExit("No session.json. Run: python session_manager.py")

    matrix = build_matrix()
    if args.limit:
        matrix = matrix[: args.limit]

    preflight(matrix)

    existing = {} if args.dry_run else load_existing()
    skip = ({rid for rid, r in existing.items() if r.status == "completed"}
            if args.resume else set())
    to_run = [p for p in matrix if p.run_id not in skip]

    # Start from what is already on disk so resuming never loses earlier rows.
    results: dict[int, BacktestResult] = dict(existing) if args.resume else {}
    total = len(matrix)

    mode = "DRY RUN (no credits)" if args.dry_run else f"LIVE (~{len(to_run)} credits)"
    log(f"Starting {total} runs, {len(skip)} skipped. Mode: {mode}\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)  # manual setup needs a window
        context = browser.new_context(storage_state=str(config.SESSION_FILE))
        context.set_default_timeout(config.DEFAULT_TIMEOUT_MS)
        page = context.new_page()
        page.goto(config.BUILDER_URL, wait_until="domcontentloaded")

        print()
        print("Set the strategy up ONCE in the browser window now:")
        print("  - Add Position: Nifty / Options / Put / Buy / ATM / 1 lot / Weekly")
        print("  - Tick Range Breakout and set the range fields")
        print("  - Set From Date and To Date, then check the credit notice")
        print("  - Confirm INTRADAY is selected")
        input("Press Enter when ready. The script then only changes the times... ")

        consecutive_failures = 0

        for i, p in enumerate(matrix, start=1):
            result = BacktestResult(**p.as_dict())

            if p.run_id in skip:
                # Leave the existing completed row untouched.
                log(f"[Run {i}/{total}] {p.label} | Status: Skipped (already done)")
                continue

            log(f"[Run {i}/{total}] {p.label} | Status: Running...")

            try:
                text = configure_and_run(page, p, args.dry_run, args.max_credits_per_run)

                if args.dry_run:
                    result.status = "dry-run-ok"
                    log(f"[Run {i}/{total}] {p.label} | Status: Dry run OK")
                else:
                    metrics = extract_metrics(text)
                    if not metrics:
                        raise ValueError("results panel updated but no metrics parsed")
                    for field, value in metrics.items():
                        setattr(result, field, value)
                    result.status = "completed"

                    pnl = result.overall_profit
                    pnl_str = f"{pnl:+,.0f}" if pnl is not None else "n/a"
                    log(
                        f"[Run {i}/{total}] {p.label} | Status: Completed | "
                        f"PnL: {pnl_str} | Win% (Days): {result.win_pct_days}"
                    )

            except Exception as exc:
                result.status = "failed"
                result.error = f"{exc.__class__.__name__}: {exc}"
                save_debug(page, p.run_id)
                log(f"[Run {i}/{total}] {p.label} | Status: FAILED | {result.error}")

                # A results timeout almost always means results_container is
                # wrong. Show what it should be, from the page on screen.
                if "results" in str(exc).lower():
                    suggest_results_container(page)

                consecutive_failures += 1
                if consecutive_failures >= args.max_failures:
                    log(f"\nAborting: {consecutive_failures} runs failed in a row.")
                    log("Every further run would spend a credit on the same fault.")
                    results[p.run_id] = result
                    write_outputs(results, args.dry_run)
                    break

                # Stop rather than burning the rest of the budget on the same
                # misconfiguration.
                if "credits, limit is" in str(exc):
                    log("\nAborting: credit guard tripped. Nothing further will run.")
                    results[p.run_id] = result
                    write_outputs(results, args.dry_run)
                    break

            else:
                consecutive_failures = 0

            results[p.run_id] = result
            write_outputs(results, args.dry_run)
            time.sleep(config.DELAY_BETWEEN_RUNS)

        browser.close()

    attempted = [p.run_id for p in matrix if p.run_id not in skip]
    ok = sum(1 for rid in attempted
             if rid in results and results[rid].status in ("completed", "dry-run-ok"))
    bad = sum(1 for rid in attempted
              if rid in results and results[rid].status == "failed")

    log(f"\nThis session: {ok} succeeded, {bad} failed, of {len(attempted)} attempted.")
    if not args.dry_run:
        total_done = sum(1 for r in results.values() if r.status == "completed")
        log(f"Overall progress: {total_done}/{len(matrix)} runs recorded.")
    log(f"  {config.DRY_CSV_PATH if args.dry_run else config.CSV_PATH}")
    log(f"  {config.DRY_JSON_PATH if args.dry_run else config.JSON_PATH}")

    done = [r for r in results.values() if r.status == "completed"]
    if done:
        df = pd.DataFrame([r.model_dump() for r in done]).sort_values(
            "overall_profit", ascending=False
        )
        log("\nTop 5 by overall profit:")
        cols = ["range_start", "range_end", "exit_time", "overall_profit",
                "win_pct_days", "max_drawdown", "return_to_mdd"]
        log(df[cols].head().to_string(index=False))


if __name__ == "__main__":
    main()
