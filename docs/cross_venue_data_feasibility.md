# Cross-venue data feasibility: bounded evidence, 6 October 2026

A **new slow Binance–Bybit perpetual funding-differential study is data-feasible in principle**, conditional on complete collection and validation. It would trade the same underlying in opposite directions on two venues and receive/pay their actual settlements. This differs economically from spot/perpetual carry and directional predictors. The evidence does **not** establish an executable high-frequency spread edge, complete yearly coverage, or profitability. No strategy was fitted or run; existing frozen sources, datasets and results were unchanged.

The only historical window considered is **2025-10-05 00:00 UTC inclusive to 2026-10-05 00:00 UTC exclusive** (525,600 minutes). Metadata fetched now is explicitly a current-rule approximation, not historical exchange-rule evidence.

## Verified second-venue availability

The public, unauthenticated Bybit REST endpoints accepted **56 bounded requests, 24,710 response bytes**: eight current instrument specifications and, for each of eight contracts, first/last three minute trade candles, first/last three minute mark candles, and first/last day funding histories. Every response had HTTP 200 and `retCode=0`; every requested historical slice returned three observations. The minute slices were exactly **2025-10-05 00:00–00:02 UTC** and **2026-10-04 23:57–23:59 UTC**. Funding slices returned actual settlements at 00:00, 08:00 and 16:00 on those two days. This proves boundary availability only; no interior yearly grid or settlement completeness claim follows.

| Stream | Official endpoint, `category=linear` | Meaning and limitations |
|---|---|---|
| Trade OHLCV | `/v5/market/kline`, `interval=1`, explicit `start/end` | Venue trade prices, base-coin volume and USDT turnover; up to 1,000 rows/page, reverse chronological output. Closed minute data becomes usable only after the minute completes. |
| Mark OHLC | `/v5/market/mark-price-kline`, `interval=1` | Published venue mark observations, up to 1,000/page; no trade volume and no executable price guarantee. |
| Settled funding | `/v5/market/funding/history`, explicit `startTime/endTime` | Actual rate and settlement timestamp, up to 200/page. The response has no historical receipt time, next announced rate, or settlement mark. |
| Current contract rules | `/v5/market/instruments-info` | Native identity, tick/quantity/minimum rules and current funding interval; does not reconstruct historical rules or schedules. |

