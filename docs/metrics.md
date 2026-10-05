# Independently verified crypto analytics

`aster.analytics.metrics(equity, trades=None, fills=None, benchmark=None)` returns a strict JSON-compatible dictionary. Ratios and returns are fractions, not percentages. P&L, fees, turnover and exposure are in the account's reporting currency; duration is in days or seconds as named. Undefined ratios produce `null`, including no losses, zero volatility, no observations, nonpositive compounding equity, or zero denominators. A positive-return sample without losing trades does not produce an infinite profit factor.

## Inputs and time semantics

The equity frame must have unique chronological UTC-convertible `timestamp` and finite `equity`, including its **initial baseline** before any fills or costs. Cumulative ledger columns are `realized_pnl`, `unrealized_pnl`, `funding_pnl`, `trading_fees`, `slippage_cost`, `liquidation_fees`, and `turnover`. Equity is authoritative: costs are never applied again by analytics. Optional exposures, leverage, trades and fills add further metrics.

Daily returns use the last equity observation in each **UTC calendar day**, including weekends. A baseline-only initial day is excluded; when the first day contains activity, that day's return compares its closing equity with the initial baseline. Calendar days without a ledger observation carry forward the last equity. This assumes a complete account ledger; it does not certify market-data gaps or repair missing events. A partial initial/final day remains a partial day, so short backtests' annualized ratios are unstable. The report records return sample count and elapsed days.

Duration-weighted holdings use a left-continuous convention: snapshot `i` applies until snapshot `i+1`; a final snapshot has zero duration. This prevents bursts of order events from overweighting exposure averages. The simulation's snapshots must follow this convention.

## Formulas

Let `E0` be initial equity, `ET` terminal equity, `Y = elapsed_seconds / (365 × 86400)`, and `r` the daily simple returns. Risk-free rate and minimum acceptable return are zero in this MVP.

| Metric | Definition |
|---|---|
| Total return | `ET / E0 - 1`, with positive initial equity |
| CAGR | `(ET / E0) ** (1 / Y) - 1`, with positive terminal equity and elapsed time; numerical overflow becomes null |
| Annualized volatility | Daily sample standard deviation (`ddof=1`) × `sqrt(365)` |
| Sharpe | Daily arithmetic mean / daily sample standard deviation × `sqrt(365)` |
| Sortino | Daily mean / `sqrt(mean(min(r,0)**2))` × `sqrt(365)`; downside denominator includes all daily observations |
| Drawdown | `1 - equity / running_peak`; max drawdown is a positive loss magnitude |
| Calmar | CAGR / positive max drawdown |
| Drawdown duration | Peak timestamp to recovery at that peak, or end of sample if unrecovered; maximum across episodes |
| Recovery time | Trough timestamp to recovered peak; maximum of completed recoveries, null if none completed |
| Win rate | Strictly positive net trade outcomes / all closed trades; break-even trades count in denominator |
| Profit factor | Sum of positive **net** closed-trade P&L / absolute sum of negative net closed-trade P&L |
| Expectancy / P&L per trade | Arithmetic mean net closed-trade P&L |
| Average win / loss | Mean positive net P&L / mean negative net P&L (loss is negative) |
| Payoff ratio | Average win / absolute average loss |
| Gross profit / loss | Sum of positive gross trade P&L / absolute sum of negative gross trade P&L, before trading fees/funding |
| Turnover | Cumulative filled absolute notional; both entry and exit count |
| Turnover multiple | Turnover / initial equity |
| P&L per unit turnover | Portfolio net profit / turnover |
| Exposure time | Duration with positive gross exposure / elapsed duration |
| Average exposure / leverage | Duration-weighted snapshot values; exposures are currency amounts |
| Net leverage | Net signed exposure / snapshot equity, averaged by duration |
| Trades per day | Closed-trade count / actual elapsed days |
| Maker/taker ratio | Number of maker/taker fills / all fills; partial fills each count |
| Maker notional ratio | Maker absolute fill notional / all absolute fill notional |
| Fees / gross profit | All cumulative trading fees / positive gross closed-trade P&L |
| Slippage / gross profit | All cumulative execution slippage cost / positive gross closed-trade P&L |
| Beta | Sample covariance of aligned portfolio/benchmark daily returns / benchmark sample variance |
| Alpha | `365 × (mean(portfolio daily return) - beta × mean(benchmark daily return))`; arithmetic annualization, zero risk-free rate |

Cost-to-profit ratios include all fills in their numerator but closed trades in their denominator; open positions make that distinction important. Maker rebates can produce negative fees. No silent absolute-value conversion is applied to fee cash flows. Net profit includes open-position mark-to-market; closed-trade attribution therefore need not sum to portfolio profit until all positions close. Symbol and exchange attribution are sums of closed **net** trade P&L.

## Slippage and accounting reconciliation

The engine's `gross_pnl` and equity use actual simulated execution prices, so their P&L **already includes slippage**. Analytics records slippage as diagnostic implementation shortfall and does not subtract it again. In reporting, either display executed-price trading P&L minus fees plus funding minus liquidation fees, or add back diagnostic slippage to construct a reference-price P&L waterfall before subtracting it once. Never subtract diagnostic slippage from executed-price P&L.

`trading_pnl` is cumulative realized plus current unrealized executed-price P&L. A ledger with zero initial accrued P&L/costs should satisfy:

`final_equity - initial_equity = trading_pnl + funding_pnl - trading_fees - liquidation_fees`

This identity presumes no transfers or deposits; transfer accounting requires an external-flow adjusted return model. Liquidation execution loss belongs to trading P&L; the separately reported liquidation fee is the additional penalty. Counts come from closed trades' optional `exit_reason == 'liquidation'`; absent exit reasons produce null rather than an invented zero.

## Chart helpers and descriptive regimes

`monthly_returns` returns year/month/return rows using UTC month-end equity and initial baseline for the first month. `rolling_statistics` returns daily rolling Sharpe, volatility, compounded return and within-window max drawdown; a full window is required. Outputs are Pandas frames with NaN for missing values; use `json_safe` after converting to records if exporting JSON.

`regime_analysis` uses **lagged** benchmark daily returns, or portfolio daily returns if no benchmark is supplied. Over the configured lookback (default 30 days), cumulative return above +5% is “bull”, below -5% is “bear”, and otherwise “sideways”. Annualized volatility at or above 60% is “high_volatility”. Warmup rows are “unknown”. These fixed thresholds are exploratory descriptions, not validated economic states. Portfolio-derived regimes are self-referential and should not be used to claim independent regime robustness. Current day's return cannot change current day's label.

## Independent numerical verification

`tests/test_metrics.py` contains hand-calculated checks covering daily returns `[+10%, -10%, +10%]`, sample volatility/Sharpe/Sortino, CAGR, drawdown and actual-clock recovery, initial intraday baseline, missing calendar days, signed short exposure, duration weighting, net profit factor and payoff, maker fill versus notional ratio, no double subtraction of slippage, exact beta=2/alpha=0, monthly and rolling compounding, causal regime labels, bankruptcy, duplicate timestamps and strict JSON serialization. Nine tests passed with the project's `.venv/bin/python -m pytest tests/test_metrics.py -q`.

These formulas are arithmetic verification, not evidence that execution assumptions or historical data are valid. Annualizing one-day or minute-long samples can produce extreme values; the dashboard should display elapsed period and sample count alongside ratios.
