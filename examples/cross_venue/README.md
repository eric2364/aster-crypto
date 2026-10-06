# Cross-venue funding experiment and Bybit collector

The collector passed independent preparation review before acquisition. See the [51-case source audit](../../docs/cross_venue_collector_review.md). This collector performs no orders, fitting or profitability calculations. It adds a separate directory and never changes existing Binance data or earlier research sources.

From the repository root:

```sh
.venv/bin/python examples/cross_venue/download_bybit.py --workers 2 --out data_cache/minute-bybit-1y
.venv/bin/python examples/cross_venue/download_bybit.py --verify-only --out data_cache/minute-bybit-1y
```

The second command makes no network requests or writes. It checks the completed dataset seal, reopens and validates every raw page, reconstructs every normalized value and catalog entry, and compares the normalized data exactly. A completed cache automatically follows this verification path on a subsequent ordinary invocation. An incomplete download resumes only committed, validated raw-page envelopes; incomplete `.partial` files do not count as source pages. A missing/corrupt committed page fails rather than silently reacquiring it during verification.

Only BTC, ETH, DOGE, PEPE, SOL, XRP, LINK and ADA USDT linear perpetuals are collected for **[2025-10-05 00:00 UTC, 2026-10-05 00:00 UTC)**. PEPE uses native `1000PEPEUSDT` on Bybit, with no price, volume or quantity rescaling. Normalized instrument IDs are `bybit:perpetual:<native-symbol>`; folder labels retain the research spot names, including `PEPEUSDT`.

Public sources, with exact requested URLs retained per response:

