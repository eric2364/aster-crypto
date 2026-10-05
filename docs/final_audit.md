# Final independent adversarial audit

Audit date: 6 October 2026. The fresh auditor did not author or modify the core
simulator. The review assumed subtle errors capable of creating false profits.
It covered `aster/backtest/*.py`, data normalization, strategy examples,
vectorized screening, walk-forward optimization, and the execution/accounting
specifications. Reproduction and regression cases are in
`tests/test_fresh_audit.py`; prior independent execution findings remain recorded
in `docs/audit.md`.

## Fresh confirmed findings

| Severity | Failure | Hand-derived reproduction | Correction and verification |
| --- | --- | --- | --- |
| High | A standalone funding settlement checked liquidation against a stale mark before applying funding | Long1 at100 with isolated collateral10; settlement mark90 yields local equity0 below maintenance0.45. Negative rate2% credits1.8, allowing an already insolvent position to survive if the new mark is applied only during settlement | Batch contemporaneous settlement marks, check risk, settle all surviving positions' simultaneous payments, then check risk again. Regression requires liquidation at the settlement timestamp and zero funding receipt |
| Medium | Holdout candles could close beyond a walk-forward fold's declared end | Test window day2–day3 includes a day2 candle lasting two days; the original run consumed its day4 close and could overlap another fold | Filter both training and test candles by their complete interval boundaries. Regression retains a valid second-instrument test candle, so the check cannot succeed merely because no fold runs |
| Medium | Missing funding timestamps passed normalization and were silently omitted by the engine's horizon filter | An aware funding table containing one valid timestamp and one `NaT` normalized successfully; comparisons against the run horizon dropped the unknown settlement, potentially suppressing funding costs | Require nonmissing funding fields before replay; regression requires rejection of mixed valid/unknown settlement timestamps |

## Verification scope

Fresh cases verify UTC conversion and naive-time rejection; duplicate candles;
overlapping intervals; missing prices; nonpositive prices; negative volume;
reported gaps without synthetic bars; extreme-price-jump warnings; zero-volume
capacity; listing/delisting boundaries; duplicate and unknown funding identities;
funding risk ordering; and walk-forward interval containment.

A future-price perturbation leaves the moving-average signals and lagged
screening returns unchanged before the perturbation. Changing holdout prices
does not change the first fold's parameter selection or training metrics.
Strategies receive completed history; opening capacity derives from completed
prior volume. Existing independent suites cover next-open timing, latency,
maker/taker classification, post-only, IOC/FOK, stop ambiguity, shared capacity,
reduce-only, fee/slippage conservation, shorts, leverage, funding signs,
liquidation deficits, explicit mark prices, and venue wallet separation.

## Residual limits

This is a deterministic candle research simulator. It cannot establish actual
queue position, execution depth, intrabar mark liquidation, or microsecond
ordering. Open/close and explicit mark observations drive risk; high/low trade
extrema do not reconstruct an intrabar mark path. Constant instrument fees,
maintenance rates and leverage are configurable assumptions, rather than
historical venue rule reconstruction. Funding coverage is warned about but not
proven complete by a missing-interval schedule, because historical intervals
can change.

The opening-volume proxy can exceed the eventual next candle's observed volume;
using that later observation retroactively would violate causality. Resting
orders match only under the documented candle model. Cancellation takes effect
immediately, and unfilled GTC market quantities retry future opens. Publication
latency is not separately observed. These limitations require cost/liquidity
stress testing and cannot support HFT or exact exchange-replication claims.

Walk-forward folds restart with independent balances and strategy state. The
helper reports individual folds, not an automatically investable continuous
portfolio or a compounded holdout curve. The screening-return function is a
diagnostic close-to-close approximation; final claims must use event-engine
accounting. User-provided strategies and historical data remain trusted inputs;
the framework cannot prove that an arbitrary supplied signal was computed
causally or that a historical universe is free of survivorship bias.

## Verification record

All three fresh confirmed findings were corrected by the core author and
independently retested. The full repository suite passed **77 tests** in
0.94 seconds; the fresh audit module contributes **16 passing cases**.
The earlier audit's six confirmed execution/accounting defects also remain
covered by passing regressions. No known unresolved high/medium defect from
these reviews remains. This is bounded regression evidence, not a guarantee
that all defects or exchange-specific differences have been eliminated.

Run the fresh cases with:

```bash
.venv/bin/python -m pytest tests/test_fresh_audit.py -q
```

Run the complete suite with:

```bash
.venv/bin/python -m pytest -q
```

## Official Binance ingestion follow-up

The trailing-year real-data extension was independently reviewed in
`aster/data/binance_public.py`. Seventeen offline regression cases in
`tests/test_binance_public.py` use in-memory ZIP/CSV archives and mocked network
responses. Automated tests never download market data.

The review found one medium defect: daily fallback for an unavailable monthly
archive omitted the final calendar day whenever the requested end was intraday.
For an hourly January1 noon–January2 noon request, only January1 was downloaded,
yielding 12 rather than 24 bars. Existing full-coverage validation rejected the
result safely; the defect prevented legitimate aligned requests from completing.
The core author corrected the calendar-day enumeration; the regression now
verifies 24 complete bars and both required daily requests. The final partial
calendar day is enumerated before filtering individual candles to the requested
complete-interval bounds.

The cases also verify per-row spot microsecond/futures millisecond timestamp
normalization; optional header preservation of the first data row; SHA256
mismatch rejection before ingestion; cache corruption detection; duplicate and
missing candle rejection; funding cursor advancement by one millisecond;
repeated-page rejection; duplicate settlement rejection through normalization;
and missing/nonpositive/nonfinite settlement mark rejection. The funding rate
is retained as a per-settlement decimal, without a leverage or interval factor.

The added official daily repair path is independently tested: existing monthly
observations remain authoritative, daily overlap is filtered out, and only
missing recorded timestamps are added. Conflicting values on already-present
timestamps cannot silently replace monthly observations. Residual gaps and
duplicate copies of a missing observation still fail exact coverage validation.
Repair sources are recorded in the provenance manifest, and no interpolation
or synthetic tradable candle is created.

The independent integrated rerun after the ingestion correction and repair
tests passed **100 tests in 1.04 seconds**. The ingestion audit has no known
unresolved high/medium finding. This verification concerns code and mocked
formats; the root task separately records actual download and checksum results.

Archive integrity and complete candle coverage do not establish complete funding
history. The public API's returned funding events are recorded, and historical
cadence is reported for inspection rather than replaced with synthetic zeros.
Downloaded candle intervals use `[start,end)`; the existing accounting engine
includes funding settlements at the terminal valuation boundary `end`.
