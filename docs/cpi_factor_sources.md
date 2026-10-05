# Original-release CPI factor source and coverage

The collector uses the [BLS original news-release archive](https://www.bls.gov/bls/news-release/cpi.htm), following observed links rather than guessing a release-date grid. The window is fixed to **2025-10-05 00:00 UTC through 2026-10-05 00:00 UTC exclusive** by actual release time; it contains 11 published releases. Reference months differ from release months: September 2025 data were actually released October 24, not on an assumed mid-month schedule. No earlier price window or prior-release initialization is added.

Only the **current reference month in that release’s Table A** is extracted. Headline/core YoY are not seasonally adjusted; headline/core MoM are seasonally adjusted. Earlier columns printed in later releases are ignored, because seasonal revisions can change historical values. These are archived original-release values, not revised FRED/current-database series. The retrieved archive is not a historical byte-level snapshot proving that no later erratum was applied; raw retrieval hashes pin what was obtained now.

| Reference month | Stated release UTC | Available UTC | Headline / core YoY (%) | Headline / core MoM (%) | Original release |
|---|---|---|---|---|---|
| 2025-09 | 2025-10-24 12:30 | 2025-10-24 12:31 | 3 / 3 | 0.3 / 0.2 | [BLS](https://www.bls.gov/news.release/archives/cpi_10242025.htm) |
| 2025-11 | 2025-12-18 13:30 | 2025-12-18 13:31 | 2.7 / 2.6 | missing / missing | [BLS](https://www.bls.gov/news.release/archives/cpi_12182025.htm) |
| 2025-12 | 2026-01-13 13:30 | 2026-01-13 13:31 | 2.7 / 2.6 | 0.3 / 0.2 | [BLS](https://www.bls.gov/news.release/archives/cpi_01132026.htm) |
| 2026-01 | 2026-02-13 13:30 | 2026-02-13 13:31 | 2.4 / 2.5 | 0.2 / 0.3 | [BLS](https://www.bls.gov/news.release/archives/cpi_02132026.htm) |
| 2026-02 | 2026-03-11 12:30 | 2026-03-11 12:31 | 2.4 / 2.5 | 0.3 / 0.2 | [BLS](https://www.bls.gov/news.release/archives/cpi_03112026.htm) |
| 2026-03 | 2026-04-10 12:30 | 2026-04-10 12:31 | 3.3 / 2.6 | 0.9 / 0.2 | [BLS](https://www.bls.gov/news.release/archives/cpi_04102026.htm) |
| 2026-04 | 2026-05-12 12:30 | 2026-05-12 12:31 | 3.8 / 2.8 | 0.6 / 0.4 | [BLS](https://www.bls.gov/news.release/archives/cpi_05122026.htm) |
| 2026-05 | 2026-06-10 12:30 | 2026-06-10 12:31 | 4.2 / 2.9 | 0.5 / 0.2 | [BLS](https://www.bls.gov/news.release/archives/cpi_06102026.htm) |
| 2026-06 | 2026-07-14 12:30 | 2026-07-14 12:31 | 3.5 / 2.6 | -0.4 / 0 | [BLS](https://www.bls.gov/news.release/archives/cpi_07142026.htm) |
| 2026-07 | 2026-08-12 12:30 | 2026-08-12 12:31 | 3.4 / 2.5 | 0.1 / 0.2 | [BLS](https://www.bls.gov/news.release/archives/cpi_08122026.htm) |
| 2026-08 | 2026-09-11 12:30 | 2026-09-11 12:31 | 3.4 / 2.4 | 0.4 / 0.3 | [BLS](https://www.bls.gov/news.release/archives/cpi_09112026.htm) |

**October 2025 reference CPI was not published** because of the lapse in federal appropriations, explicitly recorded in the BLS archive index. There is no manufactured event or interpolation for it. November 2025 Table A also has dashes for one-month changes; the release discusses a two-month change, which is not substituted for MoM. A consecutive-reference-month factor must skip September→November.

`release_time` comes from the release’s actual stated embargo paragraph, **08:30 Eastern**, converted with `zoneinfo.ZoneInfo("America/New_York")`. The parser checks its weekday. Thus October 24 is12:30 UTC, winter releases are13:30 UTC, and March onward is12:30 UTC. `available_at = release_time + one minute` is an explicit conservative ingestion-lag assumption, not a measured network receipt time. Use `available_at` for any as-of join. No data-derived state exists before the first in-window event becomes available.

Rates `headline_yoy`, `core_yoy`, `headline_mom`, `core_mom` are published **percent-point numbers**: 3.0 means 3.0%, not 0.03. The schema also includes reference_month, release_time, available_at, rate_unit, yoy_adjustment, mom_adjustment, source_url, source_response_sha256, source_transport, value_vintage, release_time_source and availability_assumption. There is **no consensus estimate, surprise, X/social signal or price outcome** in this dataset. Do not describe an actual-rate change as a market-consensus surprise.

## Cache, provenance and reproduction

The ignored directory `data_cache/external-factors-1y/cpi/` contains `raw/`, `source_manifest.json`, `releases.parquet`, `releases.csv` and `coverage.json`. Every retained source response and archive index has a SHA-256. The normalized coverage file hashes its source manifest and both outputs.

In this environment, direct Python requests and curl to the BLS index/release returned **Akamai HTTP 403**. Official BLS pages remained readable through `web.run`. Those exact rendered source responses were retained as UTF-8 `.web.txt` files (with a terminal newline); manifest transport is explicitly `web.run official-page rendered source response`, with `publisher_original_html=false`. Their hashes identify retained tool-response bytes, not publisher-original HTTP HTML. The observed release-link responses and index preserve discovery provenance. No other publisher, revised database or invented figure was substituted.

The [collector](../examples/external_factors/download_cpi.py) defaults to verifying/reusing an existing pinned cache. `--offline` prohibits HTTP. `--refresh` discovers actual links in the official archive index and retrieves original HTML where BLS permits access; HTTP blocks fail explicitly. It does not silently create an empty-success dataset. A fresh environment without the pinned responses must obtain those official responses through an accessible route before offline mode can work.

```bash
.venv/bin/python examples/external_factors/download_cpi.py --offline
# Where BLS permits direct HTTPS:
.venv/bin/python examples/external_factors/download_cpi.py --refresh
# Optional different ignored cache:
.venv/bin/python examples/external_factors/download_cpi.py --out /path/to/cpi-cache --offline
```

A compact pinned public-source bundle is versioned under
`examples/external_factors/cpi_source_snapshot/`. It contains these same rendered
official-page responses and discovery/source hashes, not publisher-original
HTTP bodies. For a fresh clone where direct BLS access is blocked:

```bash
mkdir -p data_cache/external-factors-1y/cpi
cp -R examples/external_factors/cpi_source_snapshot/. data_cache/external-factors-1y/cpi/
.venv/bin/python examples/external_factors/download_cpi.py --offline
```

The collector verifies source hashes, stated date/weekday, Table A row shape, numeric/null fields, UTC window, and11  unique published reference months. It refuses an interpolated October 2025 event. Unknown parser layouts fail rather than infer a rate. No aster source, frozen strategy model, trading output or price cache is modified.

CPI offers only11  events in this year and does not support a strong statistical claim by itself. Any later use should keep this causal availability contract, require consecutive months where appropriate, and report small-sample/selection limitations.
