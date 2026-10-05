# Why the disclosed historical candidates did not qualify

These are original-engine reports, now provisional after the partial-exit margin correction. They describe recorded outcomes, not corrected-engine performance. This is a read-only attribution of the published final-quarter evaluations. It neither retunes a rule nor changes its fills, funding, inventory, accounting or hurdle. All source summaries are hashed.

Of 24 candidates, 18 had negative evaluation net P&L. Even adding back their actual trading and liquidation fees while holding executions fixed leaves 16 with negative evaluation P&L. The zero-return premium rule had no evaluation trades. All 24 failed at least one declared hurdle.

Fee addback is an accounting diagnostic, **not a realizable return or a rerun without costs**. Fill prices already contain adverse slippage and rounding. Slippage is separately reported and is not deducted again. Removing execution costs, changing to maker orders or relaxing thresholds would change fills and exposure; these tables do not simulate that counterfactual.

| Candidate | Evaluation net | Same fills, fees added back | Completed trades | Hurdles |
|---|---:|---:|---:|---|
| trend | 0.747% | 12.724% | 4517 | FAIL |
| donchian | 7.493% | 10.582% | 527 | FAIL |
| mean_reversion | -8.605% | -0.835% | 3921 | FAIL |
| volatility_breakout | -21.103% | -6.341% | 7714 | FAIL |
| trend_pullback | -10.787% | -2.191% | 3253 | FAIL |
| btc_lead_momentum | -11.934% | -1.662% | 4715 | FAIL |
| btc_lead_reversal | -0.952% | -0.750% | 11 | FAIL |
| funding_contrarian | -4.055% | -3.225% | 697 | FAIL |
| always_hedged | -0.216% | 0.140% | 164 | FAIL |
| positive_trailing | -1.392% | -0.490% | 452 | FAIL |
| funding_rotation | -2.128% | -1.058% | 626 | FAIL |
| funding_hysteresis | -0.979% | -0.256% | 356 | FAIL |
| risk_controlled | -1.284% | -0.479% | 440 | FAIL |
| slow_ema_trend | -1.459% | -0.496% | 368 | FAIL |
| weekly_donchian | -1.069% | -0.979% | 29 | FAIL |
| ts_momentum_agreement | -1.957% | -0.565% | 565 | FAIL |
| signed_mean_reversion | -7.499% | -5.174% | 814 | FAIL |
| btc_conditioned_alt_lag | 0.319% | 0.634% | 135 | FAIL |
| cross_sectional_momentum | -3.025% | -2.671% | 120 | FAIL |
| qqq_risk_transmission | -0.083% | 0.151% | 75 | FAIL |
| cpi_acceleration_event | 0.056% | 0.106% | 16 | FAIL |
| funding_crowding_fade | 0.053% | 0.062% | 3 | FAIL |
| perpetual_premium_fade | 0.000% | 0.000% | 0 | FAIL |
| taker_flow_drift | -29.633% | -16.919% | 5530 | FAIL |

The funding-crowding rule earned a small positive evaluation result through three PEPE trades with seven idle sleeves. That is concentration rather than multi-asset validation. CPI had just two directional evaluation releases; correlated coin positions do not create more independent macro events. Previous positive price-breakout examples failed validation or stress and were sensitive to concentrated episodes.

The current perpetual assumptions imply a simple two-sided taker fee/slippage floor of 14 bps for BTC/ETH, 20 bps for ordinary altcoins and 26 bps for DOGE/PEPE, before tick rounding, market impact and funding. These are this project’s assumed costs, not a verified historical fee tier. A minute signal must exceed those costs or hold long enough to accumulate a larger move. Maker profitability needs independent quote/book evidence; a touched candle is not a guaranteed fill.

[Complete outcomes](../minute_strategy_results.md) · [Attribution CSV](failure_attribution.csv) · [Source hashes and definitions](failure_attribution.json)
