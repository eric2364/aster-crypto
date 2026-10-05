# Forensic review of minute data and August equity concentration

Reviewed 2026-10-06. Scope: the eight spot markets and corresponding USDT perpetual trade and mark candles, **2025-10-05 00:00 UTC through 2026-10-05 00:00 UTC exclusive**, and existing `results/minute-study-1y/pooled` equity exports. This is a read-only audit; no candles, prices, source code, positions, or interpolation were changed.

## Findings

**The profitable Donchian and trend holdout results are dominated by one August episode.** Aug 19–22 contributes $15,721.89 to Donchian against $7,492.69 total profit; trend receives $17,187.00 against $746.60 total profit. Outside the episode both lose money. That concentration is sufficient to withhold a robustness claim even if every candle is genuine.

The apparent ~25% chart spike is a multi-day correlated rally followed by a synchronous high-volume reversal. Both curves peak **2026-08-22 04:44 UTC**, then eight spot markets fall around **05:09–05:10 UTC**. On Aug 21, daily-close pooled returns were +11.4642% Donchian and +11.9612% trend, rather than a single +25% daily-close return. The episode is visible in spot, perpetual trades, and marks. High trade counts rule out the August focus candles consisting of one isolated trade, but do not establish that every high/low was executable at the assumed fill price.

Archive integrity and correct normalization pass the additional checks below. **Limited independent Bybit trade corroboration now confirms the August 22 LINK/SOL selloff (see the appended check). Execution quality and the broader one-year market representativeness remain unverified.** Binance spot, perpetual and mark series share the same venue and some underlying price inputs; their agreement is not three independent sources. No news explanation, historical listing change, or token rebase is asserted.

## Definitions and coverage

Minute return is `close[t] / close[t-1] - 1`; times below are candle **start** times and the candle is complete one minute later. Daily return compares the last close of successive complete UTC days. The first and final partial archive months are clipped to the exact requested window. Largest means largest absolute return, retaining its sign. Mark returns use mark candle close (`mark_price`), not a tradable fill. All price tables use USDT per one spot base unit. For PEPE, perpetual prices are divided by 1,000 solely for comparison: the stored source remains **1000PEPEUSDT**, base **1000PEPE**, engine multiplier 1; one perpetual unit hedges 1,000 spot PEPE.

Each of 24 price streams has 525,600 rows on the same complete one-minute grid. Spot and perpetual candles have no duplicate timestamps, nonpositive low, or OHLC envelope violation in this scan. No missing minute, delisting gap, or sudden factor-1,000 normalization switch is observed. Current exchangeInfo is not historical listing/rules evidence. A smooth complete series cannot rule out a venue-wide archive or upstream problem.

## Largest minute and daily close changes in the full year

