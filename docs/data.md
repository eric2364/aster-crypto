# Data contracts and reproducibility

Candles are UTC interval-start records. Required CSV/Parquet columns:

| Field | Meaning |
|---|---|
| timestamp | Timezone-aware interval start, e.g. `2024-01-01T00:00:00Z` |
| instrument_id | Exact catalog ID, e.g. `binance:perpetual:BTCUSDT` |
| open/high/low/close | Positive quote price per base unit |
| volume | Nonnegative base units over the interval |
| duration_seconds | Interval length: 60, 300, 900, 3600, 14400, 86400; arbitrary positive lengths allowed |
| mark_open | Optional derivative mark observed at interval open |
| mark_price | Optional derivative mark observed at interval end |
| index_price | Optional index metadata, not liquidation trigger |
| quote_volume/trade_count/open_interest | Optional passthrough metadata |

A close at 00:01 belongs to the interval starting 00:00 for one-minute data. Exchange vendor adapters normalize timestamp milliseconds and base-volume candles. The engine never interprets a ticker as a globally unique instrument. Base/quote, venue, market type, tick/lot, dated fee assumptions and listing intervals belong in the catalog. OKX derivatives vendor contract volume must be converted into base units before using the generic candle adapter; no automatic contract-size conversion is claimed. Adapters are offline normalization/configuration helpers, not historical downloaders or live trading connectors.

Funding is a separate table with `timestamp,instrument_id,funding_rate,mark_price`. Timestamp is exact UTC settlement; rate is signed per-settlement decimal. Settlement marks are mandatory. No funding cadence is invented from current exchange intervals. Supplied settled rates only reach strategy callbacks at their settlement time. Missing historical funding emits a quality warning; partial coverage remains the user's dataset responsibility. Future published/predicted funding and delayed publication need distinct observed-time events before a live-like funding predictor can be studied.

Validation precedes callbacks. Duplicate/overlapping bars, missing required values, invalid OHLC, nonfinite/zero prices, negative volume, naive times, invalid marks, unknown instruments and bars outside listing lifetimes fail. Gaps and >50% close jumps warn. Gaps remain absent; trading orders cannot fill in nonexistent bars. The loader does not infer exchange-maintenance cause from gaps or repair outages. Empty funding is accepted with a warning for held perpetual datasets; duplicate/missing-timestamp funding fails.

Use `data.bars: /absolute/path/bars.parquet` and `data.funding: /absolute/path/funding.parquet` in a config after removing `data.synthetic: true`. Paths currently resolve against the invoking working directory. Maintain historical listing metadata and failed/delisted instruments yourself: the supplied BTC/ETH demonstration cannot establish an unbiased historical universe. No current-top-coins backtest should be presented as survivorship-free.

`save_partitioned` expects catalog-enriched exchange/market_type/symbol columns and partitions into venue / market / symbol / year / month. Arrow avoids repeated CSV parsing. Input is still materialized in memory by the simulator; the partitioned format does not imply streaming simulation. L1 quote, trade tick and L2 snapshot dataclasses are future schema contracts only.

Every exported run saves data and funding SHA256, full source SHA256, strategy identity/version and parameters, software/dependency versions, available git commit, execution/risk/fee settings, seed, interval lengths, period, UTC run timestamp, data-source label and quality report. Git commit may be null in an uncommitted workspace; source hashes still identify the exact implementation. Open positions stay marked at the final observed mark and are exported, so no future/artificial terminal close is invented.

## Implemented Binance ingestion

`examples/download_binance.py` downloads checksum-verified spot or USDT linear-perpetual archives, observes milliseconds versus microseconds, repairs archive omissions only from recorded official daily rows, verifies requested complete candle coverage and saves a source manifest. Perpetual mode separately joins mark open/close and paginates funding history with exact settlement marks. Funding can include a settlement exactly at the terminal valuation boundary; candle bounds remain interval-exclusive. Other venues still use user-supplied normalized files. See [source guide](data_sources.md) and [real demo](real_data_demo.md).
