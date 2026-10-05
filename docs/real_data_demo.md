# One-year historical BTC demonstration

Run date: 6 October 2026 Hong Kong time. Data interval: **2025-10-05 00:00 UTC to 2026-10-05 00:00 UTC**, a full 365 days ending at the latest completed UTC-day boundary at download time. These are downloaded real historical observations, not synthetic fixtures.

Source: [official Binance public archives](https://github.com/binance/binance-public-data) for spot/perpetual OHLC and mark-price candles, plus the [public USD-M funding history API](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data) for settlement rates and marks.

Both spot and perpetual datasets contain **8,760 one-hour bars**, with no duplicates or missing intervals. The perpetual download returned **1,095 historical funding records**. Funding is included at the terminal valuation boundary when a recorded settlement exists there, while bar intervals use exclusive end. All ZIP files were checked against Binance SHA256 CHECKSUM files. Source manifests retain every URL, hash, download timestamp and observed coverage.

The monthly mark archive omitted 24 observations for 29 June 2026. The ingestion process recovered the exact recorded observations from the official daily mark archive, verified its checksum, selected only missing timestamps and rechecked full coverage. No prices were interpolated. This repair is recorded explicitly in the perpetual manifest.

Fixed demonstration parameters were chosen for API illustration rather than optimized against this year: hourly MA fast 24/slow 168, spot allocation50%, perpetual allocation10% with 3× isolated leverage. The funding strategy follows the last published settlement sign for subsequent exposure. Initial capital is 100,000 USDT. All examples use illustrative flat maker 2 bps/taker 5 bps, adverse 2 bps slippage, 10% participation, tick 0.01 and lot 0.001. These historical prices do not validate historical fee tiers or exact venue risk mechanics.

| Example | Net return | Net P&L (USDT) | Funding P&L | Trading fees | Max drawdown |
|---|---:|---:|---:|---:|---:|
| Spot MA | -12.17% | -12,170.91 | 0.00 | 2,077.23 | 22.31% |
| Perpetual MA | -11.46% | -11,464.02 | 180.11 | 2,861.98 | 19.05% |
| Perpetual funding example | 5.14% | 5,137.97 | 1,287.74 | 6,785.85 | 13.36% |

Trading P&L includes execution slippage. Diagnostic slippage is shown in the saved metrics and dashboard without a second cash deduction. Closed lots plus marked open positions reconcile final equity; final liquidation count was zero in each historical demonstration. Partial-close trade counts describe closed average-cost lots, not independent position episodes.

## Reproduce

```bash
.venv/bin/python examples/download_binance.py --symbol BTCUSDT --interval 1h --start 2025-10-05 --end 2026-10-05 --out data_cache/btc-spot-1y
.venv/bin/python examples/download_binance.py --symbol BTCUSDT --interval 1h --market perpetual --start 2025-10-05 --end 2026-10-05 --out data_cache/btc-perpetual-1y
.venv/bin/python main.py backtest --config config/real-btc-1y.yaml
.venv/bin/python main.py backtest --config config/real-btc-perpetual-1y.yaml
.venv/bin/python main.py backtest --config config/real-btc-funding-1y.yaml
.venv/bin/streamlit run dashboard.py
```

Local dashboards are results/real-btc-1y/dashboard.html, results/real-btc-perpetual-1y/dashboard.html and results/real-btc-funding-1y/dashboard.html. Downloaded archives and full ledgers are ignored in Git; compact manifests and summary metrics are versioned here. Binance can revise archive data later, so source checksums identify this exact snapshot.

The candle model cannot observe true queue priority or intrabar mark liquidation. A positive example result is not evidence of a deployable strategy. No parameter search or profit-based cherry-picking was used for this demonstration.