| Symbol | Stream | Largest minute, UTC | Previous → current close | Minute return | Largest daily UTC return | Daily previous → close |
|---|---|---|---|---:|---|---|
| BTCUSDT | spot | 2025-10-10 21:19:00 | 108635.51 → 103975.26 | -4.289804% | 2026-02-05: -14.017431% | 73165.83 → 62909.86 |
| BTCUSDT | perp_trade | 2025-10-10 21:19:00 | 108889.6 → 103441.3 | -5.003508% | 2026-02-05: -14.041106% | 73137.4 → 62868.1 |
| BTCUSDT | mark | 2025-10-10 21:19:00 | 109340.489255 → 104393.2 | -4.524664% | 2026-02-05: -14.023451% | 73148.9 → 62890.9 |
| ETHUSDT | spot | 2025-10-10 21:21:00 | 3488.88 → 3650.05 | +4.619534% | 2026-08-19: +17.464870% | 1917.85 → 2252.8 |
| ETHUSDT | perp_trade | 2025-10-10 21:21:00 | 3500 → 3706.38 | +5.896571% | 2026-08-19: +17.477440% | 1917.1 → 2252.16 |
| ETHUSDT | mark | 2025-10-10 21:21:00 | 3504.78 → 3690.19049031 | +5.290218% | 2026-08-19: +17.480887% | 1917.09 → 2252.21433333 |
| DOGEUSDT | spot | 2025-10-10 21:18:00 | 0.16785 → 0.12822 | -23.610366% | 2025-10-10: -22.133687% | 0.24849 → 0.19349 |
| DOGEUSDT | perp_trade | 2025-10-10 21:21:00 | 0.08856 → 0.11986 | +35.343270% | 2025-10-10: -22.263817% | 0.24843 → 0.19312 |
| DOGEUSDT | mark | 2025-10-10 21:21:00 | 0.09213206 → 0.11921733 | +29.398312% | 2025-10-10: -22.283943% | 0.24843 → 0.19307 |
| PEPEUSDT | spot | 2025-10-10 21:22:00 | 3.24e-06 → 4.26e-06 | +31.481481% | 2026-08-21: +28.348910% | 3.21e-06 → 4.12e-06 |
| PEPEUSDT | perp_trade | 2025-10-10 21:22:00 | 3.2401e-06 → 4.5131e-06 | +39.288911% | 2026-08-21: +28.490366% | 3.2074e-06 → 4.1212e-06 |
| PEPEUSDT | mark | 2025-10-10 21:22:00 | 3.2466e-06 → 4.28471e-06 | +31.975297% | 2026-08-21: +28.469701% | 3.20885e-06 → 4.1224e-06 |
| SOLUSDT | spot | 2026-08-22 05:10:00 | 95.53 → 90.27 | -5.506124% | 2026-02-05: -14.947894% | 92.12 → 78.35 |
| SOLUSDT | perp_trade | 2025-10-10 21:18:00 | 175.95 → 155.16 | -11.815857% | 2025-10-10: -15.013587% | 220.8 → 187.65 |
| SOLUSDT | mark | 2025-10-10 21:22:00 | 154.43 → 168.4284162 | +9.064570% | 2025-10-10: -15.023678% | 220.80268421 → 187.63 |
| XRPUSDT | spot | 2025-10-10 21:20:00 | 1.7952 → 1.4006 | -21.980838% | 2026-02-06: +21.011032% | 1.2146 → 1.4698 |
| XRPUSDT | perp_trade | 2025-10-10 21:21:00 | 1.3722 → 1.7032 | +24.121848% | 2026-02-06: +20.995386% | 1.2136 → 1.4684 |
| XRPUSDT | mark | 2025-10-10 21:21:00 | 1.3424 → 1.6922 | +26.057807% | 2026-02-06: +20.917401% | 1.2143 → 1.4683 |
| LINKUSDT | spot | 2025-10-10 21:19:00 | 13.84 → 11.24 | -18.786127% | 2025-10-10: -21.282401% | 21.99 → 17.31 |
| LINKUSDT | perp_trade | 2025-10-10 21:19:00 | 13.61 → 10.875 | -20.095518% | 2025-10-10: -21.427272% | 21.986 → 17.275 |
| LINKUSDT | mark | 2025-10-10 21:19:00 | 13.94382951 → 10.892 | -21.886595% | 2025-10-10: -21.396939% | 21.986 → 17.28166905 |
| ADAUSDT | spot | 2025-10-10 21:19:00 | 0.4349 → 0.3398 | -21.867096% | 2025-10-10: -22.068204% | 0.8152 → 0.6353 |
| ADAUSDT | perp_trade | 2025-10-10 21:19:00 | 0.4318 → 0.3373 | -21.885132% | 2025-10-10: -22.122699% | 0.815 → 0.6347 |
| ADAUSDT | mark | 2025-10-10 21:19:00 | 0.43991013 → 0.34532277 | -21.501519% | 2025-10-10: -22.144547% | 0.815 → 0.63452194 |

Most full-year minute extremes cluster around **2025-10-10 21:18–21:22 UTC**. Rebound and decline extremes are both included; close-to-close maxima alone are not a tail-risk or liquidity model. SOL spot is the exception: its largest absolute minute change is the August 22 decline.

## Intraminute wicks: additional execution risk

The maximum full-year `(high / low - 1)` in each trade stream is shown below. This range statistic differs from close returns. A high trade count does **not** establish how many trades occurred at an extreme; a single extreme print within a busy candle remains possible without tick data.

| Symbol | Stream | UTC minute start | Low / high / close per spot unit | High/low range | Trades | Quote volume, USDT |
|---|---|---|---|---:|---:|---:|
| BTCUSDT | spot | 2025-10-10 21:24:00 | 102000 / 108923 / 108219.08 | 6.787255% | 143,555 | 48,050,191.45 |
| BTCUSDT | perp | 2025-10-10 21:19:00 | 102193.6 / 109568.2 / 103441.3 | 7.216303% | 129,306 | 1,006,184,304.20 |
| ETHUSDT | spot | 2025-10-10 21:56:00 | 3889 / 4380 / 4066.66 | 12.625354% | 423,773 | 80,395,327.98 |
| ETHUSDT | perp | 2025-10-10 21:21:00 | 3500 / 3780 / 3706.38 | 8.000000% | 112,180 | 456,213,442.66 |
| DOGEUSDT | spot | 2025-10-10 21:20:00 | 0.095 / 0.17103 / 0.10077 | 80.031579% | 71,206 | 7,902,356.51 |
| DOGEUSDT | perp | 2025-10-10 21:18:00 | 0.12031 / 0.16946 / 0.13149 | 40.852797% | 48,988 | 53,881,813.11 |
| PEPEUSDT | spot | 2025-10-10 21:19:00 | 2.79e-06 / 4.2e-06 / 3.2e-06 | 50.537634% | 8,684 | 1,853,944.18 |
| PEPEUSDT | perp | 2025-10-10 21:19:00 | 2.7752e-06 / 4.216e-06 / 3.2241e-06 | 51.916979% | 29,012 | 11,752,812.05 |
| SOLUSDT | spot | 2025-12-31 20:28:00 | 124.08 / 132.75 / 124.16 | 6.987427% | 81,688 | 55,025,881.34 |
| SOLUSDT | perp | 2025-10-10 21:22:00 | 154.4 / 176.65 / 168.97 | 14.410622% | 44,626 | 93,579,259.84 |
| XRPUSDT | spot | 2025-10-10 21:21:00 | 1.2543 / 1.8726 / 1.6535 | 49.294427% | 38,778 | 7,902,863.65 |
| XRPUSDT | perp | 2025-10-10 21:21:00 | 1.1792 / 1.7776 / 1.7032 | 50.746269% | 36,954 | 49,630,492.11 |
| LINKUSDT | spot | 2025-10-10 21:20:00 | 9.01 / 11.25 / 9.24 | 24.861265% | 6,413 | 1,816,002.93 |
| LINKUSDT | perp | 2025-10-10 21:19:00 | 10.619 / 13.648 / 10.875 | 28.524343% | 15,631 | 12,377,718.54 |
| ADAUSDT | spot | 2025-10-10 21:19:00 | 0.3398 / 0.5177 / 0.3398 | 52.354326% | 21,274 | 3,727,473.55 |
| ADAUSDT | perp | 2025-10-10 21:19:00 | 0.3345 / 0.459 / 0.3373 | 37.219731% | 32,986 | 20,730,511.72 |

