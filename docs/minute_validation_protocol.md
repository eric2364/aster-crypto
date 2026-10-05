# Trailing-year minute strategy validation protocol

Prepared independently on 6 October 2026. This protocol defines evidence needed
to describe an example as passing historical robustness checks. It cannot
guarantee a profitable or non-overfit strategy. Finding four or five successful
examples is a research target; the number of reported passers must follow the
evidence. Failed candidates remain visible.

## Freeze the research contract before testing

Record one UTC end boundary `E`, representing the last fully available minute,
and request exactly `[E - 1 calendar year, E)`. Every signal, tuning observation,
warmup bar and return must be inside this interval. Use actual one-minute source
bars throughout. Sampling a minute dataset at hourly decision times is allowed
if explicitly described, but hourly source data cannot be labelled a minute
backtest. A stale archive endpoint must be disclosed rather than presented as
the current trailing year.

Freeze candidate strategy families, the DOGE/PEPE and other altcoin universe,
parameter grids, risk sizing, trading costs, execution assumptions, selection
objective and pass/fail thresholds before opening the final holdout. Preserve
the strategy source hash and the full trial ledger. Count changes to symbols,
directions, exits, lookbacks, fees and date ranges as research trials. Subsequent
holdout-driven revisions invalidate the untouched-holdout label.

## Chronological split within the same year

Use calendar boundaries derived from `E`; do not mix the prior hourly study or
older years into this evaluation.

| Segment | Bounds | Permitted use |
| --- | --- | --- |
| Development | `[E-12 months, E-6 months)` | Indicator design, small documented parameter grid, training-only selection |
| Rolling validation | `[E-6 months, E-3 months)` | Three successive monthly forward folds; parameters chosen using only the earlier development/validation observations available at each boundary |
| Final holdout | `[E-3 months, E)` | One locked final evaluation; no tuning, symbol replacement or strategy redesign |

Training and evaluation candles must finish within their respective intervals.
No overlapping exposure or label from a training segment may leak into a test
segment. Deterministic backward-looking indicators need no arbitrary fixed
embargo if their warmup ends before the decision; learned forward-return targets
must purge training examples whose target horizon crosses the boundary and
declare any further embargo. Warmup uses only earlier bars inside this year.

Before a test begins, freeze the chosen parameters. Warmup observations may build
indicator state but cannot produce evaluated trades or returns. Test sizing
starts from its declared cash and empty positions; retain that convention across
all candidates. Existing generic walk-forward helpers restart both accounts and
indicators, so they cannot claim warm-started continuous trading without an
explicit implementation. Report a continuous holdout portfolio separately from
fresh-account fold results; summing fold profits is not a self-financing curve.

## Market data and instrument validity

Require checksum-verified official data, exact minute coverage, distinct
instrument identities, and matching historical marks/funding for perpetuals.
Repair an archive omission only with a verified source observation. Never fill
a missing minute with an interpolated tradable price or invented funding zero.
Record source URLs, checksums, observed coverage, all repairs and unresolved
funding-cadence uncertainty. A settlement with a missing mark fails validation.

Record the exact exchange symbol, quoted base unit, lot/tick/minimum-notional
constraints, fees, listing interval and leverage limits. A `1000PEPE` derivative
is quoted per bundle of 1000 PEPE; preserve that unit in quantity, price,
funding and marks. Do not combine PEPE spot prices and bundled derivative
quantities without an explicit conversion. Extremely small PEPE spot prices need
an appropriate tick size; generic BTC defaults are invalid assumptions.

A hand-picked universe of presently listed DOGE/PEPE and other surviving assets
does not establish a historical survivorship-free universe. Report that the
claims concern these named instruments only. To make a broader altcoin-universe
claim, reconstruct dated membership including delisted/failed symbols and
include their outcomes. An asset lacking the full requested year cannot silently
replace a failed asset or contribute a shorter period labelled a year.

## Execution and causal audit

The completed minute's high/low/close/volume become visible at its end. A signal
based on that completion can execute only at the next eligible opening
observation after activation. Positive latency may miss the adjacent minute
open. Opening capacity uses completed prior volume. Stops must not invent a
high/low path that guarantees both favorable triggering and execution.

Before interpreting returns, verify that perturbing all future prices, volumes,
marks and funding leaves past signals and orders unchanged. Mutating an
unavailable next-minute volume cannot change an opening fill. Batch simultaneous
symbols consistently; test changes to symbol iteration order. Perpetual shorts
must carry actual fees, funding, collateral and liquidation risk; short proceeds
are not spendable principal. Separate venue wallets and retain negative balances.
All account equity must reconcile to fills, realized/unrealized P&L, trading
fees, funding and liquidation costs. Slippage already embedded in execution
prices must not be deducted twice.