Primary documentation: [trade candles](https://bybit-exchange.github.io/docs/v5/market/kline), [mark candles](https://bybit-exchange.github.io/docs/v5/market/mark-kline), [funding history](https://bybit-exchange.github.io/docs/v5/market/history-fund-rate), [instrument specifications](https://bybit-exchange.github.io/docs/v5/market/instrument). The canonical request host is `https://api.bybit.com`.

All eight currently report `LinearPerpetual`, `Trading`, USDT quote/settlement and funding interval 480 minutes. Use distinct IDs `bybit:perpetual:<native-symbol>` and `binance:perpetual:<native-symbol>`, even where symbol strings match. The following common quantity grid is the least common admissible step from observed current Bybit rules and the existing explicitly current Binance catalog. Minimum notional, minimum quantity and market-order maxima remain separate checks.

| Research asset | Both native symbols | Binance step | Bybit step | Common step, native quantity |
|---|---|---:|---:|---:|
| BTC | BTCUSDT | 0.001 | 0.001 | 0.001 |
| ETH | ETHUSDT | 0.001 | 0.01 | 0.01 |
| DOGE | DOGEUSDT | 1 | 1 | 1 |
| PEPE | 1000PEPEUSDT | 1 | 100 | 100 |
| SOL | SOLUSDT | 0.01 | 0.1 | 0.1 |
| XRP | XRPUSDT | 0.1 | 0.1 | 0.1 |
| LINK | LINKUSDT | 0.01 | 0.1 | 0.1 |
| ADA | ADAUSDT | 1 | 1 | 1 |

There is **no missing PEPE product mapping** in the probes: both venues expose base coin `1000PEPE`. Native quantity one represents a bundle of 1,000 spot PEPE; the common step 100 represents 100,000 spot PEPE. Both contract prices remain per bundle. Do not rescale either derivative price or quantity a second time. This is not a spot-PEPE order-size grid.

## Actual settlements versus predictions

Funding history is settlement evidence, not a point-in-time forecast of the upcoming rate. A predictor could use only previously settled observations, with a prospective explicit publication lag such as settlement plus one minute; that lag is a modeling assumption because historical receipt timestamps are absent. Cash settlement remains at the actual settlement timestamp, independently of predictor availability. Future settlement values, future timestamps and today's interval must not leak into earlier decisions.

Read the actual chronological settlement stream separately per venue. Normalize already observed rates by their actual elapsed intervals where the protocol requires a rate per unit time; equal-weight averages of differently timed settlement rates are not comparable. Current eight-hour metadata and two sampled days do not establish an eight-hour schedule throughout the year. History alone also cannot distinguish an interior missing record from a genuine schedule change: ambiguous gaps require corroboration or explicit missing-data handling, never interpolation. A future scheduled interval change was not historically observed by these probes.

Bybit history does not supply settlement mark. Joining the observed minute mark **open** at an exactly aligned settlement is a declared approximation to the exchange's settlement valuation, not an exact tick mark. If exact settlement valuation is required, acquire an authentic settlement mark stream first. Published venue marks can share external index constituents, so separate publishers do not imply statistically independent index inputs. They must remain separate observed marks, not synthetic copies of Binance marks.

## Historical quotes: concrete limits of this probe

Binance Data Vision's canonical bucket was discovered from its own [archive page](https://data.binance.vision/). **Sixteen bounded listings** (eight native contracts, daily and monthly `data/futures/um/.../bookTicker/` prefixes, marker at October 2025, maximum two keys) all returned HTTP 200, no keys and `IsTruncated=false`. Thus those canonical bookTicker folders contain no files at or after the start-month marker in this window. This is an observed archive limitation, not a claim that no Binance historical quote product exists anywhere.

A listing-discovered **BTC bookDepth 2025-10-05** archive was downloaded once (466,766 bytes) and verified against its official CHECKSUM. Its CSV schema is `timestamp,percentage,depth,notional`: aggregated depth at percentage buckets, **not best bid/ask prices or individual L2 price levels**. Do not infer BBO or executable spread from `notional/depth`. Source/checksum URLs and hashes are in the evidence packet. [Binance's official archive repository](https://github.com/binance/binance-public-data) explains its checksum convention.

Bybit's [official developer page](https://www.bybit.com/future-activity/developer) advertises historical order-book data, and its [recent-trade documentation](https://bybit-exchange.github.io/docs/v5/market/recent-trade) links the [historical-data portal](https://www.bybit.com/en/derivative-activity/history-data). The portal returned a JavaScript catalog stub through the web reader and HTTP 403 through the direct HTTP probe. Its free access, exact product/schema and eight-asset year coverage therefore remain **unverified**, not absent. The [public root](https://public.bybit.com/) lists trade and other archive directories; the existing August LINK/SOL trade corroboration is evidence for those samples only. No further daily trade corpus was downloaded. The [REST order-book endpoint](https://bybit-exchange.github.io/docs/v5/market/orderbook) is a current snapshot with no historical start/end parameters; it cannot backfill this year.

Contemporaneous spread arbitrage needs synchronized historical bid/ask prices, sizes and freshness on both venues, with executable side/latency modeling. Minute trade candles, independent marks and aggregate depth cannot establish that edge. Quotes alone would also not justify maker queue fills.

## Acquisition size and practical next test

A complete additional Bybit trade-plus-mark year requires **8,409,600 minute rows** (525,600 × eight × two) and approximately **8,416 maximum-size candle requests** (526 pages × eight × two), before retries or overlap checks. Stable eight-hour funding would produce 8,760 total observations and approximately 48 full pagination requests; an hourly cadence would instead produce 70,080 observations and approximately 352 requests. These are planning scenarios, not measured historical cadence. Metadata adds eight requests. Full raw bytes and trade-archive sizes are not measured by these tiny boundary samples; do not estimate disk needs by treating them as representative days.

A collector should save original response bytes, exact URLs, retrieval times, response SHA256, decoded identities and a normalized stream seal. REST data has no archive CHECKSUM, so a hash proves local preservation, not publisher immutability. Paginate backwards using the oldest returned timestamp; enforce bounds, deduplicate identical overlap, reject conflicting duplicates, validate the exact minute grids and report ambiguous funding gaps. Persist missing observations rather than manufacture them. Two bounded workers with conservative pacing and retry/backoff are sufficient; Bybit currently documents a 600-request/5-second IP ceiling and advises against approaching it. [Rate-limit rules](https://bybit-exchange.github.io/docs/v5/rate-limit).

The credible next prospect is **slow cross-venue funding differential with explicit market-bar execution assumptions**. First collect and seal the second venue, then freeze one new protocol before any outcomes. Require separate pre-funded venue wallets and locked total starting capital; no free cross-venue transfer or pooled margin rescue. Both entry legs and both exits pay fixed prospective venue costs, use their own prior volume and can fail independently. Central timeout/cancel/flatten handling, common native quantity grids, venue-local funding/marks/liquidation, residual exposure and exit reserves remain mandatory. New adapters/coordinator/accounting tests are required even if the public Engine already supports multiple exchange wallets; [the companion execution review](cross_venue_execution_feasibility.md) owns that assessment. No quote-driven or exact live-execution claim follows from a candle backtest, and this reused year remains exploratory after prior families were seen.

## Evidence and reproduction

[Bybit bounded manifest](cross_venue_source_evidence/bybit_probe_manifest.json) records all 56 URLs, UTC retrieval times, hashes, row counts and boundary timestamps. [Binance bounded manifest](cross_venue_source_evidence/binance_quote_probe_manifest.json) records the 16 listings and the discovered depth sample/checksum. [Tiny original responses](cross_venue_source_evidence/bounded_raw_responses.json) retain JSON/XML/checksum text for offline hash verification; the compressed depth file remains only in ignored `data_cache/cross-venue-feasibility/probes/`. All 75 recorded cached response hashes were checked before writing this packet. The depth ZIP is excluded from versioned evidence.

For a small repeat probe, request the exact manifest URLs without credentials. Offline, load the raw-response mapping and compare `sha256(text.encode()).hexdigest()` with each manifest record except `bookDepth_sample`; retrieve that single archive only if checking its publisher CHECKSUM. Dynamic REST retrieval timestamps mean a fresh complete response hash can change even when its historical observations are identical. Repeating these bounded probes still does not validate a full-year grid. This feasibility review performed no complete collection or numerical strategy trial.