Two spot-specific wick anomalies deserve separate inspection, even though they are outside the August holdout spike:

- ETHUSDT 2025-10-10 21:56 UTC: spot high 4380, low 3889, close 4066.66; perpetual high 3960, low 3880.01, close 3956.52; mark close 3949.35. A fill at the spot wick cannot be justified merely by the trade-volume total.
- SOLUSDT 2025-12-31 20:28 UTC: spot high 132.75, low 124.08, close 124.16; perpetual high 124.95, low 124.01, close 124.08; mark close 124.11. A fill at the spot wick cannot be justified merely by the trade-volume total.

Neither anomaly is corrected or assigned a news cause here. Both reinforce the need for tick-level corroboration and conservative limits on fills inferred from minute high/low.

## August selloff: exact spot candles and contemporaneous trade/mark closes

| Symbol | UTC Aug 22 start | Spot previous → close | Return | Spot open / high / low | Base volume | USDT quote volume | Trades | Perp close / mark close per spot unit |
|---|---|---|---:|---|---:|---:|---:|---|
| BTCUSDT | 05:10:00 | 77802 → 76742.11 | -1.362291% | 77802 / 77859.85 / 76618.7 | 729.89662 | 56,335,733.06 | 43,989 | 76742 / 77151.1153475 |
| ETHUSDT | 05:10:00 | 2452.94 → 2392.57 | -2.461128% | 2452.94 / 2461.62 / 2385 | 21230.0801 | 51,672,134.09 | 56,740 | 2390.63 / 2415.96133248 |
| DOGEUSDT | 05:10:00 | 0.09141 → 0.08488 | -7.143639% | 0.09108 / 0.09141 / 0.0848 | 99416628 | 8,723,141.46 | 51,710 | 0.08461 / 0.08489225 |
| PEPEUSDT | 05:09:00 | 4.23e-06 → 3.85e-06 | -8.983452% | 4.24e-06 / 4.25e-06 / 3.85e-06 | 971931123789 | 3,943,511.16 | 15,799 | 3.8572e-06 / 3.89022e-06 |
| SOLUSDT | 05:10:00 | 95.53 → 90.27 | -5.506124% | 95.52 / 95.89 / 89.83 | 227133.473 | 21,104,441.68 | 45,188 | 90 / 90.82307066 |
| XRPUSDT | 05:10:00 | 1.532 → 1.4561 | -4.954308% | 1.5334 / 1.55 / 1.4411 | 11963147.4 | 18,033,504.51 | 36,543 | 1.452 / 1.45873768 |
| LINKUSDT | 05:10:00 | 12.031 → 11.191 | -6.981963% | 12.032 / 12.049 / 11.17 | 213418.18 | 2,497,183.46 | 17,239 | 10.934 / 11.69628277 |
| ADAUSDT | 05:10:00 | 0.2374 → 0.2147 | -9.561921% | 0.2373 / 0.2391 / 0.2132 | 17109578.5 | 3,914,659.87 | 19,922 | 0.2149 / 0.22093696 |

PEPE’s largest August focus decline occurs one minute earlier than the other seven; its 05:10 close is 0.00000374, normalized perpetual close 0.0000038072 and mark 0.00000378039. These are aggregate minute observations, not simultaneous bid/ask quotes. A minute’s last trade may precede its boundary and the mark can reflect a different sampling/filtering process.

The immediate recovery also matters: at 05:11 DOGE spot/perp/mark were 0.08973 / 0.08923 / 0.08678914; SOL 90.49 / 90.79 / 89.21139829. Thus mark/trade differences change sign during the reversal. Treating mark as an execution quote, or assuming a spot/perpetual close pair is simultaneously executable, can turn a sampling dislocation into apparent carry profit.

## Basis discrepancies relevant to carry and liquidation

Basis below is the signed ratio minus one, for the largest absolute minute-close discrepancy in each pair over the full year. It is descriptive and is not executable arbitrage.

