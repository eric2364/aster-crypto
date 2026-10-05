# External-factor and aggressive-flow experiments

This exploratory cohort introduces five hypotheses: QQQ transmission, actual
CPI acceleration, funding crowding, spot/perpetual premium and aggressive trade
flow. It follows nineteen unsuccessful policies on the same historical year.
The reused evaluation period cannot establish absence of overfitting. Funding
and premium mechanisms overlap earlier carry research; five names are not five
demonstrated independent edges.

All target data and external observations are confined to **5 October 2025–
5 October 2026 UTC**, end exclusive. Eight underlyings include DOGE, PEPE and
BTC, ETH, SOL, XRP, LINK and ADA. Execution uses actual minute futures candles,
separate marks and settlement funding, with native 1000PEPE units.

## Inputs and reproduction

Install from the repository root as described in the [manual](../../docs/user_manual.md).
The existing minute collectors create the original source archives:

```bash
.venv/bin/python examples/minute_research/download.py --workers 2
.venv/bin/python examples/minute_research/downloadcarry.py --workers 2
.venv/bin/python examples/external_factors/download_qqq.py
.venv/bin/python examples/external_factors/download_qqq.py --verify-only
.venv/bin/python examples/external_factors/extract_flow.py
.venv/bin/python examples/external_factors/extract_flow.py --verify-only
mkdir -p data_cache/external-factors-1y/cpi
cp -R examples/external_factors/cpi_source_snapshot/. data_cache/external-factors-1y/cpi/
.venv/bin/python examples/external_factors/download_cpi.py --offline
```

QQQ consists of 250 actual Yahoo Finance daily observations. The exact
session-date set agrees with pinned Nasdaq full-day closures. Unadjusted closes
become usable at an **assumed next UTC midnight**; the vendor morning session
label is not closing-price availability. Current adjusted closes are unused.
Historical delivery and correction vintages remain unknown. This is daily
risk-information research rather than evidence of an intraday QQQ lead.

CPI consists of eleven BLS archived first-release events. The actual release
paragraph supplies Eastern time, converted with daylight saving. Availability
adds an explicit one-minute assumed ingestion lag. October 2025 stays absent;
November monthly changes stay missing. No pre-year baseline, interpolation,
economist consensus or inflation surprise exists. See [source coverage](../../docs/cpi_factor_sources.md).
Direct BLS HTTPS is blocked in this environment; pinned official-page rendered
responses are explicitly identified as such. Offline mode requires that pinned
cache. A compact `cpi_source_snapshot/` bundle preserves those exact public
official-page rendered responses and their hashes for offline reproduction;
it does not claim publisher-original HTTP bytes. Where direct access works,
use `download_cpi.py --refresh` to acquire
original HTML from links discovered in the official index.

Aggressive-flow extraction performs no new network download. It uses only
trade klines from the already checksum-verified archives, excludes valuation
mark archives, and verifies total volume against the Engine input for every
minute and native instrument. Authentic taker-buy volume is aggregate aggressive
trade flow, not order-book imbalance, queue depth or liquidation identity.

Raw market datasets and full simulation outputs stay outside Git. All collectors
preserve hashes and fail on missing, invalid or changed records. New downloads
can differ from the recorded vendor vintages and must use a fresh output folder.

## Frozen experiment

The [economic definitions](proposed_protocol.md) state fixed signs, thresholds,
decision clocks, gaps, stale periods and exits. Only duration scales 0.8, 1 and
1.2 vary. Synthetic causality tests and the runner audit precede numerical market
results. No prior model or simulation is overwritten.

The first six months choose one common duration scale per model using pooled
training Sharpe. Three fresh-account monthly validation folds follow. The final
quarter is reused evaluation, reporting all three neighboring scales plus the
joint execution stress. Five models and eight assets produce 400 simulations.
There are now twenty-four cumulative hypotheses/policies if all five complete;
their conditional multiplicity adjustment does not remove adaptive design bias.

Each $12,500 sleeve enters 25% current-equity notional, uses isolated leverage
one and keeps native contract quantity fixed between direction transitions.
Actual trading fees and funding cashflows reconcile. Base taker fees are 5 bps;
slippage is 2/5/8 bps by asset class. Stress doubles fees/slippage, delays one
minute and halves prior-volume participation. Terminal positions remain marked;
an indicative exit reserve is diagnostic rather than a fabricated fill.

The unchanged historical hurdles require positive validation, evaluation, stress
and all neighbors; positive reserve-adjusted diagnostics; two positive evaluation
months; Sharpe at least 0.5; drawdown at most 20%; five profitable sleeves; and
no simulated liquidation across relevant phases. Sparse CPI events must remain
visible. Eight exposures to one release are not eight independent announcements.
These are slower decisions executed on minute data, not demonstrated one-minute
scalping. A hurdle pass cannot establish durable future profitability.

## Run and inspect the demonstration

From the repository root after preparing and verifying the datasets above:

```bash
.venv/bin/python examples/external_factors/run.py --freeze-only
.venv/bin/python examples/external_factors/run.py --workers 4
.venv/bin/python examples/external_factors/update_results.py
.venv/bin/python -m http.server 8765 --bind 127.0.0.1
```

Open `http://127.0.0.1:8765/docs/external_factor_results/report.html`.
The compact example includes every declared trial, selected parameters, monthly
activity, fills, funding, remaining positions, failure gates and source identities.
Full execution ledgers remain under `results/external-factor-1y/`. Use one worker
on a memory-constrained computer. The runner checks frozen source/data hashes
and cached execution receipts before reuse; changed inputs require a new output
folder. `--report-only` rebuilds presentation from completed results, and
`update_results.py` combines all twenty-four disclosed candidates without
changing their simulations.

The real demonstration spans **2025-10-05 00:00 UTC through 2026-10-05 00:00 UTC
exclusive**. Each of BTC, ETH, DOGE, PEPE, SOL, XRP, LINK and ADA has 525,600
minute observations. The macro factors contain only observations or releases
inside that same year. Historical X posts are not included: a current search is
not a timestamped historical sentiment dataset. See the [factor-source guide](../../docs/leading_factor_sources.md)
for archive access and availability requirements.

## Completed example outcomes

All 400 declared simulations completed; **0/5** passed every unchanged hurdle.
These figures are pooled net returns, with the evaluation covering the reused
final quarter rather than the whole training year.

| Hypothesis | Validation | Evaluation | Joint stress |
|---|---:|---:|---:|
| QQQ risk transmission | -8.194% | -0.083% | -0.674% |
| CPI acceleration | -0.387% | +0.056% | -0.059% |
| Funding crowding fade | +0.344% | +0.053% | +0.033% |
| Perpetual premium fade | -0.016% | 0.000% | 0.000% |
| Taker flow drift | -31.072% | -29.633% | -47.792% |

The funding rule traded only PEPE in evaluation: three completed trades, with
seven idle sleeves. Its pooled evaluation profit was $52.84 on $100,000 initial
capital, falling to $33.01 under stress. This is sparse, concentrated evidence
and fails the five-profitable-assets breadth gate. Premium had no evaluation
trades. CPI evaluation had three unique releases and two directional events,
not sixteen independent signals. The full report preserves every other failed
hurdle, activity month, liquidation and parameter neighbor. Cumulative disclosed
results are **0/24** hurdle passes; no strategy is presented as proven non-overfit.
