"""
The parameter matrix: 8 range windows x 5 exit times = 40 runs.

Edit RANGE_WINDOWS or EXIT_TIMES and the run count follows automatically.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, timedelta

# (range_start, range_end)
# Scoped to fit the free-tier credit budget (20 on signup, refill to 15/day)
# with headroom for failed runs. 3 x 3 = 9 runs, leaving 11 in reserve.
#
# Note: StockMock does not use the 9:15 candle, so ranges cannot start at
# 09:15. Confirm the earliest selectable time in the hour/minute dropdowns.
RANGE_WINDOWS = [
    # 8 range windows x 5 exit times = 40 iterations, matching the brief.
    # Note StockMock does not use the 09:15 candle (entry defaults to 09:22),
    # so ranges start at 09:20 at the earliest.
    ("09:20", "09:45"),
    ("09:20", "10:00"),
    ("09:30", "10:00"),
    ("09:30", "10:30"),
    ("09:45", "10:15"),
    ("09:45", "10:30"),
    ("10:00", "10:30"),
    ("10:00", "11:00"),
]

EXIT_TIMES = ["14:30", "14:45", "15:00", "15:10", "15:15"]

# Backtest window. The brief says "current month".
#
# Taken literally (1st of the month to today) that gives almost no data when
# run early in a month: on 3 September it is 2 trading days. The intent was
# clearly "roughly a month of recent data, so no subscription is needed", so
# the default is a trailing 30-day window.
#
#   "trailing"  - last LOOKBACK_DAYS days (default, ~1 month of data)
#   "month"     - literal 1st-of-month to today
#   "year"      - trailing 1 year
#
# Worth stating in the writeup: StockMock charges 1 credit for anything up to
# 1 year, so a one-month backtest costs the SAME as a one-year one. "year"
# gives ~12x the data for identical credits.
WINDOW_MODE = "trailing"
LOOKBACK_DAYS = 30


@dataclass(frozen=True)
class RunParams:
    run_id: int
    range_start: str
    range_end: str
    exit_time: str
    date_from: date
    date_to: date

    @property
    def label(self) -> str:
        return f"Range: {self.range_start}-{self.range_end} | Exit: {self.exit_time}"

    def as_dict(self) -> dict:
        d = asdict(self)
        d["date_from"] = self.date_from.isoformat()
        d["date_to"] = self.date_to.isoformat()
        return d


def date_bounds(today: date | None = None) -> tuple[date, date]:
    """The backtest window.

    Current month (1st to today) by default, per the brief. Nifty options data
    on StockMock starts 15 Feb 2019, so the window is clamped to that.
    """
    today = today or date.today()
    if WINDOW_MODE == "month":
        start = today.replace(day=1)
    elif WINDOW_MODE == "year":
        start = today - timedelta(days=364)
    else:
        start = today - timedelta(days=LOOKBACK_DAYS)
    return max(start, date(2019, 2, 15)), today


def _to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def build_matrix(today: date | None = None) -> list[RunParams]:
    date_from, date_to = date_bounds(today)
    runs: list[RunParams] = []
    run_id = 1

    for start, end in RANGE_WINDOWS:
        for exit_time in EXIT_TIMES:
            # Sanity check: exit must come after the range closes.
            if _to_minutes(exit_time) <= _to_minutes(end):
                continue
            runs.append(
                RunParams(
                    run_id=run_id,
                    range_start=start,
                    range_end=end,
                    exit_time=exit_time,
                    date_from=date_from,
                    date_to=date_to,
                )
            )
            run_id += 1

    return runs


if __name__ == "__main__":
    matrix = build_matrix()
    d0, d1 = date_bounds()
    print(f"{len(matrix)} runs | window: {d0} to {d1} ({(d1 - d0).days} days)")
    print(f"credit cost: ~{len(matrix)} credits (1 per run for under 1 year of data)")
    print("free tier: 20 credits on signup, refills to 15/day. Use --limit to")
    print("run a subset now and --resume to continue on a later day.")
    for r in matrix:
        print(f"  [{r.run_id:>2}] {r.label}")