| Symbol | Pair | UTC minute start | Signed discrepancy | Spot / perp / mark (per spot unit) |
|---|---|---|---:|---|
| BTCUSDT | trade_spot | 2026-08-19 15:27:00 | +1.816908% | 69052.48 / 70307.1 / 69427.3630082 |
| BTCUSDT | mark_spot | 2025-10-10 21:29:00 | +0.764057% | 108432.09 / 109183 / 109260.573391 |
| BTCUSDT | mark_trade | 2026-08-19 15:27:00 | -1.251278% | 69052.48 / 70307.1 / 69427.3630082 |
| ETHUSDT | trade_spot | 2025-10-10 21:56:00 | -2.708365% | 4066.66 / 3956.52 / 3949.35 |
| ETHUSDT | mark_spot | 2025-10-10 21:56:00 | -2.884677% | 4066.66 / 3956.52 / 3949.35 |
| ETHUSDT | mark_trade | 2025-10-10 21:19:00 | +1.405762% | 3500.6 / 3476.18 / 3525.04681504 |
| DOGEUSDT | trade_spot | 2025-10-10 21:20:00 | -12.116701% | 0.10077 / 0.08856 / 0.09213206 |
| DOGEUSDT | mark_spot | 2025-10-10 21:20:00 | -8.571936% | 0.10077 / 0.08856 / 0.09213206 |
| DOGEUSDT | mark_trade | 2025-10-10 21:24:00 | -4.253715% | 0.14043 / 0.14521 / 0.13903318 |
| PEPEUSDT | trade_spot | 2025-10-10 21:22:00 | +5.941315% | 4.26e-06 / 4.5131e-06 / 4.28471e-06 |
| PEPEUSDT | mark_spot | 2025-10-10 21:19:00 | -4.444063% | 3.2e-06 / 3.2241e-06 / 3.05779e-06 |
| PEPEUSDT | mark_trade | 2025-10-10 21:19:00 | -5.158339% | 3.2e-06 / 3.2241e-06 / 3.05779e-06 |
| SOLUSDT | trade_spot | 2025-10-10 21:20:00 | -17.754123% | 181.31 / 149.12 / 147.35 |
| SOLUSDT | mark_spot | 2025-10-10 21:20:00 | -18.730351% | 181.31 / 149.12 / 147.35 |
| SOLUSDT | mark_trade | 2025-10-10 21:18:00 | +3.235370% | 180.42 / 155.16 / 160.18 |
| XRPUSDT | trade_spot | 2025-10-10 21:19:00 | -12.048797% | 1.7952 / 1.5789 / 1.5877 |
| XRPUSDT | mark_spot | 2025-10-10 21:19:00 | -11.558601% | 1.7952 / 1.5789 / 1.5877 |
| XRPUSDT | mark_trade | 2025-10-10 21:25:00 | -2.950074% | 1.8905 / 1.8456 / 1.79115344 |
| LINKUSDT | trade_spot | 2025-10-10 21:20:00 | -5.746753% | 9.24 / 8.709 / 8.704 |
| LINKUSDT | mark_spot | 2025-10-10 21:20:00 | -5.800866% | 9.24 / 8.709 / 8.704 |
| LINKUSDT | mark_trade | 2026-08-22 05:10:00 | +6.971673% | 11.191 / 10.934 / 11.69628277 |
| ADAUSDT | trade_spot | 2025-10-10 21:20:00 | -4.418364% | 0.2897 / 0.2769 / 0.2758 |
| ADAUSDT | mark_spot | 2025-10-10 21:20:00 | -4.798067% | 0.2897 / 0.2769 / 0.2758 |
| ADAUSDT | mark_trade | 2026-08-22 05:10:00 | +2.809195% | 0.2147 / 0.2149 / 0.22093696 |

**LINK Aug 22 05:10 is the full-year largest LINK mark/trade gap:** spot 11.191, perpetual trade 10.934, mark 11.69628277. Mark is +6.971673% versus perpetual trade and +4.515081% versus spot, while perpetual trade is −2.296488% versus spot. ADA at that minute has mark +2.809195% versus trade; that is also its largest full-year mark/trade gap. These differences can affect liquidation and forced-close accounting even with matched base quantities. They must remain in the raw study; do not silently replace trade prices with marks or delete the candles.

BTC’s largest perpetual/spot discrepancy occurs **2026-08-19 15:27**: spot 69,052.48, perpetual 70,307.1, mark 69,427.36300822 (+1.816908% trade/spot). This precedes the rally and is another stress point for execution assumptions.

## P&L concentration in existing price-study exports

Episode attribution compares the final snapshot before Aug 19 00:00 to the final snapshot before Aug 23 00:00. Holdout begins July 5; all families start at $100,000. Episode and outside-episode increments add exactly to final P&L. This is **ledger attribution**, not a rerun that removes days or changes signals/positions; those counterfactuals would require a separately declared experiment.

| Family | Equity before episode | Equity after episode | Episode P&L | Total holdout P&L | Outside episode P&L |
|---|---:|---:|---:|---:|---:|
| btc_lead_momentum | $90,124.22 | $94,610.02 | $4,485.79 | $-11,934.19 | $-16,419.98 |
| btc_lead_reversal | $100,000.00 | $99,160.86 | $-839.14 | $-951.68 | $-112.54 |
| donchian | $97,614.58 | $113,336.46 | $15,721.89 | $7,492.69 | $-8,229.20 |
| funding_contrarian | $97,823.37 | $97,823.37 | $0.00 | $-4,054.79 | $-4,054.79 |
| mean_reversion | $95,478.84 | $95,387.71 | $-91.13 | $-8,604.54 | $-8,513.41 |
| trend | $87,006.13 | $104,193.13 | $17,187.00 | $746.60 | $-16,440.40 |
| trend_pullback | $93,545.87 | $94,228.20 | $682.34 | $-10,786.52 | $-11,468.85 |
| volatility_breakout | $84,704.14 | $90,044.32 | $5,340.18 | $-21,103.29 | $-26,443.47 |

