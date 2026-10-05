# Last-year minute strategy results

Actual source period: **5 October 2025–5 October 2026 UTC**, end exclusive. The final three months, **5 July–5 October 2026**, are the historical holdout. All trading, warmup and selection data is confined to this year.

Eight underlyings: BTC, ETH, DOGE, PEPE, SOL, XRP, LINK and ADA. Exact coverage: 4,204,800 spot minute candles, 4,204,800 perpetual trade candles and matching mark candles, plus 8,760 settled funding observations. Official archives were checksum-verified; no candles or funding values were interpolated.

Thirteen policies were evaluated: eight price/directional-factor hypotheses and five variants of **one funding-carry economic family**. Carry variants are correlated, so their number is not a count of independent edges. All candidates and losers are retained.

| Policy | Validation net | Holdout net | Joint stress net | Daily Sharpe | Minute drawdown | Positive assets | Hurdles |
|---|---:|---:|---:|---:|---:|---:|---|
| trend | -31.48% | 0.75% | -12.72% | 0.28 | 20.09% | 5/8 | FAIL |
| donchian | -7.63% | 7.49% | 3.76% | 1.06 | 17.17% | 6/8 | FAIL |
| mean_reversion | -11.30% | -8.60% | -18.33% | -4.63 | 10.52% | 1/8 | FAIL |
| volatility_breakout | -22.71% | -21.10% | -35.86% | -4.57 | 21.92% | 0/8 | FAIL |
| trend_pullback | -17.07% | -10.79% | -19.51% | -5.53 | 11.11% | 1/8 | FAIL |
| btc_lead_momentum | -24.03% | -11.93% | -22.11% | -4.52 | 12.36% | 0/8 | FAIL |
| btc_lead_reversal | -1.22% | -0.95% | -0.08% | -2.24 | 0.99% | 0/8 | FAIL |
| funding_contrarian | -10.09% | -4.05% | -5.14% | -3.76 | 4.93% | 0/8 | FAIL |
| always_hedged | -0.12% | -0.22% | -1.47% | -2.00 | 0.57% | 4/8 | FAIL |
| positive_trailing | -2.97% | -1.39% | -4.79% | -10.78 | 1.39% | 1/8 | FAIL |
| funding_rotation | -2.08% | -2.13% | -3.48% | -22.12 | 2.13% | 0/8 | FAIL |
| funding_hysteresis | -1.16% | -0.98% | -3.50% | -7.24 | 1.02% | 1/8 | FAIL |
| risk_controlled | -2.83% | -1.28% | -4.92% | -13.07 | 1.28% | 1/8 | FAIL |

**0 of 13 policies passed every predefined historical hurdle.** 0 of those also have a positive lower endpoint in the conditional seven-day block-bootstrap interval corrected conservatively for all thirteen policy tests.

A historical hurdle pass is not certification that a strategy is non-overfit or will work in another regime. Bootstrap intervals depend on the observed short holdout; they do not remove survivorship bias, literature selection, transaction-cost model error or repeated research choices. Some reviewed papers were published during the sample, so this is retrospective research rather than prospective preregistration.

## Evaluation mechanics

Price/factor models select a single shared duration scale on the first six months only, then use three separate fresh-wallet monthly validation folds and a continuous fresh-wallet final-quarter holdout. Carry policies have fixed defaults with no optimization and use a continuous three-month validation run. Their validation conventions differ and are labelled; no training return is merged into holdout equity.

Capital is $100,000 per candidate portfolio, split across eight $12,500 sleeves without transfers. Directional spot entries allocate 95% of current sleeve equity, hold fixed units and pay assumed 10 bps per side. Carry fixes $3,750 notional per leg at entry, long spot and short equivalent perpetual base units with isolated leverage 2; PEPE spot units are explicitly converted to 1000PEPE contract units. Perpetual taker fees assume 5 bps. Actual trading P&L, fees, funding and liquidation costs reconcile in the ledgers.

Baseline adverse slippage is 2 bps for BTC/ETH, 5 for other alts and 8 for DOGE/PEPE, with adverse tick rounding. Joint stress doubles fees and slippage, delays execution one minute, and halves prior-volume participation. Carry exits are submitted before the known horizon and use the same constrained engine; unresolved terminal inventory fails the carry gate. Legs fill separately, so carry is not atomic or risk-free.

All models consume actual minute candles and execute on minute observations. Price-model entry clocks are 15–60 minutes; carry decisions are daily. Holding periods are longer than one minute. These examples therefore assess strategies on minute data, not demonstrated one-minute scalping.

BTC features and published funding observations receive an additional one-minute lag. Funding is only a predictor in the directional spot study; actual funding cashflows are paid or received by the carry perpetual leg. Verified historical QQQ, inflation-surprise and X sentiment inputs were not imported. Their primary sources and publication-time requirements are documented in the research notes.