- [Trade candles](https://bybit-exchange.github.io/docs/v5/market/kline): `/v5/market/kline`, category linear, interval 1, closed bounded 1,000-minute windows.
- [Independent observed mark candles](https://bybit-exchange.github.io/docs/v5/market/mark-kline): `/v5/market/mark-price-kline`, same exact minute windows.
- [Actual settled funding](https://bybit-exchange.github.io/docs/v5/market/history-fund-rate): `/v5/market/funding/history`, a bounded whole-year scan backwards in at most 200-settlement pages. No eight-hour schedule is imposed.
- [Current native rules](https://bybit-exchange.github.io/docs/v5/market/instrument): `/v5/market/instruments-info`, one native symbol per response. These are explicitly current approximations to historical trading rules; simulator fee/risk defaults are assumptions, not authenticated account tiers.

Each raw response is stored in one atomically replaced JSON envelope containing base64 original bytes, SHA256, exact URL and UTC retrieval time. Normalized manifests additionally hash the envelope and retain its raw hash and byte count. The final dataset seal records the collector and instrument-model source SHA256 and Python/NumPy/pandas/PyArrow runtime versions (data provenance, not strategy preregistration), and hashes all eight bar files, eight funding files, eight source manifests and the catalog. REST responses have no publisher archive checksum; SHA proves preservation, not permanent publisher immutability.

Each `SYMBOL/bars.parquet` has exactly 525,600 minute rows: `timestamp`, `end`, `duration_seconds=60`, `instrument_id`, trade `open/high/low/close/volume/turnover`, and observed `mark_open/mark_high/mark_low/mark_price` (last field is minute mark-close). Volume is native base units and turnover USDT; mark prices are not executable fills. Missing/extraneous minutes, duplicate timestamps, API errors, wrong identities, nonfinite values and corrupt OHLC are rejected. No interpolation or pre-year warmup is permitted.

Each `SYMBOL/funding.parquet` contains `timestamp`, `instrument_id`, `funding_rate`, `mark_price`, `mark_price_source`, `boundary`. Actual rates/timestamps are source facts. Bybit does not provide settlement mark in this response: `mark_price` is explicitly a **settlement-minute mark-open proxy**. The collector separately requests an actual event exactly at END; if present, it is included with `boundary=true` and **END_last_completed_mark_close_proxy**, never an outside-year mark. If absent, no END event is invented. Published rate history does not establish historical delivery/receipt time or the next announced rate: no assumed predictor `available_at` is written as a fact.

Funding interval diagnostics report actual consecutive elapsed times, without interpreting differences as proven missing events or reconstructing schedules. Full history gaps require independent corroboration before a strategy claims complete settlement accounting. No quotes, historical BBO, maker queues, exact settlement tick marks or historical dynamic risk tiers are reconstructed.

Baseline acquisition is about 8,416 candle requests plus eight metadata requests. If actual funding is eight-hourly, approximately 48 history-page requests plus eight END-point requests are needed; hourly settlement would require approximately 352 plus eight. Actual cadence determines the count; no schedule is imposed. The candle total is 8,409,600 rows. Progress per instrument/stream is printed every 50 candle pages and every ten funding pages, with flushed output. At most two symbol jobs are retained at a time. Two workers share a global gate spaced at least 0.11 seconds apart (below ten requests/second), 30-second HTTP timeouts and bounded exponential retries. Endpoint first/last samples are not full-year coverage evidence; the exact grid checks occur only after a completed collection. The completed local corpus occupies about 934 MiB, including raw envelopes and normalized files; filesystem allocation can differ.

Synthetic checks:

```sh
.venv/bin/python -m pytest tests/test_bybit_collector.py tests/test_bybit_collector_audit.py -q
```


## Source review and reproduction

The completed year contains 525,600 trade and 525,600 mark rows for each asset,
8,480 cached responses and 1,096 sourced funding events per asset, including one
actual event exactly at END. The [independent dataset audit](../../docs/cross_venue_data_audit.md)
reconstructs the raw source without importing the collector. Verify it with:

```sh
.venv/bin/python audit/verify_bybit_dataset.py --root data_cache/minute-bybit-1y --out audit/bybit_dataset_evidence.json
```

The [fixed prospective packet](proposed_protocol.md) defines one additional
family: equal native quantities long on one venue and short on the other,
admitted by previous realized funding intensity after conservative roundtrip
costs. It uses two independent 50,000-USDT wallets and all eight pairs, including
DOGE and native 1000PEPE. This is slow carry evaluated with minute execution;
it does not establish a minute scalping edge. See the independent reviews of
[signals](../../docs/cross_venue_signal_review.md),
[execution](../../docs/cross_venue_execution_review.md) and
[assembled runner](../../docs/cross_venue_preregistration_review.md).
The reused year has already supported 25 unsuccessful candidates.

Install the pinned research environment as described in the root README. From
an empty result directory, source reconstruction precedes any features or outcomes:

```sh
.venv/bin/python examples/cross_venue/run.py --freeze-only --out results/cross-venue-funding-1y-v1
```

Retain the reviewed source commit and publish the generated source/input/runtime
lock and verification receipt to the private repository before execution:

```sh
.venv/bin/python examples/cross_venue/run.py --execute --out results/cross-venue-funding-1y-v1
```

The runner permits exactly seven sequential joint simulations: three validation
months, primary evaluation baseline/stress, and alternative funding-mark
evaluation baseline/stress. It preserves all 25 outputs per phase and rejects
source/input/runtime drift or altered cached outputs. A partial run is preserved
for explicit diagnosis; do not erase it or run a neighboring parameter grid.
Its numerical summary remains **unpublished** until separate independent
financial, causal-feature and gate reconstruction succeeds. No strategy from
this packet has yet been certified as a historical hurdle pass.


## Completed historical result and audit scope

All seven actual runs stayed in cash, with zero orders, fills, funding cashflows,
positions and returns. Thirteen of fifteen declared hurdles fail. A separate
entry proof checked all 78,720 pair decisions: none met the fixed cost filter.
The best forecast/cost ratio was 0.253, below the required 1.5. The full financial
audit checked 661,627 snapshots and all 175 execution outputs; the causal audit
checked all 16 feature streams. [Audited report](../../docs/cross_venue_results/report.html).
This adds one failed family; the cumulative result is **0/26**.

Audits and guarded publication for the preserved original cache:

```sh
.venv/bin/python audit/verify_cross_venue_features.py --certificate audit/cross_venue_feature_evidence.json
.venv/bin/python audit/verify_cross_venue_outputs.py --certificate audit/cross_venue_output_evidence.json
.venv/bin/python audit/verify_cross_venue_no_admission.py --feature-audit audit/cross_venue_feature_evidence.json --certificate audit/cross_venue_no_admission_evidence.json
.venv/bin/python examples/cross_venue/publish.py --financial-audit audit/cross_venue_output_evidence.json --feature-audit audit/cross_venue_feature_evidence.json --no-admission-audit audit/cross_venue_no_admission_evidence.json --destination docs/cross_venue_results-reproduction
```

The no-admission proof is specific to this zero-activity cohort. The financial
verifier reconstructs recorded executable fills and account trajectories; it
does not prove generic policy decisions or detect every omitted eligible fill.
A future trading cohort needs a corresponding independent intent/execution
completeness audit. Do not reuse the inactive certificate to publish a winner.

The verifiers require the original pre-outcome source/input/runtime lock at
`1820b82`, including recorded input paths. Reacquired REST responses or moved
paths can have different hashes: a relocated/new replication requires an
explicit mapping/new provenance receipt, not edits to the original frozen lock.
Runtime measurements for these real simulations were approximately 19.5–20.3
seconds per month and 61.3–62.5 seconds per quarter for `Engine.run`; these exclude
feature generation, source hashing and export. Sequential process peak RSS was
about 8,193 MiB. These are measured inactive-path workloads, not throughput
benchmarks for active orders or high-frequency execution.
