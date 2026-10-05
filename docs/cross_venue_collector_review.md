# Independent Bybit collector review

The collector is ready for the fixed-year acquisition, subject to the source limits below. This is an offline software audit, not a certificate that the full real year has been downloaded or independently verified. No acquisition, strategy fitting, signal calculation, or economic simulation was performed by this audit. The prospective funding-differential family is not yet preregistered or counted as candidate 26; the research result remains 0/25.

The reviewed collector is `examples/cross_venue/download_bybit.py`; independent regressions are in `tests/test_bybit_collector_audit.py`. The tests construct official-schema raw byte envelopes for all eight native contracts on a three-minute window, rather than using saved market outcomes. HTTP is forbidden in these tests. Initial normalization followed by verify-only reconstruction preserves every byte of every file. A separate 201-settlement history plus the endpoint exercises the 200-row backwards cursor and proves no settlement is skipped or duplicated at that boundary.

## Evidence and corrected pre-acquisition defects

The independent 34-case suite passes. The collector author's 17 cases also pass: 51 focused tests total. Verification covers:

- Exact eight-contract identity, linear USDT settlement, native 1000PEPE quantities and prices, multiplier one, and the current 100-native-unit lot step. No factor of 1,000 is silently applied to volume or price.
- Three actual minute opens, explicit 60-second durations and interval ends, strict complete candle and mark grids, duplicate/conflicting observations, OHLC bounds, finite values, nonnegative volume, and Engine normalization compatibility.
- Real settlement timestamps and signed rates. Interior funding valuation uses that minute's mark **open**, not its future close. A settlement exactly at END uses the final completed minute's mark close, separately labelled; no next-year candle or prior-year warmup is read.
- A full 200-observation funding page advances to the oldest timestamp minus one millisecond, then retains the remaining older observation and the separately requested END settlement.
- Wrong response identity/category, successful HTTP with API error, wrong URL, raw hash corruption, missing raw pages, and non-UTC retrieval labels are rejected offline.
- Forged normalized bars, funding marks, instrument rules, and manifests remain rejected even when their normalized-file hashes are resealed. Verification independently reparses preserved raw bytes and compares the resulting frames and manifests.
- The exact 25 permitted relative output paths are checked before reading seal entries. Collector/model source and Python/NumPy/pandas/PyArrow runtime provenance are checked. Verification neither writes files nor fetches missing data.

Before acquisition, timestamp-grid calculations were made explicit in nanoseconds for pandas' microsecond-resolution indices; missing `duration_seconds`/`end` fields were added; raw normalization gained numeric checks; and the seal's permitted path set was validated before reads. These are collector repairs, not changes to previously tested strategies or the backtest core. The dataset seal records the actual final collector source hash.

Reproduce the focused audit:

```bash
.venv/bin/python -m pytest tests/test_bybit_collector.py tests/test_bybit_collector_audit.py -q
```

After acquisition, the separate production verification command reconstructs every expected page from local raw envelopes:

```bash
.venv/bin/python examples/cross_venue/download_bybit.py --out data_cache/minute-bybit-1y --verify-only
```

It requires the completed dataset seal and its recorded source/runtime, rather than repairing normalized files or retrieving missing pages. This audit does not replace that real-data verification.

## Source limits that remain

Official [trade kline](https://bybit-exchange.github.io/docs/v5/market/kline) and [mark kline](https://bybit-exchange.github.io/docs/v5/market/mark-kline) responses provide minute OHLC values; [funding history](https://bybit-exchange.github.io/docs/v5/market/history-fund-rate) provides settled rates and timestamps. Funding history does not supply historical publication receipts, the next announced rate, a historical interval schedule, or exact settlement tick marks. The collector consequently supplies no factual `available_at` field. Its retrieval timestamp records today's source acquisition, not past predictor availability.

[Instrument information](https://bybit-exchange.github.io/docs/v5/market/instrument) supplies current contract rules. Current lot/tick rules and simulator fee/risk defaults are explicitly approximations for this historical year. Catalog identity validates the native contract, but does not establish that all current limits, fee tiers, or risk tiers applied throughout the year.

An exact candle grid is testable. Funding omissions are not generally identifiable from elapsed times: a missing four-hour payment can create an eight-hour gap that resembles a genuine eight-hour interval. Even the sum of those elapsed intervals can still cover the entire calendar. The collector preserves observations and reports intervals, rejects an entirely empty history, and performs no synthetic interpolation; it cannot certify an unknown historical funding cadence from those observations alone. Later predictor design must distinguish this uncertainty from measured source coverage and explicitly freeze any publication lag, expiry rule, and valuation-proxy sensitivity before fitting.

Interior minute-open and END completed-close settlement values are disclosed approximations, not exact exchange funding marks. The available-first funding policy and independent wallet execution limitations remain in [the execution feasibility review](cross_venue_execution_feasibility.md); source coverage limitations remain in [the data feasibility review](cross_venue_data_feasibility.md). No profitable-result or non-overfitting claim follows from these software tests.