## Prespecified practical hurdles

These numerical hurdles are proposed engineering conventions, not statistically
derived confidence guarantees. Apply identical thresholds to every candidate
before revealing holdout results; declare any departure explicitly.

| Check | Proposed passing requirement |
| --- | --- |
| Final holdout | Positive net return after all configured costs; daily-return Sharpe at least 0.5; maximum drawdown no more than 20%; no liquidation or insolvent balance |
| Monthly consistency | At least two of the three final holdout months positive; report all three and all validation folds |
| Sample sufficiency | At least 30 separately completed position episodes in the holdout for a frequent-trading claim; ledger partial closes do not count as independent episodes |
| Cost resilience | Positive holdout return under a combined two-times trading-fee schedule and two-times baseline adverse slippage; disclose absolute bps and fixed/spread profile |
| Execution sensitivity | Run one additional minute of activation delay and half participation; disclose all results. A sign reversal under either fails the stated robustness hurdle |
| Parameter neighborhood | Vary each numeric lookback/threshold individually by approximately ±20%, using distinct valid integer/grid values; at least 75% of feasible neighboring cases retain positive net holdout return under the same costs |
| Concentration | Report largest day, month, instrument and position episode contributions; flag dependence on one episode or liquidation/gap event |

Neighbor tests are evaluations of the frozen family, not a new search for the
best holdout variant. A failed central model cannot be relabelled successful
by promoting a positive neighbor. Portfolio-level strategies report instrument
attribution and leg risk; four highly correlated parameter variants are not
four distinct economic strategy families.

Report same-period cash and suitable buy/hold benchmarks, including their risk
and costs. Positive return does not imply benchmark outperformance; mean
reversion and market-neutral models should additionally show their actual
exposure and market beta where the daily sample permits estimation.

## Dependence, uncertainty and multiple testing

