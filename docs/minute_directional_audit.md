# Independent exploratory directional audit

Audit date: 6 October 2026. The auditor did not implement the strategy builder,
runner or backtest core. Audit edits are confined to tests and documentation;
the frozen `aster` package was not modified.

## Interpretation before results

This six-hypothesis batch reuses the year and final evaluation months already
examined in the original thirteen policies. It is **exploratory**, even though
each new duration scale is selected using only the first six training months.
Passing later hurdles cannot restore an untouched holdout or establish absence
of overfitting. The six hypotheses also overlap economically: several are trend
models. They cannot be described as six independent proven trading edges.

The chronology remains 5 October 2025–5 October 2026, using actual minute
perpetual trade, mark and funding observations. Training ends 5 April; three
fresh-wallet validation months follow; the reused final evaluation is
5 July–5 October. The one-year endpoint and surviving eight-asset universe are
explicit. Older observations and an hourly source dataset do not supply these
minute-strategy results.

## Reviewed implementation

`examples/minute_directional/signals.py` supplies signed intents for slow EMA,
weekly Donchian breakout, agreeing time-series momentum, signed mean reversion,
BTC-conditioned altcoin lag and a cross-sectional momentum basket. Signals use
completed bars, backward windows and observed-time BTC alignment. A stated
12% close-stop is a completed-close decision; it cannot guarantee an intrabar
fill or a fill at the stop threshold.

`examples/minute_directional/run.py` fixes entry notional at 25% of current
segregated sleeve equity, in the instrument's native perpetual base units.
Quantities remain fixed until a direction change. Leverage is 1 with isolated
margin; short opening principal is not spendable cash. Actual funding is a
separate ledger event and is retained at the terminal valuation boundary.
Native 1000PEPE quantity and bundled prices remain consistent, including funding.

The eight $12,500 sleeves are independently funded. Pooled equity uses the union
of their actual observation clocks and only prior sleeve values at asynchronous
funding times. Assets/exposures add; leverage and utilization ratios are
recomputed. A common duration scale is chosen per hypothesis by pooled training
daily Sharpe; ties prefer scale 1. Holdout neighbors are reported and do not
replace that choice.

Terminal inventory remains marked at actual observations. No terminal order or
invented final-close fill appears. A separate indicative exit reserve applies
configured nominal final-position fees and adverse slippage; it does not alter
cash, fabricate volume or promise a future executable exit. Positive returns
after this diagnostic reserve and zero liquidation events are additional gates.
Baseline fees, adverse costs and the combined doubled-fee/slippage, delayed,
reduced-participation stress are declared assumptions.

## Cross-sectional special cases

The basket requires eight native perpetual identities on the same continuous
minute grid. Missing one instrument observation or a shared interval is an
error; prices are neither interpolated nor forward filled. Daily 00:01 UTC
ranks use already completed seven-day normalized close returns, select two
long and two short assets, and leave four sleeves in cash. Common scaling of
a token's price units cancels in its return, so the native 1000PEPE price scale
does not distort its momentum rank. Tie ordering is fixed by instrument ID.

The cached matrix is guarded by all eight input hashes, the signal-code hash,
cutoff and scale, and the matrix file's own checksum. Each consuming job also
fingerprints the matrix and manifest. Corruption or changed source data fails
validation. The final matrix is computed using only source bars before the
requested cutoff; its prefix is independently invariant to future perturbation.

Basket hedge legs may lose individually. Its preregistered breadth gate therefore
requires actual fills in at least four distinct assets instead of five profitable
individual sleeves. All eight asset P&Ls, including losing legs, remain in the
report and pooled P&L. All aggregate profitability, months, drawdown, costs,
neighbor sensitivity, reserve and zero-liquidation gates still apply. The five
scalar hypotheses retain the five-of-eight profitable-sleeve gate. This economic
distinction was frozen before the new batch produced numerical outcomes.

## Independent verification

`tests/test_minute_directional.py` contains **28 passing cases** covering:

- Prefix and future-OHLC perturbation invariance for all five scalar families,
  with actual long and short intent in each comparison; gap warmup reset.
- Zero/one-minute delayed signed flips; fixed quantities between unchanged
  intents; no derivative principal credit; actual positive short funding.
- Native 1000PEPE funding and marked terminal positions without fabricated exits.
- A completed-close stop that subsequently exits at a worse opening gap, rather
  than being granted its configured stop price.
- Nonmutating indicative exit reserves; pooled reserve arithmetic; asynchronous
  prior-only sleeve pooling; actual liquidation counts.
- Training-only scale selection and deterministic central-scale tie preference.
- Millisecond, microsecond and nanosecond bootstrap timestamps retaining real
  terminal P&L without changing the source ledger.
- Cross-sectional warmup, two-long/two-short counts, unit-normalized returns,
  sorted-input invariance, prefix causality and strict missing-grid rejection.
- Matrix-cache corruption/source-change rejection and the actual summary's
  three-versus-four participating-asset gate while retaining losing hedge legs.

Final integrated prelaunch verification: **177 repository tests passed in
2.47 seconds**. No known unresolved high/medium material defect was found in
the current six-hypothesis code. This is implementation evidence; actual
historical winners and stress outcomes are unknown at signoff.

## Statistical and execution limits

Nineteen cumulative policy/hypothesis comparisons are disclosed. The conditional
seven-day circular block bootstrap uses 10,000 seeded samples and Bonferroni
tails `0.05 / 38` and `1 - 0.05 / 38`. This diagnostic does not correct the full
research adaptation involved in constructing new hypotheses after viewing the
old outcomes, nor eliminate nonstationary-regime or short-sample uncertainty.

The candle model cannot prove queue priority, depth or intraminute mark
liquidation. Current contract rules approximate historical rules. Equal counts
of long/short sleeves do not establish beta neutrality; fixed quantity and
independent fills allow notional drift and leg exposure. Marked-open returns
are distinct from executable realized cash. Report all failures and original
results, and call any new hurdle passer an exploratory historical result rather
than a guaranteed robust or non-overfit strategy.
