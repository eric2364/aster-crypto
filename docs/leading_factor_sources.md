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

## QQQ: a free public page exists, but usable history is not yet verified

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