Donchian peaks at $126,855.71 and trend at $119,205.54, both Aug 22 04:44. Their respective gains from the pre-episode baseline to that peak are $29,241.13 and $32,199.41. Through Aug 22 close the episode contributes **209.83%** of Donchian’s eventual total profit and **2,301.37%** of trend’s: losses elsewhere offset it. A net-positive result is therefore not evidence of a durable effect across regimes. Carry results have not been attributed here; this report supplies the timestamps and basis stress points for that separate audit.

## Thin minutes, volume and minimum notional

| Symbol | Spot zero-volume minutes | Spot one-trade minutes | Smallest positive spot minute quote volume, USDT | Perp zero-volume / one-trade minutes |
|---|---:|---:|---:|---|
| BTCUSDT | 0 | 0 | 3063.2387769 | 0 / 0 |
| ETHUSDT | 0 | 0 | 691.974901 | 0 / 0 |
| DOGEUSDT | 12 | 33 | 1.25802 | 0 / 0 |
| PEPEUSDT | 2427 | 6969 | 0.9944163 | 0 / 0 |
| SOLUSDT | 0 | 0 | 287.59496 | 0 / 0 |
| XRPUSDT | 0 | 0 | 58.4647 | 0 / 0 |
| LINKUSDT | 2806 | 6566 | 4.88 | 0 / 1 |
| ADAUSDT | 793 | 1737 | 4.98012 | 0 / 0 |

A complete minute grid includes empty/stale candles. Zero-volume minutes offer no modeled volume capacity and must not receive fills. One-trade minutes can have unrepresentative closes; the focus August crash candles have many thousands of trades instead. The positive aggregate quote volumes under current minimum notional in some quiet spot minutes are not, by themselves, proof of bad data: exchangeInfo is a current snapshot, and candle totals are not historical order acceptance records or order-level partial-fill metadata. Do not “repair” those candles using current rules.

Base volume is coin units for spot and source base units for perpetuals; 1000PEPE units must be converted consistently when comparing liquidity or hedges. Mark candles have no executable trade volume. Minute volume cannot establish queue position, spread, whether both carry legs filled together, or available capacity precisely at an opening price.

## Source integrity recheck and its limits

For every symbol, the August monthly **spot klines, perpetual klines, and perpetual markPriceKlines** archive was read from the pinned local manifest path. SHA-256 was recomputed and matched its stored officially verified checksum for all **24** files. The exact raw Aug 22 05:10 candle open/close (and trade high/low) was compared against the corresponding normalized Parquet record: all matched. Spot raw timestamps are microseconds, futures milliseconds; normalization used the correct units. This verifies neither an independent market nor executable prices, but rules out local decoding/unit conversion corruption for the questioned minute.

Exact source URLs and SHA-256 values follow. Broader source metadata, original checksum URLs, and all other archives remain in each symbol’s `source_manifest.json`; no source files were rewritten.

