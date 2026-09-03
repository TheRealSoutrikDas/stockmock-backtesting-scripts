"""Mock-based verification of the runner's logic. No browser needed."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
config.RESULT_TIMEOUT_MS = 4000
config.DELAY_BETWEEN_RUNS = 0
config.BACKOFF_BASE_SECONDS = 0.01
import stockmock_runner as R

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + ("  " + detail if detail and not cond else ""))

# ---------- mock DOM ----------
class Sel:
    def __init__(self, options, value):
        self.options, self.value = options, value
    def select_option(self, label=None):
        if label not in self.options:
            raise Exception(f"no option {label!r}")
        self.value = label
    def input_value(self): return self.value
    def wait_for(self, timeout=None): pass

class Loc:
    def __init__(self, items): self.items = items
    def nth(self, i):
        if i >= len(self.items): raise Exception("index out of range")
        return self.items[i]
    @property
    def first(self): return self.items[0]

class Text:
    def __init__(self, page, key): self.page, self.key = page, key
    def inner_text(self, timeout=None):
        v = self.page.texts.get(self.key)
        if v is None: raise Exception("not found")
        return v

class MockPage:
    """Simulates StockMock: hour/minute selects, a credit notice, and a
    results panel that keeps its OLD text for a while after clicking run."""
    def __init__(self, result_delay=1.0, credit="This backtest result will consume 1 Credit"):
        HOURS = [str(h) for h in range(9, 16)]
        MINS = [f"{m:02d}" for m in range(0, 60)]
        self.entry = [Sel(HOURS, "9"), Sel(MINS, "22")]     # range start
        self.until = [Sel(HOURS, "9"), Sel(MINS, "31")]     # range end
        self.exit = [Sel(HOURS, "15"), Sel(MINS, "15")]
        self.texts = {"credit": credit,
                      "helper": "High & Low of the Range will be considered "
                                "between 9:22 open and 9:30 closing time."}
        self.result_delay = result_delay
        self.run_clicked_at = None
        self.run_count = 0
        self.clicks = []
    def locator(self, sel):
        if "Entry Time:" in sel: return Loc(self.entry)
        if "Until" in sel: return Loc(self.until)
        if "Exit Time:" in sel: return Loc(self.exit)
        if "High & Low" in sel: return Loc([Text(self, "helper")])
        if "Credit" in sel: return Loc([Text(self, "credit")])
        if sel == config.SELECTORS["results_container"]:
            return Loc([Text(self, "results")])
        return Loc([])
    def click(self, sel):
        self.clicks.append(sel)
        self.run_clicked_at = time.time()
        self.run_count += 1
    def wait_for_timeout(self, ms):
        time.sleep(ms / 1000)
        # results appear only after the delay, then reflect the CURRENT times
        if self.run_clicked_at and time.time() - self.run_clicked_at >= self.result_delay:
            self.texts["results"] = (
                f"Overall Profit Rs{1000 * self.run_count}\n"
                f"Win% (Days) 4{self.run_count}% (8)\n"
                f"Max Drawdown (MDD) Rs-{500 * self.run_count} (15 Days)\n"
                f"Return To MDD Ratio 4.65")

print("\n=== 1. parse_number ===")
cases = [("Rs1,23,456.50",123456.5),("36% (8)",36.0),("Rs-14775 (15 Days)",-14775.0),
         ("(1,200)",-1200.0),("62.5%",62.5),("NA",None),("2 Days",2.0),("",None)]
for raw, want in cases:
    got = R.parse_number(raw)
    check(f"parse_number({raw!r}) == {want}", got == want, f"got {got}")

print("\n=== 1b. real StockMock output (regression) ===")
REAL = """Estimated Margin (On Non Expiry)
Rs 1,625
Overall Profit
Rs 3972 (244%)
Avg Day Profit
Rs 248 (15.26%)
Max Profit
Rs 1980 (121.85%)
Max Loss
Rs -882 (-54.28%)
Win% (Days)
44% (7)
Loss% (Days)
56% (9)
Avg Monthly Profit
Rs 3843 (236.49%)
Avg Profit On Win Days
Rs 1055 (64.92%)
Avg Loss On Loss Days
Rs -379 (-23.32%)
Max Drawdown (MDD)
Rs -1117(-68.74%)
MDD Days (Recovery Period)
19 (5 Days)
Return to MDD Ratio
NA
Max Winning Streak
2 Days
Max Losing Streak
3 Days
Expectancy
NA"""
EXPECT = {"estimated_margin":1625.0,"overall_profit":3972.0,"avg_day_profit":248.0,
          "max_profit":1980.0,"max_loss":-882.0,"win_pct_days":44.0,
          "loss_pct_days":56.0,"avg_monthly_profit":3843.0,
          "avg_profit_win_days":1055.0,"avg_loss_loss_days":-379.0,
          "max_drawdown":-1117.0,"max_winning_streak":2.0,"max_losing_streak":3.0}
_got = R.extract_metrics(REAL)
for _k, _v in EXPECT.items():
    check(f"real output: {_k} == {_v}", _got.get(_k) == _v, f"got {_got.get(_k)!r}")
check("real output: 'NA' fields left empty",
      "return_to_mdd" not in _got and "expectancy" not in _got, f"got {_got}")
check("real output: pct in parens not mistaken for the value",
      _got.get("overall_profit") == 3972.0, "244% was picked up instead")

print("\n=== 2. parse_credit_cost ===")
check("reads 1 credit", R.parse_credit_cost("This backtest result will consume 1 Credit") == 1)
check("reads 3 credits", R.parse_credit_cost("will consume 3 Credits") == 3)
check("None when absent", R.parse_credit_cost("no notice here") is None)

print("\n=== 3. set_time drives the right dropdowns ===")
pg = MockPage()
R.set_time(pg, "Exit Time:", "14:30", "exit time")
check("exit hour set to 14", pg.exit[0].value == "14", f"got {pg.exit[0].value}")
check("exit minute set to 30", pg.exit[1].value == "30", f"got {pg.exit[1].value}")
check("entry dropdowns untouched", pg.entry[0].value == "9" and pg.entry[1].value == "22")

R.set_time(pg, "Entry Time:", "09:45", "range start")
check("unpadded hour '9' matched from '09'", pg.entry[0].value == "9", f"got {pg.entry[0].value}")
check("entry minute set to 45", pg.entry[1].value == "45")

print("\n=== 4. set_time rejects an unavailable time ===")
pg2 = MockPage()
try:
    R.set_time(pg2, "Exit Time:", "16:45", "exit time")
    check("raises when hour not selectable", False, "no exception")
except Exception as e:
    check("raises when hour not selectable", "16" in str(e) or "failed" in str(e))

print("\n=== 5. STALE RESULTS (the credit-losing bug) ===")
pg3 = MockPage(result_delay=1.0)
pg3.texts["results"] = "Overall Profit Rs9999\nWin% (Days) 99% (8)"   # previous run
stale = pg3.texts["results"]
t0 = time.time()
pg3.click("run"); 
fresh = R.wait_for_fresh_results(pg3, stale)
elapsed = time.time() - t0
check("does NOT return the stale panel", "9999" not in fresh, f"returned stale: {fresh[:40]}")
check("waited for the new results", elapsed >= 1.0, f"returned after {elapsed:.2f}s")
check("returned the new numbers", "1000" in fresh)

print("\n=== 6. wait_for_fresh_results times out instead of hanging ===")
pg4 = MockPage(result_delay=999)
pg4.texts["results"] = "unchanged"
try:
    R.wait_for_fresh_results(pg4, "unchanged")
    check("raises TimeoutError when results never update", False, "no exception")
except TimeoutError:
    check("raises TimeoutError when results never update", True)

print("\n=== 7. credit guard ===")
from params import RunParams
from datetime import date
p = RunParams(1, "09:30", "10:00", "14:30", date(2025,9,1), date(2026,9,1))
pg5 = MockPage(credit="This backtest result will consume 3 Credits")
try:
    R.configure_and_run(pg5, p, dry_run=False, max_credits=1)
    check("blocks a 3-credit run when limit is 1", False, "it clicked run")
except ValueError as e:
    check("blocks a 3-credit run when limit is 1", "3 credits" in str(e))
check("START BACKTEST was never clicked", pg5.run_count == 0, f"clicked {pg5.run_count}x")

print("\n=== 8. dry run spends nothing ===")
pg6 = MockPage()
out = R.configure_and_run(pg6, p, dry_run=True, max_credits=1)
check("dry run does not click run", pg6.run_count == 0)
check("dry run still moved the dropdowns", pg6.exit[0].value == "14" and pg6.exit[1].value == "30")

print("\n=== 9. preflight catches unset range anchors ===")
from params import build_matrix
saved = (config.SELECTORS["range_start_anchor"], config.SELECTORS["range_end_anchor"])
config.SELECTORS["range_start_anchor"] = None
config.SELECTORS["range_end_anchor"] = None
try:
    R.preflight(build_matrix())
    check("aborts when range anchors are unset", False, "preflight passed")
except SystemExit:
    check("aborts when range anchors are unset", True)
config.SELECTORS["range_start_anchor"] = "Range Start:"
config.SELECTORS["range_end_anchor"] = "Range End:"
try:
    R.preflight(build_matrix()); check("passes once anchors are set", True)
except SystemExit:
    check("passes once anchors are set", False)
config.SELECTORS["range_start_anchor"], config.SELECTORS["range_end_anchor"] = saved

print("\n=== 10. end-to-end: 3 runs give 3 DIFFERENT results ===")
config.SELECTORS["range_start_anchor"] = "Entry Time:"
config.SELECTORS["range_end_anchor"] = "Until"
pg7 = MockPage(result_delay=0.6)
rows = []
for i, exit_t in enumerate(["14:30", "15:00", "15:15"], 1):
    pp = RunParams(i, "09:30", "10:00", exit_t, date(2025,9,1), date(2026,9,1))
    txt = R.configure_and_run(pg7, pp, dry_run=False, max_credits=1)
    rows.append(R.extract_metrics(txt))
check("3 runs clicked run 3 times", pg7.run_count == 3, f"got {pg7.run_count}")
check("range start set to 09:30", pg7.entry[0].value=="9" and pg7.entry[1].value=="30",
      f"got {pg7.entry[0].value}:{pg7.entry[1].value}")
check("range end set to 10:00", pg7.until[0].value=="10" and pg7.until[1].value=="00",
      f"got {pg7.until[0].value}:{pg7.until[1].value}")
profits = [r.get("overall_profit") for r in rows]
check("each run returned distinct numbers", len(set(profits)) == 3, f"got {profits}")
check("metrics parsed on every run", all(len(r) >= 4 for r in rows), f"{rows}")
config.SELECTORS["range_start_anchor"] = saved[0]

print("\n" + "="*58)
print(f"PASSED {len(PASS)} / {len(PASS)+len(FAIL)}")
if FAIL:
    print("FAILURES:"); [print("  - "+f) for f in FAIL]; sys.exit(1)
print("All checks passed.")
