# Dashboard and offline reporting

Launch from the repository root:

```bash
.venv/bin/streamlit run dashboard.py
```

The sidebar defaults to `results/`. Change the directory field to any saved run directory or a directory containing run subdirectories. A run needs `equity.csv`; `trades.csv`, `fills.csv`, `funding.csv`, `events.csv`, `positions.csv`, `metadata.json` and `metrics.json` are optional. Empty ledger CSVs are handled. Metrics are calculated from the ledger if `metrics.json` is absent. Filtering ledger rows does not recalculate portfolio metrics, so a venue or symbol filter cannot accidentally masquerade as portfolio-level attribution.

The dark dashboard presents 12 metric cards, equity, underwater drawdown, a P&L waterfall, gross leverage, long/short/net exposure, closed-trade symbol and exchange contribution, UTC monthly heatmap, four rolling statistics, net trade P&L distribution, holding-duration distribution, and maker/taker/funding/slippage totals. Rolling statistics require 30 complete UTC-day observations. Short samples display gaps instead of inventing statistics. Provenance, execution/risk configuration and data-quality evidence remain visible in their own tab. Missing metrics appear as an em dash.

Use the ledger explorer to choose trades, fills, funding, events, positions or equity. Venue and symbol filters appear where the selected ledger has those fields. Download exports exactly the currently selected rows as CSV.

## Offline HTML

```python
from aster.reports import write_html, charts

write_html(result, 'results/my_run/dashboard.html')
figures = charts(result)  # mapping of chart names to Plotly Figure objects
```

The HTML contains Plotly's JavaScript inline once, with no external script or stylesheet request. It can be opened without internet connectivity. It includes the same charts/cards and expanded run provenance. Ledger exploration is available through the Streamlit view and separately exported ledgers. Offline charts retain zoom, hover and image-export interactions.

## Benchmark data

Attach a DataFrame as `result.benchmark`, save a `benchmark.csv` alongside the result, or upload a benchmark CSV in Streamlit. The first column must be `timestamp`; other numeric columns are equity or prices, for example:

```csv
timestamp,BTC buy & hold,ETH buy & hold
2024-01-01T00:00:00Z,42000,2200
2024-01-02T00:00:00Z,43000,2250
```

Each benchmark is rebased to portfolio equity at its first overlap. Comparison values use only a benchmark observation at or before the portfolio timestamp; there is no future-data backward fill. Before first overlap, the line is absent. Values may carry forward from an older observation, so the user must supply suitably sampled data and review stale prices. Duplicate benchmark timestamps are rejected. Benchmark price data is a gross buy-and-hold comparison and does not silently include transaction fees. The reporter does not download market data or fabricate benchmarks. A late-starting benchmark has a shorter comparison period, visible on the chart.

## Cost interpretation

The execution ledger's trading P&L includes simulated fill-price slippage. The waterfall adds back diagnostic slippage to form reference-price trading P&L, then subtracts slippage once, subtracts fees, adds signed funding and subtracts liquidation fees. This reconciles to executed-price net P&L without double counting. Maker/taker bars display positive fees as costs and negative rebates as benefits; signed funding is inverted in the “funding paid” bar so received funding is negative cost. Closed-trade symbol/exchange contribution can differ from current portfolio profit when positions remain open.

## Verification

A synthetic 45-day result verified all 15 figures and a self-contained HTML file with no external script tags. Streamlit `AppTest` loaded a persisted synthetic run, rendered all 12 metric cards, and reported no exceptions. A benchmark beginning three timestamps after the portfolio left all earlier benchmark observations missing, confirming no future fill. This is functional UI verification; no rendered screenshot or pixel-level visual audit was performed.
