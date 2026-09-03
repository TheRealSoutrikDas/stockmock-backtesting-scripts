# Understanding the task

> My understanding of the assessment, written before and during the build.
> The implementation, results and analysis are in [README.md](README.md).

## What I was asked to do

Backtest a simple intraday range-breakout strategy on NIFTY using StockMock,
restricted to the bearish side, and iterate it across 30-40 combinations of
range timings and exit timings. Current week expiry, at-the-money strike, no
stop loss, no target, current month only, free tier only. Then automate the
whole thing rather than clicking through it by hand.

My reading of the intent: the strategy itself is deliberately trivial. What is
being tested is whether I understand what the strategy actually does on this
platform, and whether I can drive the platform reliably enough to produce a
consistent dataset across many parameter combinations.

## How I understand the strategy

Take the high and low of NIFTY over a fixed morning window. That window is
observation only, no position is held. When price breaks out of that band, the
trade fires. Because this is the bearish side, the position taken is a **bought
ATM put** on the current week's expiry.

With no stop loss and no target, the only exit is a fixed clock time, so the
three events happen in strict order:

```
range window  ->  breakout fires entry  ->  hold  ->  square off
(observe only)    (after window closes)    (no SL/target)  (fixed time)
```

That ordering has a consequence I built into the code: an exit time at or
inside the range window is meaningless, because no position exists yet.
`params.py` drops any such combination before it can be run.

I also expected, and confirmed, that not every day produces a trade. If price
never leaves the range, there is no entry and the day's P&L is zero. Seven of
the 23 days in this period were like that, so the effective sample is smaller
than the number of days implies.

## What I had to work out about StockMock

I had not used the platform before, so I worked through the form and confirmed
how each requirement is expressed:

| Requirement | StockMock control |
|---|---|
| NIFTY | Select Index: `Nifty` |
| Put buying | Segment `Options`, Option Type `Put`, Action Type `Buy` |
| At-the-money strike | Strike Price `ATM`, with `Use Spot as ATM` |
| Current week expiry | Expiry Type `Weekly` |
| Range breakout | `Range Breakout` checkbox, which reveals a second time row |
| Range window, e.g. 09:30-10:00 | Entry Time row = start; the row under `Until` = end |
| Intraday exit | Exit Time, with `Same Day` selected |
| No SL, no target | Leave `+ Target Profit` and `+ Stop Loss` unadded |
| Backtest period | From Date / To Date, with `INTRADAY` selected |

Four things were not obvious to me at the start and are worth stating, since
getting any of them wrong would have invalidated the results:

**The range is defined by time only.** I expected to enter price levels.
Ticking Range Breakout instead adds a second *time* row: StockMock derives the
window's high and low itself. So there is nothing to configure about levels,
and no way to invert the breakout direction by mistake.

**There is no direction setting.** I initially looked for a bullish/bearish
toggle. There isn't one, because the direction is already implied by the
position: the leg is a bought PUT. The brief's "bearish" therefore reduces to
the strike-and-side choice, not a separate control.

**Entry Time doubles as the range start.** There is no separate range-start
field. The first time row is both where the observation window opens and where
the trade becomes eligible.

**StockMock states its own interpretation**, e.g. *"High & Low of the Range
will be considered between 09:20 open and 9:44 closing time."* I checked
whether this meant my window was a minute short. It does not: the sentence
names the last *candle* included, and 09:20 through 09:44 is 25 one-minute
candles, exactly the 25-minute window I set. I made the runner log this line
for every iteration so the platform's own reading is recorded next to each
result rather than assumed.

## Judgement calls I made

Two parts of the brief could not be taken literally, so I resolved them and
recorded why.

**"Current month."** Read literally as 1st-of-month to today, this gives two
trading days when run on 3 September, which would produce almost no trades
across 40 cells. I read the intent as "roughly a month of recent data, so no
subscription is needed" and used a trailing 30-day window. `WINDOW_MODE` in
`params.py` switches between `trailing`, `month` and `year`.

**"30-40 iterations" on the free tier.** Each run costs 1 credit; the free tier
gives 20 with a refill to 15 per day; payment was excluded. Those three
constraints cannot all hold in a single day. I defined the full 40-run matrix
in code, validated all 40 at zero cost with a dry run, and executed as many as
the credits allowed. The arithmetic is in "Credit constraint" below.


## What this implies for the automation

Across all 40 iterations only two things change: the **range window** and the
**exit time**. Index, option type, strike, expiry, lot size, dates and the risk
settings are identical throughout.

That is the structural fact the whole design rests on. Because the form does
not need rebuilding per iteration, I set it up once by hand and let the script
drive only the three time dropdowns, which keeps the calendar widgets and the
positions panel out of the automation entirely.