One year contains many minute bars but only about 365 daily observations and
one final three-month holdout. Minute counts and fractional trade closes are not
independent sample counts. Preserve temporal dependence when assessing sampling
uncertainty; a daily-return block bootstrap can be a useful descriptive
sensitivity test if its stationarity assumptions and block lengths are reported.
The [original stationary-bootstrap paper](https://www.tandfonline.com/doi/abs/10.1080/01621459.1994.10476870)
provides the methodological basis for resampling dependent observations.

Retain every tested candidate and parameter combination. A maximum historical
Sharpe is inflated by searching many alternatives. Where the complete trial
return matrix is available, compute a correctly implemented selection-adjusted
diagnostic such as the [Deflated Sharpe Ratio](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf),
and state its assumptions about trial dependence, return shape and sample length.
Do not report an ordinary one-model p-value as if only one strategy had been
tried. If such a diagnostic is not implemented, label the outcome as passing
practical historical checks with unresolved statistical selection risk; do not
invent a numerical non-overfit probability.

## Required deliverables and truthful labels

Publish a row for every candidate showing source/data interval, split bounds,
exact parameters, number of trials, validation folds, final holdout net return,
daily Sharpe/sample count, drawdown, episodes, monthly returns, all stress runs,
neighborhood results and pass/fail reasons. Retain underlying equity, fills,
positions, trades, funding, configuration and provenance. State whether terminal
inventory is marked or forcibly closed and how its costs are handled.

Use “passed the specified historical robustness checks” only for candidates
meeting the frozen hurdles. Use “profitable in this backtest, robustness failed”
or “did not pass” for the others. If fewer than four or five pass, report the
actual count and explain the failed conditions. A locked forward paper-trading
evaluation after this historical study supplies additional evidence; it cannot
be replaced by repeatedly reopening the same three holdout months.

## Frozen contract for the implemented study

The runner at `examples/minute_research/run.py` fixes the year to
`2025-10-05 00:00 UTC` through `2026-10-05 00:00 UTC`, with training ending
5 April and holdout beginning 5 July. This endpoint is 5 October rather than
the latest minute of 6 October; reports must preserve those actual dates.
BTC, ETH, DOGE, PEPE, SOL, XRP, LINK and ADA are eight segregated spot long/cash
sleeves, initially $12,500 each. Quantities are fixed after a 95% entry sizing
decision until exit; there is no automatic minute-by-minute resizing or capital
transfer between sleeves.

Eight fixed signal families test duration scales 0.8, 1.0 and 1.2. Five use
target-price features and three use observed BTC-leading or funding factors.
The scope expanded before any holdout evaluation; both the old and new training
trials remain part of the trial ledger. One common
scale per family is selected by pooled training daily Sharpe across all eight
symbols. The three validation months use fresh accounts. Every holdout scale
is reported, and the training-selected scale alone supplies the primary result.
Holdout neighbor outcomes must not change that selection.

Baseline spot fees are 10 bps per side. Baseline adverse slippage is 2 bps for
BTC/ETH, 8 bps for DOGE/PEPE and 5 bps for the remaining symbols. The joint
stress doubles both fees and adverse slippage, adds one minute of activation
delay and halves participation from 5% to 2.5%. These are declared simulations
rather than observations of the actual historical bid/ask or fee tier.

The adopted runner hurdles require positive validation-fold compounded return,
positive primary holdout return, at least two positive anchored holdout months,
daily Sharpe at least 0.5, drawdown at most 20%, positive combined stress,
positive returns at all three scales and at least five of eight positive symbol
sleeves. The validation product is a hypothetical reinvestment of independent
fold returns, not a continuous ledger. Holdout minute snapshots are required
for the drawdown hurdle. Training/validation summaries may be sampled less
frequently and must disclose that limitation.

These adopted hurdles differ from the broader proposed protocol above: they
do not automatically enforce 30 independent position episodes, individual
parameter perturbations or a statistical-confidence hurdle. Report these
differences rather than claim every proposed check was implemented. Confidence
diagnostics use preregistered seven-day circular daily-return blocks and 10,000
seeded draws. Per-family 95% intervals and simultaneous Bonferroni intervals
using per-tail probability `0.05 / (2 × 8)` for the eight fixed families are
descriptive; even all-positive bounds cannot prove absence
of overfitting, especially with roughly 90 holdout days and nonstationary crypto
markets. Compounded-return intervals and mean-daily-return intervals are
different statistics and must be labelled by their actual estimand.

## Independent implementation verification

`tests/test_minute_research.py` independently checks every family's prefix
invariance after perturbing future OHLC/volume and after truncating a partially
completed 15-minute indicator bucket. Actual entries exist in each comparison.
It also checks gap warmup reset, microsecond-resolution timestamp schedules,
invalid inputs, block-bootstrap reproducibility and constant-return arithmetic,
and portfolio ratio recomputation after adding segregated sleeve assets.

The review found and the runner author corrected a high-severity hurdle bug:
drawdown is a positive loss fraction, so `drawdown >= -0.2` accepted every
ordinary drawdown. The corrected check is `drawdown <= 0.2`; a regression runs
the actual summary path and requires all mock candidates with 80% drawdown
to fail. Sleeve leverage/utilization ratios are recomputed after asset sums.
Cached outputs must match runner, strategy, input data and configuration
fingerprints; a metrics file alone is not evidence of a current evaluation.

The leading-factor review found a high-severity availability error: settlement
`timestamp` took precedence over supplied later `available_at`, exposing a
published rate before its recorded receipt. The author corrected the builder
to use receipt time, validate receipt not earlier than settlement, and add the
configured observation lag after receipt. The regression models a negative
1000PEPE settlement at minute 50 received at minute 150; the mapped PEPE spot
strategy must remain cash before minute 151. The explanatory funding rate is
dimensionless; its verified spot identity mapping is explicit, and no bundled
price or derivative quantity is mixed into the spot execution ledger.

BTC observations become usable after their bar ends plus an extra minute and
expire after the stated stale tolerance. BTC-target self-leading sleeves remain
cash. A SOL/ETH bar frame cannot masquerade as the BTC leader. Funding and target
price gaps do not silently supply future values. QQQ input is explicitly rejected
until historical receipt-time and alignment rules are implemented; no Nasdaq or
macroeconomic edge is claimed by these tests.

The bootstrap review also corrected dropping the genuine terminal midnight
valuation change. The terminal observation is assigned to the last completed
trading day before resampling; an independent test requires a final 50% gain to
remain in the return intervals. The analysis copy is explicitly converted to
nanosecond datetime precision before assigning the endpoint offset, so actual
Parquet millisecond, microsecond and nanosecond columns all work. The original
equity ledger is preserved.

Independent verification at this revision: **29 minute/factor/protocol tests
passed; 129 tests passed in the complete repository suite (1.98 seconds)**.
No known unresolved high/medium defect remains from this review. These are
implementation checks; historical profitability, stress survival and the number
of candidates passing the adopted hurdles require the actual root-run outputs.

## Separate fixed funding-carry policy study

`examples/minute_carry/run.py` adds five policies of **one economic carry
family**, frozen before numerical outcomes were inspected. The broader study
therefore has eight initial strategy families plus one carry family; screening
all five carry variants separately creates thirteen policy-level outcome tests.
Five positive carry policies cannot be presented as five independent successful
economic strategies. Carry diagnostics use conservative thirteen-policy
Bonferroni tails; any combined confidence claim across both studies must also
account for thirteen policy tests for the original eight results.

Each fresh $12,500 sleeve plans 30% of its initial capital in long spot and the
same native base exposure in a short perpetual, with isolated leverage 2.
Collateral is reserved within cash, not expensed or added to equity. Original
perpetual funding cashflows and marks are retained in their native units.
One 1000PEPE perpetual quantity unit matches 1,000 spot PEPE units. A common
decimal lot grid makes both submitted quantities valid without manufacturing
matched fills. Independent leg volume and latency still allow partial exposure
and liquidation; holding equal planned notionals does not guarantee an atomic
market-neutral position.

The five fixed policies use always-hedged exposure, positive trailing published
funding, cross-asset funding rotation, funding hysteresis and explicit risk
filters. All retain negative funding costs when held. Past settlements become
predictor observations only after a declared minute of publication lag, and
the trailing-three observation rule does not inspect upcoming rates. Rotation
selects from the fixed universe using only those past observations. This
assumed lag is not a reconstruction of actual exchange receipt timestamps.

The audit found a high-severity terminal-order defect: repeated flatten calls
cancelled the prior delayed close immediately before its last eligible opening
fill, then submitted a new close too late to execute. The author corrected this
with a once-submitted terminal close and preserved GTC closing orders. Terminal
orders are planned two minutes before the known end. The engine uses actual
future eligible opening observations, rather than an invented final-close fill.
Residual positions remain marked and must fail the explicit terminal-flat
mechanical hurdle. No final funding settlement may disappear merely because
its timestamp equals the valuation boundary; a residual short owing negative
funding at that boundary must pay it.

`tests/test_minute_carry.py` contains twelve independent cases: native PEPE and
ordinary units; hand-derived cash/collateral/funding conservation; decimal
hedge grids; one-minute funding availability and future perturbation; causal
cross-asset rankings; zero/one-minute delayed terminal execution with ample
liquidity; truthful zero-liquidity residuals; owed terminal negative funding;
actual runner funding-boundary filtering; and prior-only union-clock equity
aggregation across independently timed sleeves. These tests did not modify
the frozen `aster` package.

Independent integrated verification after the carry corrections:
**141 repository tests passed in 2.00 seconds**, including all twelve carry
tests. No known unresolved high/medium defect remains from this carry review.
Actual validation/holdout success, basis risk, fee stress and liquidation
outcomes remain matters for the retained real-data runs, not these synthetic
implementation checks.

## Postprocessing-only datetime repair

The 640 price/factor simulations completed before the final summary encountered
a dtype error: assigning a microsecond endpoint adjustment into the actual
millisecond Parquet timestamp column failed. The executed runner was preserved
at `results/minute-study-1y/reproducibility/executed_runner.py`. Independent
comparison confirms the repaired runner adds only the datetime-to-nanosecond
cast inside bootstrap postprocessing; signal construction, chosen parameters,
orders, costs and simulation ledgers did not change.

`examples/minute_research/analyze.py` reconstructs summaries from completed
ledgers and the retained training-selection file. It calls aggregation and
bootstrap postprocessing rather than model simulation or parameter search.
Repairs must preserve the executed-source hash and verify the recorded model
and market-input fingerprints; actual simulation outputs are not replaced.
The recovery additionally checks all instrument, BTC-leader and funding source
hashes; requires the exact set of 640 distinct locked trial identities; and
recomputes each retained selection using the original training-only objective
and deterministic tie break. This is a consistency check of the prior choice,
not a new holdout search.
Parameterized regressions cover real Parquet timestamp units `ms`, `us` and
`ns` in both the runner bootstrap and the report's combined thirteen-policy
confidence diagnostic, including the terminal valuation and original-ledger
preservation. These analysis repairs do not reopen the holdout for tuning.
The retained price/factor summary contains eight families and **zero passes**
under its frozen historical hurdles. That observed result must not be converted
into claimed successful examples by changing parameters, costs or thresholds
afterward. The carry policy study remains a separately frozen evaluation.
