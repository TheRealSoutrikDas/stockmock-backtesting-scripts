"""
Record backtest results run by run, without automating the browser.

StockMock sits behind Cloudflare bot protection, so the Playwright runner
cannot reach the app. This walks you through the same 15-run matrix by hand
and produces an identical results/backtest_summary.csv and .json, using the
same parser the automated runner would have used.

    python manual_entry.py            # start, or resume where you left off
    python manual_entry.py --show     # print the matrix and what is done

For each run: set the two dropdowns in the browser, click START BACKTEST,
select the stats panel, copy it, paste it here, then press Enter twice.
"""

from __future__ import annotations

import argparse
import json

import pandas as pd

import config
from params import build_matrix
from stockmock_runner import BacktestResult, extract_metrics


def load_existing() -> dict[int, BacktestResult]:
    if not config.CSV_PATH.exists():
        return {}
    df = pd.read_csv(config.CSV_PATH)
    out: dict[int, BacktestResult] = {}
    for row in df.to_dict("records"):
        clean = {k: (None if pd.isna(v) else v) for k, v in row.items()}
        out[int(clean["run_id"])] = BacktestResult(**clean)
    return out


def save(results: dict[int, BacktestResult]) -> None:
    rows = [results[k].model_dump() for k in sorted(results)]
    pd.DataFrame(rows).to_csv(config.CSV_PATH, index=False)
    config.JSON_PATH.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def read_paste() -> str:
    """Read a multi-line paste, ending on a blank line."""
    print("    Paste the stats panel, then press Enter on an empty line.")
    print("    (or type 'skip' to leave this run for later, 'quit' to stop)")
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip().lower() in ("skip", "quit"):
            return line.strip().lower()
        if line.strip() == "" and lines:
            break
        if line.strip():
            lines.append(line)
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true", help="print status and exit")
    args = ap.parse_args()

    matrix = build_matrix()
    results = load_existing()

    if args.show:
        for p in matrix:
            got = results.get(p.run_id)
            mark = "done" if got and got.status == "completed" else "    "
            pnl = f"  PnL {got.overall_profit:+,.0f}" if got and got.overall_profit is not None else ""
            print(f"  [{mark}] Run {p.run_id:>2}  {p.label}{pnl}")
        done = sum(1 for r in results.values() if r.status == "completed")
        print(f"\n{done}/{len(matrix)} recorded")
        return

    todo = [p for p in matrix
            if p.run_id not in results or results[p.run_id].status != "completed"]

    print(f"{len(matrix)} runs total, {len(matrix) - len(todo)} already recorded.\n")

    for p in todo:
        print("=" * 62)
        print(f"Run {p.run_id}/{len(matrix)}")
        print(f"  Range start : {p.range_start}")
        print(f"  Range end   : {p.range_end}")
        print(f"  Exit time   : {p.exit_time}")
        print(f"  Dates       : {p.date_from} to {p.date_to}")
        print("  Set those in the browser, click START BACKTEST, copy the stats.")
        print()

        raw = read_paste()
        if raw == "quit":
            break
        if raw == "skip" or not raw.strip():
            print("  skipped\n")
            continue

        metrics = extract_metrics(raw)
        if not metrics:
            print("  Nothing parsed from that paste. Check you copied the stats")
            print("  panel (Overall Profit, Win% (Days), etc). Skipping.\n")
            continue

        result = BacktestResult(**p.as_dict())
        for field, value in metrics.items():
            setattr(result, field, value)
        result.status = "completed"
        results[p.run_id] = result
        save(results)

        print(f"  Parsed {len(metrics)} metrics:")
        for k, v in metrics.items():
            print(f"    {k:24} {v}")
        print("  Saved.\n")

    done = sum(1 for r in results.values() if r.status == "completed")
    print("=" * 62)
    print(f"{done}/{len(matrix)} recorded")
    print(f"  {config.CSV_PATH}")
    print(f"  {config.JSON_PATH}")

    if done:
        df = pd.DataFrame([results[k].model_dump() for k in sorted(results)])
        df = df[df["status"] == "completed"].sort_values("overall_profit", ascending=False)
        cols = ["range_start", "range_end", "exit_time", "overall_profit",
                "win_pct_days", "max_drawdown", "return_to_mdd"]
        print("\nBest so far:")
        print(df[cols].head().to_string(index=False))


if __name__ == "__main__":
    main()