| Symbol | Stream | Official August archive | Recomputed SHA-256 |
|---|---|---|---|
| BTCUSDT | spot | [archive](https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1m/BTCUSDT-1m-2026-08.zip) | `acab442e02745177063031d402929703ae983715010064b40cf811c4beb843d4` |
| BTCUSDT | perp | [archive](https://data.binance.vision/data/futures/um/monthly/klines/BTCUSDT/1m/BTCUSDT-1m-2026-08.zip) | `adfd0846ea580681aeb18a6bdf06660dcfcc1a7b6819ea2eecfc3c53240ec67a` |
| BTCUSDT | mark | [archive](https://data.binance.vision/data/futures/um/monthly/markPriceKlines/BTCUSDT/1m/BTCUSDT-1m-2026-08.zip) | `3bd0556d903ce14f833ed58c78fd8d3309bc1a3804bb401c9fa2dd9d902f2c37` |
| ETHUSDT | spot | [archive](https://data.binance.vision/data/spot/monthly/klines/ETHUSDT/1m/ETHUSDT-1m-2026-08.zip) | `f2f2fe8da85467fb8ec8185e07f16f3af9f4ebcb266633ba494e76ac73c40c0c` |
| ETHUSDT | perp | [archive](https://data.binance.vision/data/futures/um/monthly/klines/ETHUSDT/1m/ETHUSDT-1m-2026-08.zip) | `038b412935c3349e95b4abe3e9cec8a7fd521d16ce73fff3c2f92d605b252b9e` |
| ETHUSDT | mark | [archive](https://data.binance.vision/data/futures/um/monthly/markPriceKlines/ETHUSDT/1m/ETHUSDT-1m-2026-08.zip) | `d00934bc9bef31b683c5d689b5812d1397085eed11eff8dcb4babd80dbf0870b` |
| DOGEUSDT | spot | [archive](https://data.binance.vision/data/spot/monthly/klines/DOGEUSDT/1m/DOGEUSDT-1m-2026-08.zip) | `ac6c9f0ecd41f903dab63c15076ed5c981b39021300d2a61d6b414312ac59a4b` |
| DOGEUSDT | perp | [archive](https://data.binance.vision/data/futures/um/monthly/klines/DOGEUSDT/1m/DOGEUSDT-1m-2026-08.zip) | `bce45b036618e8d7d1fc370de004813e7d055e807657fabd730833fe77b63739` |
| DOGEUSDT | mark | [archive](https://data.binance.vision/data/futures/um/monthly/markPriceKlines/DOGEUSDT/1m/DOGEUSDT-1m-2026-08.zip) | `822af9ad69b332d4061b96f6fa3584d41043df7597da023b4949c3d6d2270cb9` |
| PEPEUSDT | spot | [archive](https://data.binance.vision/data/spot/monthly/klines/PEPEUSDT/1m/PEPEUSDT-1m-2026-08.zip) | `04170efdac22319119234bb90c0cc31efb95ec116b40319122feb7cc6f59966c` |
| PEPEUSDT | perp | [archive](https://data.binance.vision/data/futures/um/monthly/klines/1000PEPEUSDT/1m/1000PEPEUSDT-1m-2026-08.zip) | `25339b8345ac6a97bb56ee1474271a80925c252d9abb1fb99a5bc0cf576edab4` |
| PEPEUSDT | mark | [archive](https://data.binance.vision/data/futures/um/monthly/markPriceKlines/1000PEPEUSDT/1m/1000PEPEUSDT-1m-2026-08.zip) | `55dc0a873c5ebe7d4fad848e6459cde2e587fb47142474a8fcc3eff654804e0d` |
| SOLUSDT | spot | [archive](https://data.binance.vision/data/spot/monthly/klines/SOLUSDT/1m/SOLUSDT-1m-2026-08.zip) | `138412edb2c86df6109e0800b7b7399c6f7d2b4483d0e35ddf5921e70c0d08b6` |
| SOLUSDT | perp | [archive](https://data.binance.vision/data/futures/um/monthly/klines/SOLUSDT/1m/SOLUSDT-1m-2026-08.zip) | `0d895f66c4c07969845decf7d8e8752b0d8cb5409ca737b7b48c8751d4fd6f1f` |
| SOLUSDT | mark | [archive](https://data.binance.vision/data/futures/um/monthly/markPriceKlines/SOLUSDT/1m/SOLUSDT-1m-2026-08.zip) | `77bf9fa1ec5f8c95f313c1197b276f29eb61183abbfa31dc1843ff3bf6791746` |
| XRPUSDT | spot | [archive](https://data.binance.vision/data/spot/monthly/klines/XRPUSDT/1m/XRPUSDT-1m-2026-08.zip) | `c2d64e7fccc79a915659e4453b6423f49d9fbec2cf3ce8b4fcb33852c2c1f5cf` |
| XRPUSDT | perp | [archive](https://data.binance.vision/data/futures/um/monthly/klines/XRPUSDT/1m/XRPUSDT-1m-2026-08.zip) | `e4108def774c3daf34c1639d0a0a0ad5a4addc35df4cf927b493fc887c242854` |
| XRPUSDT | mark | [archive](https://data.binance.vision/data/futures/um/monthly/markPriceKlines/XRPUSDT/1m/XRPUSDT-1m-2026-08.zip) | `39f5c1301cae80535d0a4f460431de4207762199fa1446960050ac53d29bcbd8` |
| LINKUSDT | spot | [archive](https://data.binance.vision/data/spot/monthly/klines/LINKUSDT/1m/LINKUSDT-1m-2026-08.zip) | `c7a1e12faf1c61e3846432d3570fa2eb57c8ce8b711209444e854245cf43e85a` |
| LINKUSDT | perp | [archive](https://data.binance.vision/data/futures/um/monthly/klines/LINKUSDT/1m/LINKUSDT-1m-2026-08.zip) | `da20c8e69171095a89b8b7ab9c1b21394d2ab55d44009ef71189e9d9b9cf0282` |
| LINKUSDT | mark | [archive](https://data.binance.vision/data/futures/um/monthly/markPriceKlines/LINKUSDT/1m/LINKUSDT-1m-2026-08.zip) | `fa9c454e2506813d549305857f0c68daeed3bcfded83b70f80d3c6b994ad6374` |
| ADAUSDT | spot | [archive](https://data.binance.vision/data/spot/monthly/klines/ADAUSDT/1m/ADAUSDT-1m-2026-08.zip) | `03e8cf5a9874442e2fd9981cc60588c0beed6ed8b47ff657c3ec6c397d8bb93b` |
| ADAUSDT | perp | [archive](https://data.binance.vision/data/futures/um/monthly/klines/ADAUSDT/1m/ADAUSDT-1m-2026-08.zip) | `639520f80d6ffcf52a0e77657685c3c0541bd878095ddf24ac77edaee17710ea` |
| ADAUSDT | mark | [archive](https://data.binance.vision/data/futures/um/monthly/markPriceKlines/ADAUSDT/1m/ADAUSDT-1m-2026-08.zip) | `54b9f8be74e9b5741d8d41a436931aa051cfcdf1624fc01dfa81cd9ae7275003` |

## Interpretation and next validation

Keep the immutable results and label them as an exploratory, episode-concentrated holdout observation. Official checksums support authenticity of the downloaded bytes, not robustness, market representativeness or realizability. Independent venue candles and ideally time-synchronized trade/L2 observations should corroborate the August and October dislocations before making execution or profitability claims. Historical symbol/rule records would be required to establish or reject an actual corporate/token event; no such claim follows from current exchangeInfo.

For carry, disclose P&L, fills, liquidation/forced-close events and residual hedge exposure around Aug 19 15:27, Aug 22 05:09–05:16, and Oct 10 21:18–21:29. Mark valuation must remain distinct from trade execution and pooled isolated-account equity must include liquidated-account losses. Report episode concentration and sensitivity as additional diagnostics without retrospectively changing the frozen selection or calling an already-viewed holdout a new untouched test.

## Independent venue corroboration: Bybit, one day and two assets

Added 2026-10-06. The exact **2026-08-22** LINKUSDT and SOLUSDT daily files were found in the official [LINK listing](https://public.bybit.com/trading/LINKUSDT/) and [SOL listing](https://public.bybit.com/trading/SOLUSDT/) before fetching them. No earlier price data or additional assets were fetched. Bybit’s [official API documentation](https://bybit-exchange.github.io/docs/v5/market/recent-trade) directs historical-trade users to its archive website. The archive uses fractional Unix **seconds**, whereas the recent-trades API documents milliseconds; the parser follows the actual archive format.

The products are **Bybit USDT-settled linear perpetuals**, not spot: current official `instruments-info?category=linear&symbol=...` responses identify `LinearPerpetual`, base LINK or SOL, quote and settlement USDT. These responses are preserved as current metadata, not historical rule snapshots. In every fetched trade, `homeNotional == size` and `foreignNotional == size * price` within numerical tolerance. The volume table therefore uses LINK/SOL base units and USDT quote units. Binance and Bybit volume represent different venues and product matching rules; their totals are not interchangeable execution depth.

| Symbol | Official one-day file | Compressed bytes | Local SHA-256 of raw gzip |
|---|---|---:|---|
| LINKUSDT | [raw trades](https://public.bybit.com/trading/LINKUSDT/LINKUSDT2026-08-22.csv.gz) | 29,326,656 | `577df99422e5ca8530511022f14a41ffbdcce2ad35855647c3990c8346b4afc5` |
| SOLUSDT | [raw trades](https://public.bybit.com/trading/SOLUSDT/SOLUSDT2026-08-22.csv.gz) | 54,154,991 | `a7e2a6fe2abde6a65b0fd305d915d55de45a7cafc405653a4b0c35437aaf4bcb` |

These SHA-256 values pin the actual HTTP response bytes; a Bybit publisher checksum file was not asserted or fetched. The saved multipart ETag is not treated as an integrity checksum. Listings, original gzip files, current instrument responses, HTTP source headers, source/derived hashes, minute reconstructions and the comparison CSV are copied under `data_cache/outlier-validation`.

| Symbol | Raw trade rows | First / last trade UTC on Aug 22 | Actual occupied UTC minutes | Timestamp order failures | Duplicate trade-ID hashes |
|---|---:|---|---:|---:|---:|
| LINKUSDT | 818,497 | 00:00:00.034400 / 23:59:56.882700 | 1440 | 0 | 0 |
| SOLUSDT | 1,608,427 | 00:00:00.122200 / 23:59:58.617000 | 1440 | 0 | 0 |

Every one of the 1,440 UTC minutes contains actual trades; no missing minutes were filled. Raw timestamps were parsed as exact seconds plus fractional nanoseconds, avoiding floating-point minute-boundary rounding. Trade order is monotonic and same-timestamp ties preserve archive order. OHLC is first/max/min/last actual trade within `[minute_start, minute_start + 60s)`, volumes are sums, counts are raw trade rows. All `RPI` flags are zero in these two daily files. ID uniqueness was checked using pandas 64-bit hashes, not a formal exchange sequence completeness guarantee. The day’s first close-to-close minute return is undefined rather than borrowing the previous day.

### Comparison around the questioned minutes

| Symbol | UTC Aug 22 minute | Bybit low / high / close | Bybit close return | Binance spot close / return | Binance perp close / return | Binance mark close | Bybit trades |
|---|---|---|---:|---|---|---:|---:|
| LINKUSDT | 05:08:00 | 12.163 / 12.342 / 12.207 | -1.085812% | 12.208 / -1.085724% | 12.214 / -1.053143% | 12.193 | 5,710 |
| LINKUSDT | 05:09:00 | 12.008 / 12.243 / 12.026 | -1.482756% | 12.031 / -1.449869% | 12.028 / -1.522843% | 12.074 | 8,947 |
| LINKUSDT | 05:10:00 | 10.751 / 12.048 / 11.069 | -7.957758% | 11.191 / -6.981963% | 10.934 / -9.095444% | 11.69628277 | 42,105 |
| LINKUSDT | 05:11:00 | 10.908 / 11.271 / 11.201 | +1.192520% | 11.23 / +0.348494% | 11.195 / +2.387050% | 11.19844019 | 20,337 |
| LINKUSDT | 05:12:00 | 11.158 / 11.597 / 11.538 | +3.008660% | 11.557 / +2.911843% | 11.547 / +3.144261% | 11.511 | 8,367 |
| LINKUSDT | 05:13:00 | 11.492 / 11.64 / 11.618 | +0.693361% | 11.637 / +0.692221% | 11.634 / +0.753442% | 11.61142807 | 4,612 |
| LINKUSDT | 05:14:00 | 11.601 / 11.736 / 11.687 | +0.593906% | 11.691 / +0.464037% | 11.697 / +0.541516% | 11.688 | 5,398 |
| LINKUSDT | 05:15:00 | 11.673 / 11.82 / 11.722 | +0.299478% | 11.728 / +0.316483% | 11.729 / +0.273574% | 11.77453028 | 5,330 |
| LINKUSDT | 05:16:00 | 11.352 / 11.724 / 11.512 | -1.791503% | 11.514 / -1.824693% | 11.566 / -1.389718% | 11.502 | 10,293 |
| SOLUSDT | 05:08:00 | 97.52 / 98.59 / 97.56 | -1.044731% | 97.54 / -1.044943% | 97.52 / -1.055195% | 97.58089969 | 10,422 |
| SOLUSDT | 05:09:00 | 95.38 / 97.82 / 95.5 | -2.111521% | 95.53 / -2.060693% | 95.48 / -2.091879% | 96.15616391 | 23,416 |
| SOLUSDT | 05:10:00 | 89.22 / 95.76 / 89.87 | -5.895288% | 90.27 / -5.506124% | 90 / -5.739422% | 90.82307066 | 84,590 |
| SOLUSDT | 05:11:00 | 87.64 / 90.44 / 90.31 | +0.489596% | 90.49 / +0.243713% | 90.79 / +0.877778% | 89.21139829 | 54,164 |
| SOLUSDT | 05:12:00 | 89.94 / 93.28 / 93.13 | +3.122578% | 93.18 / +2.972704% | 93.17 / +2.621434% | 93.06924153 | 25,212 |
| SOLUSDT | 05:13:00 | 92.98 / 93.75 / 93.67 | +0.579835% | 93.73 / +0.590255% | 93.71 / +0.579586% | 93.66 | 15,561 |
| SOLUSDT | 05:14:00 | 93.19 / 94.49 / 93.27 | -0.427031% | 93.33 / -0.426758% | 93.33 / -0.405506% | 93.75756489 | 11,719 |
| SOLUSDT | 05:15:00 | 93.28 / 94.49 / 94.07 | +0.857725% | 94.14 / +0.867888% | 94.15 / +0.878603% | 94.31938925 | 9,447 |
| SOLUSDT | 05:16:00 | 90.94 / 94.15 / 92.04 | -2.157967% | 92.1 / -2.166985% | 92.1 / -2.177377% | 91.86081078 | 27,922 |

At **05:10 UTC**, LINK falls **12.026 → 11.069 (−7.957758%)** on Bybit across **42,105 trades**, versus Binance spot −6.981963% and perpetual −9.095444%. Bybit’s low is **10.751**; its minute base volume is **791,982.1 LINK**, quote volume **9,107,404.80 USDT**. SOL falls **95.50 → 89.87 (−5.895288%)** across **84,590 trades**, versus Binance spot −5.506124% and perpetual −5.739422%; Bybit low **89.22**, base volume **1,303,469.3 SOL**, quote volume **120,329,505.17 USDT**. Quote totals are rounded here; exact sums remain in the exported frames.

**Conclusion: the abrupt LINK/SOL selloff is independently corroborated on Bybit and cannot reasonably be characterized solely as an isolated Binance candle glitch.** This validates the existence and approximate scale of a two-market shock at the questioned minute, not every Binance wick, all eight markets, the preceding multi-day rally, or paired execution assumptions.

**The Binance LINK mark discrepancy remains separate.** At 05:10, Binance mark 11.69628277 is **+6.971673%** versus Binance perpetual trade close 10.934 and **+5.667023%** versus Bybit perpetual trade close 11.069. The independent trade prices corroborate the broad decline; they do not establish that a mark lag/filter is erroneous or that the mark was ever an executable quote. Different last-trade timestamps, product bases, mark filtering, and venue microstructure can produce a genuine discrepancy in stress. No Bybit historical mark feed was collected, so this check cannot certify the mark-based liquidation path.

The episode-concentration conclusion above is unchanged. A genuine market shock can still dominate a strategy’s backtest profit. The independent check strengthens price-event provenance while leaving execution robustness, portfolio liquidation conservation and economic stability as separate requirements.

Versioned compact evidence is available in [minute_outlier_evidence](minute_outlier_evidence/README.md), including the comparison CSV, source/validation manifests and current instrument responses. Reproduce the reconstruction with `.venv/bin/python examples/minute_research/validate_outlier.py` using the [versioned script](../examples/minute_research/validate_outlier.py). The evidence README gives exact official manual download URLs. The script verifies pinned raw and Binance input hashes, performs no downloads, interpolation or trading, and writes only derived review artifacts to the ignored cache (or `--out`).
