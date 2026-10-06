# Historical crypto data sources

Checked 6 October 2026. Use exchange-specific prices for executable research.
BTC/USDT spot, BTC/USDT perpetual and a consolidated BTC/USD index are different
instruments. A downloader's successful HTTP response is not proof of complete
history. This guide describes sources; only the repository's documented download
commands are implemented integrations.

## Choosing the dataset

| Research | Minimum data | Suggested starting source |
| --- | --- | --- |
| Spot daily/hourly/minute signals | Venue spot OHLCV plus instrument rules, fees and listing history | Binance public archives; native Bybit/OKX candles for those venues |
| Leveraged linear perpetual strategies | Same-venue perpetual trade candles, independent mark observations, exact realized funding settlements, instrument specifications | Binance USD-M archives/API; Bybit linear candles + mark + funding API |
| Funding arbitrage | Both venue instruments, funding settlement marks/timestamps, rates, balances and asynchronous execution prices | Native settlement histories where coverage exists; vendor archive for missing periods |
| Basis/cash-and-carry | Matched spot and derivative series; dated futures expiry/specifications or perpetual funding | Native spot/futures histories, with legs kept distinct |
| Maker/HFT/order-book research | Sequenced trades, bid/ask, snapshots and L2 updates, receipt timestamps and outage metadata | Historical venue exports or a specialist tick-data vendor |

These are dataset recommendations, not a claim that the MVP can execute L2 replay.
Do not convert a spot candle dataset into a perpetual dataset by changing a
market-type label. Never invent missing funding, marks, executable bid/ask or
exact historical prices.

## Binance: free public archives first

