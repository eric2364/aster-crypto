# External leading-factor data: availability and provenance

Checked 6 October 2026. Research window is exactly
`2025-10-05T00:00:00Z <= time < 2026-10-05T00:00:00Z`.
External observations can be predictors of spot behavior; they are not spot
account cash flows. A plausible economic story does not demonstrate predictive
power. Selection after examining the earlier holdout must be labelled a new
exploratory research round, not a newly untouched holdout.

## Collected: realized perpetual funding

The official Binance USD-M `/fapi/v1/fundingRate` history reports realized rate,
fundingTime and associated source mark. Historical funding is available to the
model only at that observation's settlement timestamp; it is not a forecast of
the next funding event.
[Official funding API](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History).

Eight files under `data_cache/minute-1y/funding/<SPOT_SYMBOL>.parquet` contain
**1,095 observations each, 8,760 total**. Original settlement timestamps retain
their milliseconds; intervals are nominally eight hours in this acquired
sample. No cadence was synthesized. Independent checks verified chronological
unique timestamps, finite rates, positive marks, bounds, and raw/Parquet hashes.
Per-file manifests list API URLs, raw response files and SHA256 hashes.

| Spot identity | Funding source identity |
| --- | --- |
| binance:spot:BTCUSDT | binance:perpetual:BTCUSDT |
| binance:spot:ETHUSDT | binance:perpetual:ETHUSDT |
| binance:spot:DOGEUSDT | binance:perpetual:DOGEUSDT |
| binance:spot:PEPEUSDT | binance:perpetual:1000PEPEUSDT |
| binance:spot:SOLUSDT | binance:perpetual:SOLUSDT |
| binance:spot:XRPUSDT | binance:perpetual:XRPUSDT |
| binance:spot:LINKUSDT | binance:perpetual:LINKUSDT |
| binance:spot:ADAUSDT | binance:perpetual:ADAUSDT |

Rate is dimensionless. The 1000PEPE source mark is a price for 1,000 PEPE,
and remains a distinct source field. Never copy it into a PEPE spot mark without
unit conversion. `spot_instrument_id` and `source_instrument_id` are explicit;
the inherited `instrument_id` column still identifies the derivative source.

Join with a backward as-of operation on `available_at` and the spot bar's
availability time, not its start. Carry forward only an already observed rate;
before the first observation remain missing rather than backfill from the future.
No funding payment is charged to a spot account. Publication at exact settlement
is an explicit zero-delay approximation: the historical API does not establish
the original API receipt/publication latency. A sensitivity delay can be applied.
Spot tick/lot specifications remain current snapshots approximating past rules,
as recorded in `instrument_source_manifest.json`.

## CPI: free first-release events are feasible

