# Bybit corroboration of the 2026-08-22 LINK/SOL selloff

This compact evidence covers exactly two assets and one UTC day within the original one-year research window. `focus_comparison.csv` compares actual Bybit trade reconstructions with the frozen Binance spot/perpetual/mark observations at 05:08–05:16 UTC. `validation_summary.json` records trade counts, occupied minutes and quality checks. `source_manifest.json` pins official URLs, raw gzip hashes, retrieved metadata, and Binance comparison input hashes. The two current instrument JSON responses identify USDT-settled linear perpetual products with LINK/SOL base units; they do not establish historical exchange rules.

Bybit's [official documentation](https://bybit-exchange.github.io/docs/v5/market/recent-trade) points users to historical trade archives. The exact filenames were confirmed in the official [LINK directory](https://public.bybit.com/trading/LINKUSDT/) and [SOL directory](https://public.bybit.com/trading/SOLUSDT/) before downloading. Raw gzip files and HTML listing copies are intentionally omitted from versioned evidence. SHA-256 pins the downloaded bytes locally; no publisher checksum file is asserted, and multipart ETags are not checksums.

From the repository root, manually download only these two original files if the ignored cache is absent:

```bash
mkdir -p data_cache/outlier-validation
curl --fail --location --output data_cache/outlier-validation/LINKUSDT2026-08-22.csv.gz https://public.bybit.com/trading/LINKUSDT/LINKUSDT2026-08-22.csv.gz
curl --fail --location --output data_cache/outlier-validation/SOLUSDT2026-08-22.csv.gz https://public.bybit.com/trading/SOLUSDT/SOLUSDT2026-08-22.csv.gz
.venv/bin/python examples/minute_research/validate_outlier.py
```

The script also requires the existing, exact Binance LINK/SOL `bars.parquet` inputs under `data_cache/minute-1y` and `data_cache/minute-perpetual-1y`. It checks the four Parquet hashes and both Bybit gzip hashes against the versioned manifest. A mismatch or missing input fails explicitly; it never fetches or substitutes comparison data. Recreating Binance data from an archive may produce different Parquet byte hashes even when semantic rows agree; such a new comparison requires an explicitly reviewed manifest rather than bypassing the pinned-input check.

The script parses fractional Unix seconds without floating-point boundary rounding, preserves archive order for timestamp ties, reconstructs first/max/min/last actual trade OHLC, and sums observed base/quote volumes. Every minute must contain trades; missing minutes cause failure, with no interpolation. It writes derived minute Parquet files, a comparison CSV and validation summary into the ignored cache. Use `--cache PATH`, `--workspace PATH`, or `--out PATH` to relocate raw inputs, Binance inputs or derived outputs. No trading source, package data, results or raw files are changed.

```bash
.venv/bin/python examples/minute_research/validate_outlier.py --out /tmp/bybit-outlier-review
```

Bybit independently corroborates the abrupt LINK/SOL market decline. Venue volumes do not establish available order-book depth, and neither the mark discrepancy nor profitable execution follows from this price-event confirmation. See [the forensic report](../minute_data_outliers.md) for interpretation and limitations.
