# Leading-factor literature and causal research hypotheses

Research checked **6 October 2026**. This review uses primary papers/publisher pages, NBER, IMF and author manuscripts discoverable through scholarly internet search. It distinguishes reported empirical findings from our new hypotheses. No paper's published return is a result for this repository, DOGE, PEPE, or the requested last-year window. Abstract-level findings are identified where full methodology was not inspected. The implementation does not inspect historical strategy returns or choose parameters.

**Retrospective timing limitation:** the requested one-year sample starts in October 2025. Some research reviewed here was published during that period or revised in September 2026. A frozen code/config hash before opening our numerical holdout protects against this experiment's direct tuning, but it is not prospective preregistration before the historical year began. Literature selection and broader prior knowledge remain forms of retrospective influence. A genuinely prospective test needs newly arriving data after the freeze.

## What the primary evidence supports

| Primary source | Status and inspected material | Reported finding | Appropriate inference and limits |
|---|---|---|---|
| Kurihara & Matsumoto, **Price Transmission from Bitcoin to Altcoins: High-Frequency Evidence and Implications for Trading Strategy** (10 March 2026), [publisher / DOI](https://link.springer.com/article/10.1007/s10690-026-09589-z) | Peer-reviewed, open-access; methods/results inspected | Binance one-minute data show delayed responses in selected low-liquidity small-cap coins; ETH/LTC largely co-move contemporaneously. A LightGBM state-change strategy includes fees and training-only threshold search. | Supports testing BTC-leading features. Selected trading coins include QKC/GNO/PIVX/CITY/BIFI, not a demonstrated DOGE/PEPE rule. Effects mostly occur at one minute and fade at further lags. Candle execution and fees do not establish queue/impact realism. |
| Liu & Tsyvinski, **Risks and Returns of Cryptocurrency**, [NBER WP24877](https://www.nber.org/papers/w24877) (2018; published RFS 2021) | Peer-reviewed published version; NBER abstract inspected | Historical crypto-specific time-series momentum and investor attention forecast returns; traditional factor exposures differ. | Motivates crypto trend/attention hypotheses. It does not validate a minute-horizon BTC→DOGE lead or the current year's regime. |
| Liu, Tsyvinski & Wu, **Common Risk Factors in Cryptocurrency**, [NBER WP25882](https://www.nber.org/papers/w25882) (2019; published Journal of Finance 2022) | Peer-reviewed published version; NBER abstract inspected | Market, size and momentum account for crypto cross-sectional expected returns. | Use market-beta and momentum controls before calling an altcoin return “alpha”; the finding is not an executable contemporary minute rule. |
| **Fundamentals of Perpetual Futures**, [arXiv:2212.06888](https://arxiv.org/abs/2212.06888) (first 2022, latest inspected revision 17 September 2026) | Author manuscript; abstract/version history inspected | Derives perpetual valuation with funding and cost-dependent arbitrage bounds; documents price deviations and an implied arbitrage strategy. | Funding/basis are economically meaningful. Hedged arbitrage and unhedged long funding-contrarian positions have different risks; the latter is our hypothesis. |
| **BitMEX Funding Correlation with Bitcoin Exchange Rate**, [arXiv:1912.03270](https://arxiv.org/abs/1912.03270) (2019) | Author manuscript; abstract inspected | Examines correlation between inverse-perpetual funding and Bitcoin price behavior. | Correlation motivates examination, not a causally identified current linear-contract profit rule. Its old venue/contract/sample are different. |
| Iyer, **Cryptic Connections: Spillovers between Crypto and Equity Markets**, [IMF Global Financial Stability Note 2022/01](https://www.elibrary.imf.org/view/journals/065/2022/001/065.2022.issue-001-en.xml) | Institutional research; abstract and sample description inspected | Crypto/equity interconnectedness increased after 2020 in daily return/volatility spillovers. | Macro/equity controls are worthwhile. Co-movement does not establish that QQQ's last return predicts a subsequent crypto return, particularly overnight/weekends. |
| **The Crypto Cycle and US Monetary Policy**, [IMF WP2023/163](https://www.elibrary.imf.org/view/journals/001/2023/163/article-A001-en.xml) | Institutional working paper; abstract/sample discussion inspected | Studies a common crypto cycle and its relationship to US monetary policy. | Monetary conditions can be risk-state controls, but release-time surprise inputs must be available before a trade. No implemented monetary predictor is claimed. |
| Pinchuk, **Bitcoin Does Not Hedge Inflation**, [arXiv:2301.10117](https://arxiv.org/abs/2301.10117) (2023) | Author manuscript; abstract inspected | Reports a negative Bitcoin response to inflation surprise, with alternative economic interpretation. | A monthly CPI level is different from an announcement surprise. Direction and magnitude are sample dependent; do not encode “higher inflation means buy Bitcoin”. |
| Haritha GB & Sahana N.B., **Cryptocurrency Price Prediction using Twitter Sentiment Analysis**, [arXiv:2303.09397](https://arxiv.org/abs/2303.09397) (2023), [conference DOI](https://doi.org/10.5121/csit.2023.130302) | Conference manuscript; abstract inspected | Combines sentiment/attention measures and historical prices in forecasting models; reports forecast error. | Demonstrates a research approach, not net trading profitability. Low price-level prediction error is not evidence of incremental return prediction after costs. |

The most directly relevant minute paper supports selected lag effects, while also documenting contemporaneous responses in more liquid assets. The economic inference is to test, rather than assume, leadership in each instrument and venue. Granger predictability means incremental forecasting conditional on chosen variables/lags; it is not proof of structural causality or monetizable execution. Negative results under fees/latency are meaningful.

## Three frozen executable hypotheses

The new module is `aster/strategies/leading_factors.py`. These deliberately simple rules avoid reproducing published ML models, adopting paper-reported winners, or fitting coefficients on the evaluation period. They are **long/cash**, not promised successful strategies, and are additional to the five price-only families.

| Family | Fixed entry idea | Exit and turnover control | What is being tested |
|---|---|---|---|
| `btc_lead_momentum` | Observed BTC one-hour return >0.2%, BTC above its 24-hour mean, target one-hour return at least 0.2 percentage points behind BTC; target not below its six-hour exit mean | Enter only on 30-minute boundaries; exit when observed BTC return turns negative, target falls below its mean, source is stale, or six-hour maximum hold; one-hour cooldown | A slower, cost-aware catch-up continuation hypothesis. This is not a replication of the paper's one-minute LightGBM effect. |
| `btc_lead_reversal` | Observed BTC one-hour loss worse than1.5%, target worse than2%, subsequently observed positive BTC15-minute rebound and target above its15-minute mean | Enter on15-minute boundaries; exit renewed BTC rebound loss below−0.5%, target below its mean, stale source or four-hour maximum hold; two-hour cooldown | Whether broad selloffs plus confirmed rebound predict relief in overshooting targets. Reversal direction is our hypothesis, not a proved paper finding. |
| `funding_contrarian` | Last **published realized settlement** rate at or below−1bp; target six-hour return above−3% and close above its one-hour mean | Enter on hourly boundaries; exit nonnegative published funding, six-hour loss below−5%, stale rate or24-hour maximum hold; two-hour cooldown | Negative funding as crowded-short sentiment with rebound confirmation. On spot this does not receive a funding payment; on perpetuals actual ledger cashflows still apply independently. |

`scale=0.8/1.0/1.2` changes lookback, hold and cooldown durations; entry schedules, external observation lag, stale tolerances and economic thresholds stay fixed. Neighbor sensitivity is a robustness check, not permission to choose the best holdout scale. The BTC sleeve in the two BTC-leading families remains **cash**, so the report cannot mistake Bitcoin predicting itself for cross-asset leadership. Root's portfolio runner determines allocations and executes only direction changes, holding entered base quantity between them.

## Availability contract and supported data

```python
from aster.strategies.leading_factors import build_factor_signals, FACTOR_FAMILIES

signals = build_factor_signals(
    target_minute_bars,
    'btc_lead_momentum',
    leader_bars=btc_minute_bars,
    scale=1.0,
)
```

Each bar frame contains one instrument, timezone-aware interval-start `timestamp`, positive finite `close`, and `duration_seconds=60`. Output is binary int8 intent indexed by UTC **end/available time**. Completed leader returns and trend features are calculated on continuous BTC history, then matched backward as of `BTC end + 1 minute`. No feature from a later leader bar is available earlier. BTC identity must be `BTCUSDT`; an ETH frame cannot silently stand in for it. Stale leader features older than two minutes after their availability cause cash intent. Returns/means reset after source gaps rather than interpreting a missing interval as a minute.

Funding accepts a single matched instrument and `funding_rate` plus `timestamp` (settlement time) or `available_at` (observation/receipt time). Numeric timestamps are interpreted explicitly as milliseconds; textual times must be timezone aware. **If both exist, `available_at` wins and must not precede settlement.** The configured additional one-minute lag is applied after that actual availability. This prevents early exposure when a rate was settled but delivered later. With only settlement time, availability is approximated as settlement+one minute and must be labelled as an assumption.

The downloader's factor table can include `spot_instrument_id` and a different contract ticker/source ID. An explicit spot mapping must match the target and is authoritative for mappings such as `1000PEPEUSDT` futures to `PEPEUSDT` spot. Without it, legacy instrument suffixes must match. Never mix rates across coins. The latest published rate is held for at most12hours; this is a stale-data threshold, not a synthesized funding schedule or forecast. A missing required funding/leader input raises rather than inventing observations.

Signals cannot collect the just-published funding settlement by opening afterward. Rate information and future funding cashflows are separate. Missing/stale features flatten intent; the execution engine's next eligible observation still controls when the actual exit fills. The module does not interpolate sub-minute reactions, publish perfect forecasts or modify portfolio equity.

## QQQ, inflation and X: excluded pending point-in-time evidence

These potential controls are recorded as future hypotheses, not implemented inputs. Passing `qqq` to the current builder raises an explicit unsupported-input error.

- **QQQ/risk sentiment:** obtain exchange timestamps and verified delivery time, correct corporate actions and historical data versions. Compute returns only from completed sessions/bars. Reindex crypto with backward as-of matching plus a stale-age policy; do not fill a holiday/weekend with Monday's eventual close. ETF market hours, daylight saving and overnight information mean “previous row” is not “previous minute”. Risk co-movement can be contemporaneous or jointly news-driven.
- **Inflation/macroeconomic surprise:** use original release vintage, official release clock, contemporaneous consensus known before release, and realistic ingestion latency. Surprise is actual minus that consensus. Today's revised CPI history indexed to its reference month would leak information. Pre-release blackout/risk controls are a separate hypothesis requiring a historical calendar available at the time.
- **X/Twitter sentiment:** preserve post creation time, first retrieval time, deletion/edit state, sampled universe and model/version. Use features available at first observation, not today's likes/reposts/follower counts attached retrospectively. Freeze the classifier before evaluation; later-trained language models may encode events from the backtest year. Exclude bots/spam using rules known then. Selection and availability limits of paid historical access must be disclosed.

No QQQ, CPI-consensus/vintage or X point-in-time dataset was verified in this task. Scraped retrospective sentiment or a revised macro series must not be silently admitted to improve results.

## Evaluation required before calling a leading factor useful

1. Keep the last-year-only source manifests, bar checksums, factor receipt/mapping files, code hash and train/validation/holdout boundary fixed. Adding three factors increases the tested family universe to eight; multiple-testing adjustments must reflect all eight and any instrument/lag searches actually performed.
2. Measure incremental forecasting against own lagged return, market beta and simple trend baselines using only training data. For future fitted methods, prespecify lag1–3 minute VAR or regularized regression, use rolling/purged temporal folds and never a random time split. Fitted lag/feature selection is distinct from this fixed-rule test.
3. Evaluate net executed-price returns under taker/maker classification, observed liquidity proxy, fees, slippage, funding for derivatives, and positive latency. One-minute statistical effects may vanish before a delayed order can execute. An asset-level screen is not a cross-exchange arbitrage guarantee.
4. Report all eight families, including zero-return BTC cash sleeves, failed strategies and missing-factor periods. Do not select only the winning DOGE/PEPE combination from dozens of trials. Compare untouched holdout, training-only parameter selection, scale neighbors, doubled fees/impact and delayed fills.
5. Use dependent daily/block uncertainty, not IID minute observations. The seven-day-block percentile bootstrap is descriptive. For eight-family Bonferroni at family-wise5%, a two-sided interval uses0.3125% and99.6875% quantiles (99.375% coverage), rather than the earlier five-family99% label. Instrument selections may require further correction.
6. Independent synthetic checks must alter future BTC/target/funding values and verify identical earlier outputs, cut at partial availability boundaries, delay publication, introduce source gaps, test explicit token mappings and reject a wrong leader. The engine still requires its separate event/accounting audit.

A factor that fails these checks should remain a documented negative result. The one-year window alone cannot establish stable efficacy across changing listings, liquidity regimes and sentiment infrastructure. A prospective continuation after the experiment freeze has the highest value for distinguishing retrospective fit from a durable effect.

## Subsequent external-factor experiment

The dataset limitation above describes the original directional cohort. A later
exploratory extension collected 250 actual QQQ sessions, eleven original CPI
release records and authentic aggressive trade volume, with explicit timing and
provenance limits. It does not introduce CPI consensus surprises or historical
X sentiment. See the [five fixed definitions](../examples/external_factors/proposed_protocol.md)
and [independent audit](external_factor_audit.md). QQQ daily risk transmission,
CPI acceleration, funding crowding, trade/spot premium and taker-flow drift are
candidate mechanisms; the papers motivate testing them and do not establish
these exact rules as profitable on DOGE, PEPE or this historical year.


## Subsequent factor-residual experiment

[Avellaneda and Lee's original statistical-arbitrage paper](https://math.nyu.edu/inmemoriam/avellaneda/AvellanedaLeeStatArb20090616.pdf)
motivates testing mean reversion of factor-adjusted price residuals. Its equity
setting does not establish a crypto edge. Our separate fixed BTC/ETH experiment
used disjoint return-beta and residual-calibration blocks, actual shared hedge
legs and conditional stationarity checks. The protocol was committed before
fitting this candidate, although the year had already been examined.

All six targets failed its fixed admission rules. Five actual historical runs
therefore produced no trades or returns. See the [full diagnostics and audit](residual_convergence_results/README.md).
The cumulative result remains **0/25 historical hurdle passes**; neither a paper
nor observed correlation supplies proof of a tradeable leading factor.


## Next mechanism under feasibility review: cross-venue funding

[BIS Working Paper 1087, Crypto carry](https://www.bis.org/publications/working-paper-1087-crypto-carry)
connects large carry with investor demand and limited arbitrage capital, while
explicitly describing margin and liquidation risks.
[Fundamentals of Perpetual Futures](https://arxiv.org/abs/2212.06888) derives
pricing bounds with trading costs; its current version was revised during this
research year. Neither paper proves that our proposed Binance/Bybit rule works.
This would be retrospective hypothesis development, not a pre-year strategy.

A possible next test would hold opposite native perpetual exposures in separate
exchange wallets, using only previously settled funding as a predictor.
[Bybit's funding-history API](https://bybit-exchange.github.io/docs/v5/market/history-fund-rate)
provides settled rates and timestamps, but does not supply historical receipt
time or exact settlement mark in that response. Full-year coverage, historical
schedule changes and valuation assumptions require verification before a
backtest can be represented as faithful. This is feasibility work, not a tested
26th candidate, successful example or executable quote-arbitrage result.


## Counter-evidence checked during frozen cross-venue execution

The following additional primary-source abstracts were checked on 6 October
2026 after cross-venue source/input freezing and before inspecting that
candidate's outcomes. They do not amend its economic rules.

[Jia, Wu, Yan and Liu, *A seesaw effect in the cryptocurrency market*](https://www.sciencedirect.com/science/article/pii/S0927539823000956)
(Journal of Empirical Finance, December 2023) reports negative intraday
cross-prediction from larger to other coins, using LASSO. Only the publisher's
abstract/highlights were accessible; the full method was not reviewed. This
provides counter-evidence to a universal same-direction BTC-leading rule, not
proof that a reverse DOGE/PEPE strategy works at our execution latency/costs.

[Benigno and Rosa, *The Bitcoin–Macro Disconnect*](https://www.newyorkfed.org/research/staff_reports/sr1052.html)
(New York Fed Staff Report 1052, February 2023) reports little Bitcoin response
to monetary and macro news in its intraday study. That differs from
[Pinchuk's inflation-surprise manuscript](https://arxiv.org/abs/2301.10117),
which reports a negative inflation-surprise response. Both statements here are
abstract-level findings. Their differing results justify testing precise event
surprises, samples and data availability rather than treating inflation levels
or QQQ correlation as a fixed profitable signal. The existing CPI experiment
uses original releases without contemporaneous consensus, and consequently is
not an inflation-surprise replication.

No new cross-prediction model, sign flip, lag search or macro threshold was
selected from these sources. Historical X sentiment still requires a verified
point-in-time archive; present-day search cannot reconstruct an unbiased past
year of first-observed posts or engagement counts.


## Completed cross-venue experiment

The subsequent one-family packet was frozen at `98fe45a`, with verified inputs
recorded and uploaded at `1820b82` before its historical features and outcomes.
All seven actual runs stayed in cash. Separate independent source, causal-feature,
financial/gate and cohort-specific entry checks passed; every tested entry was
below the fixed cost filter. The best predicted carry covered 25.3% of modeled
stress roundtrip costs, while the packet required 150%. This rejects this fixed
slow-carry hypothesis under its stated model; it does not establish that all
funding or cross-venue strategies fail. The cumulative result is **0/26**.
[Full report and limits](cross_venue_results/report.html).
