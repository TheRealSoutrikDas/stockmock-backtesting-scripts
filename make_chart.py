"""
Build the results visualisation from results/backtest_summary.csv.

    python make_chart.py

Writes results/pnl_by_exit_time.png: a line chart of P&L against exit time
(one series per range window) beside a heatmap of the same grid. Only range
windows with a complete set of exit times are plotted, so a partially
executed matrix does not produce a misleading chart.
"""

from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import config

OUT = config.RESULTS_DIR / "pnl_by_exit_time.png"


def main() -> None:
    df = pd.read_csv(config.CSV_PATH)
    df = df[df["status"] == "completed"]
    if df.empty:
        raise SystemExit("No completed runs in the CSV.")

    df["window"] = df["range_start"] + "-" + df["range_end"]
    exits = sorted(df["exit_time"].unique())

    # Only fully populated windows, so the chart is not misleading.
    full = [w for w, g in df.groupby("window") if len(g) == len(exits)]
    if not full:
        raise SystemExit("No range window has a complete set of exit times.")

    grid = np.array([
        [df[(df.window == w) & (df.exit_time == e)]["overall_profit"].iloc[0]
         for e in exits]
        for w in full
    ])

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.6))

    for w, row in zip(full, grid):
        ax1.plot(exits, row, marker="o", linewidth=2, label=w)
    ax1.axhline(0, color="#444", linewidth=1)
    ax1.set_title("Overall P&L by intraday exit time", fontsize=11)
    ax1.set_xlabel("Exit time")
    ax1.set_ylabel("Overall profit (Rs, 1 lot)")
    ax1.legend(title="Range window", fontsize=8, title_fontsize=8)
    ax1.grid(alpha=0.25)

    lim = np.abs(grid).max()
    im = ax2.imshow(grid, cmap="RdYlGn", vmin=-lim, vmax=lim, aspect="auto")
    ax2.set_xticks(range(len(exits)), exits)
    ax2.set_yticks(range(len(full)), full)
    for i in range(len(full)):
        for j in range(len(exits)):
            ax2.text(j, i, f"{grid[i, j]:+,.0f}", ha="center", va="center", fontsize=9)
    ax2.set_title(f"{len(full)}x{len(exits)} factorial grid (Rs)", fontsize=11)
    ax2.set_xlabel("Exit time")
    ax2.set_ylabel("Range window")
    fig.colorbar(im, ax=ax2, shrink=0.85, label="P&L (Rs)")

    d0, d1 = df["date_from"].iloc[0], df["date_to"].iloc[0]
    fig.suptitle(
        f"NIFTY range-breakout (Buy ATM PE, weekly, no SL/target) | {d0} to {d1}",
        fontsize=12,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(OUT, dpi=150)
    print(f"wrote {OUT}")

    print("\nMain effect of exit time (mean across windows):")
    for j, e in enumerate(exits):
        print(f"  {e}: {grid[:, j].mean():+8.0f}")
    print("\nMain effect of range window (mean across exits):")
    for i, w in enumerate(full):
        print(f"  {w}: {grid[i, :].mean():+8.0f}")


if __name__ == "__main__":
    main()