[Binance Data Vision](https://data.binance.vision/) and the
[official public-data repository](https://github.com/binance/binance-public-data)
provide daily/monthly spot and futures files. Spot includes candles, trades and
aggregate trades. The repository describes formats and adjacent SHA256 checksum
files; archives can be corrected later, so retain original downloads and hashes.
Spot archive timestamps switch from milliseconds to microseconds from
**1 January 2025**. Interpret timestamp units from source/date, validate them,
and never apply a single millisecond parser across both eras.

For a fixed one-year spot sample, use the twelve completed months
**October 2025–September 2026**, subject to complete download verification. The
official BTCUSDT 1h September 2026 archive, plus January/December 2025 and August
2026, returned HTTP200 in an independent HEAD check. This verifies URL existence,
not row counts, integrity or gaplessness.
[September archive](https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-2026-09.zip).

Example archive path:

```text
https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-2026-09.zip
```

For recent tails or targeted windows, `/api/v3/klines` has a maximum 1000 rows
per request and request weight 2. Set UTC bar boundaries explicitly; `startTime`
and `endTime` are UTC even when a candle timezone is selected. Page by the last
observed start plus interval; remove duplicate boundary rows and exclude the
current incomplete candle. Use current documented weight limits and server
responses, rather than a universal requests-per-second assumption.
[Binance spot market API](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints).
The public market-data base URL and microsecond response header are documented
separately in the
[official REST reference](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md).
Archive microsecond rules do not mean every REST response uses microseconds.

For perpetual funding, `/fapi/v1/fundingRate` supplies settlement time, rate and
associated mark; maximum 1000 records, ascending pagination and inclusive bounds.
Its rate budget is shared with funding-info at 500 requests / 5 minutes / IP. Store
each actual settlement; do not impose 8-hour intervals across all instruments.
Acquire separate mark-price candles for margin valuation throughout the run,
not just funding-time marks.
[Binance futures market API](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History).

## Bybit: category must be explicit

The free `/v5/market/kline` API supports spot, linear and inverse categories,
with maximum 1000 records and reverse start-time ordering. Its default category
is linear: request `category=spot` explicitly for spot research. Candle start is
milliseconds. USDT/USDC contract volume is base coin; inverse volume is quote
coin. A live candle's close is provisional. Sort, deduplicate and exclude
unfinished intervals after pagination.
[Bybit candles](https://bybit-exchange.github.io/docs/v5/market/kline).

Fetch independent marks through `/v5/market/mark-price-kline` and preserve their
own timeline, including open and close observations.
[Bybit mark candles](https://bybit-exchange.github.io/docs/v5/market/mark-kline).
Funding history uses `/v5/market/funding/history`, maximum 200 rows. Supplying
start time alone is an error; end-time pagination is supported. Instrument
metadata supplies the funding interval, which varies by symbol. Test actual
earliest/latest returned settlements; this guide does not assert unlimited
retention.
[Bybit funding](https://bybit-exchange.github.io/docs/v5/market/history-fund-rate).

The official
[historical download portal](https://www.bybit.com/en/derivative-activity/history-data)
is an alternative entry point for venue historical files. It is dynamic and
was not sufficiently exposed by the text retrieval tool to verify every file
type, depth or earliest date. Inspect actual instrument/date coverage before
committing to an order-book study; do not infer a universal depth from older
third-party downloader examples.

Bybit's documented default IP ceiling is 600 requests / 5 seconds; endpoint/account
limits and response headers also matter. Use a conservative throttle and honor
429/403 and rate-limit responses; do not operate at the ceiling.
[Bybit rate limits](https://bybit-exchange.github.io/docs/v5/rate-limit).

## OKX: distinguish candle retention from funding retention

`/api/v5/market/history-candles` covers recent years; 1-second bars are limited to
three months. Request limit/pagination and rate budget 20 requests / 2 seconds / IP
must be respected. `after` requests older records. `confirm=1` identifies closed
bars; timestamps are milliseconds. Daily bars offer UTC+8 and UTC variants:
choose the intended boundary.

Derivative `vol` is contracts, while spot `vol` is base units. Normalize contract
volume using specifications; retain `volCcy`/`volCcyQuote` for unit validation.
`/api/v5/market/history-mark-price-candles` supplies independent marks.

`/api/v5/public/funding-rate-history` retains up to three months, maximum 400
records, 10 requests / 2 seconds / IP+instrument. Use `realizedRate` for actual funding;
the documented `fundingRate` field is predicted. Public trade history also has
three-month retention. Longer candle coverage does not imply longer funding or
tick coverage. A multiyear perpetual study therefore needs another verified
archive for missing streams, or a shorter common window.
[OKX official API documentation](https://app.okx.com/docs-v5/en/).

## Paid tick/L2 archives and aggregated alternatives

[Tardis](https://docs.tardis.dev/) provides historical trades, book data,
derivative data and exchange-specific replay APIs. Availability depends on
exchange, instrument, dates, channel and purchased access. Verify coverage and
terms before purchasing; this guide quotes no price.
[Historical collection details](https://docs.tardis.dev/historical-data-details)
describe snapshots and reconnect gaps. A reconstructable book needs the correct
initial snapshot plus all subsequent deltas, not an arbitrary start in the
middle of a file. Receive times, feed sequence consistency and collection
incidents remain relevant even with paid data. Record source channel/depth
changes; market-by-price L2 does not disclose true FIFO queue position.

[Coin Metrics market candles](https://docs.coinmetrics.io/api/v4/)
are trade-derived for named markets, with catalogue-dependent community or
licensed access and `next_page_url` pagination. Its candles omit intervals with
no trades. Preserve that distinction when considering gap-filled zero-volume
bars: Aster does not synthesize tradable candles. Market-specific candles can
support research; consolidated/index/asset prices are benchmark data and must
not silently replace venue-specific executable prices, marks or funding.

## Acceptance checks before a backtest

1. Pin source URL, retrieval time, market/category, symbol identity, interval,
   timezone, units, raw hash and any vendor revision/checksum.
2. Confirm requested and actual first/last complete interval, expected row count,
   missing intervals, duplicate pagination rows and source outages. Reject
   timezone/unit mismatches and impossible OHLC; do not quietly interpolate.
3. Check listing and delisting periods. Current exchange symbol lists omit
   historical failures and delistings. A single BTC example makes no claim of
   unbiased whole-universe coverage; maintain a dated listing catalogue for
   multiasset research.
4. Keep settlement funding separate from signal-time forecasts. Join marks
   without using future observations; record missing coverage explicitly.
5. Convert volume and order quantity into compatible units. Contract count,
   base volume and quote turnover are not interchangeable capacity measures.
6. Preserve raw downloads, normalize once to partitioned Parquet, and save the
   quality report and run manifest. Separate missing data from zero activity.

The execution limitations in `execution_model.md` still apply after data quality
passes. Higher-resolution data enables a future matching model; it does not
automatically make an OHLC backtest an HFT execution simulator.


## Bounded second-venue verification

The [cross-venue feasibility review](cross_venue_data_feasibility.md) preserves
56 small public Bybit responses for the same eight perpetual assets, including
native 1000PEPE. Trade and mark minute candles and actual funding histories
were available at both ends of the fixed year. These boundary probes do not
verify full-year completeness. The review describes request volume, native
quantity grids, exact settlement-mark limitations and historical-quote gaps.
It is a source assessment, not another completed backtest or winning strategy.

The additive [Bybit collector](../examples/cross_venue/README.md) now preserves
raw response bytes and reconstructs all normalized fields offline. Its
[independent source audit](cross_venue_collector_review.md) passed 51 synthetic
cases. The full year has since been acquired: each of eight assets has
525,600 trade and mark minutes, with 8,480 cached responses across the corpus.
A separate [full-source reconstruction audit](cross_venue_data_audit.md) verifies
every normalized value independently. Funding has 1,096 actual events per asset,
including an event at END valued with the last within-year mark close. These
checks establish consistency with the returned source, not historical receipt
times, exact settlement marks, historical fee tiers or an unbiased survivor universe.