The BLS archived releases provide historical release documents rather than only
today's revised monthly series. Its archive explicitly identifies **October
2025 CPI as not published** because of the lapse in appropriations. Do not
fabricate that missing observation or assume a fixed monthly release schedule.
[BLS CPI archive](https://www.bls.gov/bls/news-release/cpi.htm).

For this window, September 2025 CPI was released on **24 October 2025**, and
November 2025 CPI on **18 December 2025**. Archive PDFs preserve actual release
dates and embargo times, including the reported values.
[September release](https://www.bls.gov/news.release/archives/cpi_10242025.pdf),
[November release](https://www.bls.gov/news.release/archives/cpi_12182025.pdf).
The agency also publishes revised release scheduling following the shutdowns.
[BLS revised schedule](https://www.bls.gov/bls/2025-lapse-revised-release-dates.htm).

A sound import stores reference month, original reported headline/core values,
actual release timestamp, source URL/hash and revision status. Convert the
document's Eastern Time using `America/New_York`; do not assign a fixed UTC
offset across daylight saving transitions. Do not attach a reference-month
value to that month's first day. First releases can be collected freely, but
only a small number of macro announcements exist in one year: statistical
claims need to reflect that effective sample size.

ALFRED supports historical vintages, while ordinary FRED defaults to information
known today. Real-time start/end parameters are date-level fields. They do not
by themselves establish an intraday release time; marry the correct vintage to
the actual BLS release, or conservatively make it usable on a later verified
date. Registered API credentials may be needed for programmatic access; none
were requested, found or used in this work.
[FRED/ALFRED real-time documentation](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html),
[ALFRED CPI series](https://alfred.stlouisfed.org/series?seid=CPIAUCSL).

An inflation "surprise" also requires a historical consensus forecast observed
before the release. First-release CPI minus last month's CPI is a change, not
an economist-consensus surprise. No verified consensus archive is supplied.
No revised CPI data or invented availability times were imported here.

## QQQ: original Nasdaq access limit and subsequent vendor collection

Nasdaq offers a QQQ historical page and download UI. The source retrieved for
this review displayed that its data was unavailable; no historical daily table
was verified or downloaded. This is an access/verification limitation, not a
claim that QQQ history does not exist.
[Nasdaq QQQ historical page](https://www.nasdaq.com/market-activity/etf/qqq/historical).

A dated QQQ daily close cannot be known to BTC at that day's midnight. Import
the actual session close, respecting holidays, early closes and daylight saving
time, then add a documented provider delay. Nasdaq publishes trading calendars
and early-close notices.
[Nasdaq trading calendar](https://nasdaqtrader.com/Trader.aspx?id=Calendar),
[2025 Christmas early-close notice](https://classic.nasdaqtrader.com/TraderNews.aspx?id=ETA2025-101).
Weekends do not create new QQQ observations. Forward-carrying the last known
close is permissible as a stale predictor if its age is also visible.

Prefer unadjusted observed closes with independently dated corporate actions,
or a vendor's genuine historical adjusted-data vintages. A present-day adjusted
close can incorporate later dividends/splits and is not automatically a
point-in-time input. A free end-of-day table without delivery timestamps needs
an explicit conservative availability policy; it is not a verified intraday
QQQ lead signal. NAV, an index, an ETF trade and an equity-futures contract are
different series and cannot be silently substituted.

## X/social predictors

No X archive was accessed by this workstream. A reliable social feature requires
post IDs, event and collection timestamps, a predeclared query/universe, edit
and deletion handling, sampling coverage, and an API/archive license. Today’s
search results or engagement totals contain selection and future-engagement
bias. Missing historical posts/coverage must remain explicit; no social scores
or point-in-time post counts were invented.

## Subsequent exploratory factor collection

After the nineteen-policy cohort finished with zero hurdle passes, the next
research round collected additional inputs in this same fixed year. They were
not inputs to the original nineteen models; those results remain unchanged.

- **QQQ:** 250 actual daily observations from the [Yahoo Finance vendor chart](https://finance.yahoo.com/quote/QQQ/chart/).
  The collector checks the exact expected session-date set against pinned
  [Nasdaq holiday dates](https://nasdaqtrader.com/Trader.aspx?id=Calendar),
  New York 09:30 vendor session labels, ETF/USD identity and positive finite
  closes. It uses unadjusted `quote.close`, never the currently adjusted close.
  Availability is conservatively **assumed at next UTC midnight**, rather than
  attaching the day's closing price to its morning session label. Original
  historical delivery timestamps and vendor correction vintages are unknown;
  this does not establish an intraday QQQ lead. Splits cause rejection pending
  separately dated unit handling. The [collector](../examples/external_factors/download_qqq.py)
  preserves raw and normalized hashes and supports a read-only verification.
- **CPI:** eleven actual original-release events, including exact published
  headline/core YoY and available MoM values, actual Eastern release dates and
  timezone conversion. The [coverage guide](cpi_factor_sources.md) records
  provenance and the HTTP-access limitation. October 2025 stays absent;
  November MoM remains missing. A consecutive-month acceleration cannot bridge
  the missing October reference month. No economist consensus or inflation
  surprise was imported, and no pre-year baseline was added.
- **Aggressive trade flow:** authentic taker-buy base volume was recovered
  from the already checksum-verified native perpetual trade-kline archives,
  as defined in the [official Binance archive schema](https://github.com/binance/binance-public-data#klines-1).
  The [extractor](../examples/external_factors/extract_flow.py) excludes mark
  archives, checks exact minute grids, and reconciles raw total volume with
  existing Engine bars for all eight assets. Availability is the completed
  candle plus an extra minute. Aggregate taker flow is not book imbalance,
  depth, liquidation identity, executable queue information or an established
  predictive edge.

Collectors retain data under ignored `data_cache/external-factors-1y/`.
New hypotheses and timing tests are in `examples/external_factors/`; the
reused historical year and adaptive design process remain explicit. Importing
real inputs is preparation for an experiment, not a finding of profitability.