## Files and reproduction

- [Directional study and compact evidence](../examples/minute_research/README.md)
- [Funding-carry report](minute_carry_results/report.html)
- [Directional report](../examples/minute_research/evidence/dashboard.html)
- [Primary academic research](leading_factor_research.md)
- [Factor data sources](leading_factor_sources.md)
- [Independent validation protocol and audit](minute_validation_protocol.md)
- [User manual](user_manual.md)

Full minute equity, trade/fill/event ledgers, open positions and source manifests remain under the ignored local results folders. Compact metrics, trial results, hourly presentation curves and trading/funding ledgers are versioned. The collector and runner commands regenerate full evidence without an account API key. Current exchange instrument rules approximate dated historical rules; the selected survivor universe is not a historically complete exchange universe.


## Exploratory extension: six signed perpetual hypotheses

These six models were designed after viewing the original thirteen policies on this same year. Their final-quarter evaluation is **reused historical data**, not an untouched holdout. There are now **nineteen disclosed policies and hypotheses**; several are economically correlated. The original cohort above remains unchanged.

| Hypothesis | Validation net | Evaluation net | Joint stress net | Daily Sharpe | Minute drawdown | Positive assets | Exploratory hurdles |
|---|---:|---:|---:|---:|---:|---:|---|
| slow_ema_trend | 1.07% | -1.46% | -3.36% | -0.44 | 7.17% | 4/8 | FAIL |
| weekly_donchian | -0.26% | -1.07% | -1.18% | -0.75 | 3.45% | 1/8 | FAIL |
| ts_momentum_agreement | -1.95% | -1.96% | -4.65% | -0.61 | 6.14% | 1/8 | FAIL |
| signed_mean_reversion | -1.98% | -7.50% | -12.43% | -2.82 | 10.13% | 0/8 | FAIL |
| btc_conditioned_alt_lag | -0.54% | 0.32% | -0.13% | 0.77 | 0.70% | 5/8 | FAIL |
| cross_sectional_momentum | 0.67% | -3.03% | -3.77% | -4.10 | 3.93% | 4/8 | FAIL |

**0 of six passed the declared exploratory historical hurdles.** A pass cannot establish absence of overfitting or supply an independent successful strategy.

Each model uses eight segregated $12,500 sleeves, 25% entry notional, native perpetual units and isolated leverage one. Quantities stay fixed between direction changes. Actual settlement funding is included. Base taker fees are 5 bps; the same liquidity-class slippage and joint cost/delay/participation stress apply. Open positions stay marked, and an indicative fee/slippage exit reserve is a separate diagnostic rather than an invented fill. Positive reserve-adjusted validation, evaluation, stress and neighbors, plus zero simulated liquidations, are additional gates.

Scalar models require five profitable sleeves. The cross-sectional portfolio instead requires actual fills across at least four assets, with all losing hedge legs retained in pooled P&L. It holds two ranked longs and two ranked shorts; beta and subsequent notional drift are not neutralized. These rules were frozen before this batch produced outcomes.

Failed gates for every exploratory hypothesis:

- `slow_ema_trend`: evaluation_positive, jointstress_positive, two_positive_months, sharpe_at_least_half, all_neighbors_positive, no_liquidations, evaluation_positive_after_indicative_reserve, jointstress_positive_after_indicative_reserve, all_neighbors_positive_after_indicative_reserve, broad_symbol_success.
- `weekly_donchian`: validation_positive, evaluation_positive, jointstress_positive, two_positive_months, sharpe_at_least_half, all_neighbors_positive, validation_positive_after_indicative_reserve, evaluation_positive_after_indicative_reserve, jointstress_positive_after_indicative_reserve, all_neighbors_positive_after_indicative_reserve, broad_symbol_success.
- `ts_momentum_agreement`: validation_positive, evaluation_positive, jointstress_positive, two_positive_months, sharpe_at_least_half, all_neighbors_positive, no_liquidations, validation_positive_after_indicative_reserve, evaluation_positive_after_indicative_reserve, jointstress_positive_after_indicative_reserve, all_neighbors_positive_after_indicative_reserve, broad_symbol_success.
- `signed_mean_reversion`: validation_positive, evaluation_positive, jointstress_positive, two_positive_months, sharpe_at_least_half, all_neighbors_positive, no_liquidations, validation_positive_after_indicative_reserve, evaluation_positive_after_indicative_reserve, jointstress_positive_after_indicative_reserve, all_neighbors_positive_after_indicative_reserve, broad_symbol_success.
- `btc_conditioned_alt_lag`: validation_positive, jointstress_positive, validation_positive_after_indicative_reserve, jointstress_positive_after_indicative_reserve.
- `cross_sectional_momentum`: evaluation_positive, jointstress_positive, two_positive_months, sharpe_at_least_half, all_neighbors_positive, no_liquidations, evaluation_positive_after_indicative_reserve, jointstress_positive_after_indicative_reserve, all_neighbors_positive_after_indicative_reserve.

A separate conditional seven-day block-bootstrap diagnostic now uses Bonferroni adjustment across all nineteen comparisons. It uses full-resolution pooled ledgers and records their hashes. This adjustment does not correct the adaptive design process, regime change, survivors or execution uncertainty. The earlier thirteen-policy diagnostic is retained as cohort-specific evidence.

[Exploratory report](minute_directional_results/report.html) · [All nineteen conditional intervals](minute_directional_results/combined_selection_diagnostic19.json) · [Reproduction guide](../examples/minute_directional/README.md) · [Independent audit](minute_directional_audit.md)


## External-factor extension: five further exploratory hypotheses

This new cohort follows the nineteen outcomes above and reuses the same evaluated year. It introduces actual QQQ daily closes, eleven original CPI releases and authentic aggressive trade flow. Funding-crowding and premium mechanisms overlap earlier carry research. There are **twenty-four cumulative disclosed policies and hypotheses**, not twenty-four independent demonstrated edges.

| Hypothesis | Validation net | Evaluation net | Joint stress net | Daily Sharpe | Minute drawdown | Positive sleeves | Exploratory hurdles |
|---|---:|---:|---:|---:|---:|---:|---|
| qqq_risk_transmission | -8.19% | -0.08% | -0.67% | -0.02 | 2.83% | 4/8 | FAIL |
| cpi_acceleration_event | -0.39% | 0.06% | -0.06% | 0.14 | 0.90% | 6/8 | FAIL |
| funding_crowding_fade | 0.34% | 0.05% | 0.03% | 1.11 | 0.33% | 1/8 | FAIL |
| perpetual_premium_fade | -0.02% | 0.00% | 0.00% | undefined | -0.00% | 0/8 | FAIL |
| taker_flow_drift | -31.07% | -29.63% | -47.79% | -25.34 | 29.85% | 0/8 | FAIL |

**0 of five passed the unchanged exploratory historical hurdles.** No pass can restore an untouched evaluation or establish absence of overfitting.

QQQ unadjusted closes use conservative assumed next-UTC-day availability and calendar coverage checks. CPI uses actual first-release availability plus a minute, skips the unpublished October reference month and carries no consensus surprise. One announcement produces correlated exposure across eight sleeves, not eight independent events. Flow uses native trade-kline taker-buy volume, not mark volume or order-book depth. All signals and orders remain causal; no pre-year external initialization was added.

Capital, native quantities, actual funding, fees, slippage, joint execution stress, marked terminal positions and diagnostic exit reserves follow the signed-perpetual experiment above. Every failure, zero-activity case and phase event count is retained in the full summary. No previous model or result was retuned.

Failed gates:

- `qqq_risk_transmission`: validation_positive, evaluation_positive, jointstress_positive, sharpe_at_least_half, all_neighbors_positive, no_liquidations, broad_symbol_success, validation_positive_after_indicative_reserve, evaluation_positive_after_indicative_reserve, jointstress_positive_after_indicative_reserve, all_neighbors_positive_after_indicative_reserve.
- `cpi_acceleration_event`: validation_positive, jointstress_positive, two_positive_months, sharpe_at_least_half, all_neighbors_positive, validation_positive_after_indicative_reserve, jointstress_positive_after_indicative_reserve, all_neighbors_positive_after_indicative_reserve.
- `funding_crowding_fade`: broad_symbol_success.
- `perpetual_premium_fade`: validation_positive, evaluation_positive, jointstress_positive, two_positive_months, sharpe_at_least_half, all_neighbors_positive, broad_symbol_success, validation_positive_after_indicative_reserve, evaluation_positive_after_indicative_reserve, jointstress_positive_after_indicative_reserve, all_neighbors_positive_after_indicative_reserve.
- `taker_flow_drift`: validation_positive, evaluation_positive, jointstress_positive, two_positive_months, sharpe_at_least_half, minute_drawdown_within20pct, all_neighbors_positive, no_liquidations, broad_symbol_success, validation_positive_after_indicative_reserve, evaluation_positive_after_indicative_reserve, jointstress_positive_after_indicative_reserve, all_neighbors_positive_after_indicative_reserve.

The separate twenty-four-comparison conditional bootstrap retains source hashes and leaves earlier cohort diagnostics intact. It does not correct the full adaptive design process or uncertain historical execution. No confidence interval proves durable profitability.

[External-factor report](external_factor_results/report.html) · [Data and reproduction](../examples/external_factors/README.md) · [Collector and signal audit](external_factor_audit.md) · [CPI source coverage](cpi_factor_sources.md)
