# Mechanism research decision after 24 failed candidates

> This memo is a pre-correction assessment based on preserved original-engine results. The [audited corrected comparison](margin_correction_results/report.html) supersedes its derivative performance figures and still reports 0/24 complete hurdle passes. No new market-neutral strategy was tested by this memo.

2026-10-06. Read-only assessment of completed evidence and primary research. No new fit, parameter selection, signal calculation or simulation was performed. The price window remains 2025-10-05 00:00 to 2026-10-05 00:00 UTC, exclusive at the end.

**Decision:** the current candles, aggregate taker flow, marks and settled funding support one meaningful additional family: jointly executed, factor-hedged residual convergence. They do not support a credible promise of four or five robust profitable strategies. Different pairs, hedge estimators and thresholds are variants of that family. Another large parameter grid would add selection risk before resolving the missing economic mechanism. See the complementary [relative-value assessment](market_neutral_research_memo.md).

## Why flow did not survive costs

The completed taker-flow drift evaluation lost 29.633% and joint stress lost 47.792%. Baseline turnover was $25.429 million against $100,000 starting capital: 254.29 times capital, generating $12,714.55 explicit fees. Trading P&L was already negative $16,936.38 before those explicit fees; funding contributed only $17.83. The $13,702.46 slippage diagnostic is embedded in fill prices and must not be subtracted again. Median closed-trade holding time was 7,200 seconds: a minute observation clock did not mean one-minute holdings. These are attribution of the existing [completed summary](external_factor_results/summary.json), not a frictionless rerun or a new prediction test.

Aggressive buys can explain a price change that has already occurred, without predicting a profitable move after candle completion, publication lag and execution. Aggregate trade imbalance also omits limit additions, cancellations, best-quote depth and replenishment. Cont, Kukanov and Stoikov find short-interval price impact associated with *book* supply/demand imbalance, with depth affecting the relationship; their equities study does not establish delayed crypto trading alpha. Our aggregate taker volume is not that book imbalance. [Primary paper](https://arxiv.org/abs/1011.6402).

Flipping flow continuation into reversal is a related hypothesis about temporary pressure, not an independent edge demonstrated by the observed loss. Candle wicks and high volume cannot identify forced liquidations or distinguish informed trading from inventory absorption. Reducing turnover can reduce costs, but it cannot establish positive conditional gross expectancy. An ex ante cost budget and deterministic no-trade outcome belong in the next protocol; lowering modeled costs to rescue a result does not.

## What is actually different and identifiable

| Mechanism | Current data and executable test boundary | Decision |
|---|---|---|
| Hedged relative-value convergence | Native perpetual prices, marks, funding and volume permit a real multi-leg account with explicit delayed/partial fills and residual exposure. Statistical convergence remains unproven. | One plausible additional family; economic pair/proxy identities and training-only estimation rules must be declared before new numbers. |
| Liquidity provision and spread capture | Requires bid/ask quotes, depth, update sequencing, queue uncertainty, latency and adverse-selection measurement. Minute OHLC and aggregate flow do not reveal these. | Obtain suitable within-year book data first; no fabricated maker fills or assumed rebates. |
| Cross-venue dislocation or price leadership | Requires synchronized second-venue prices and tradable quotes, fees, inventory/capital constraints and leg execution. Existing Bybit evidence is a small outlier-validation sample. | Distinct mechanism, unavailable from the current one-venue year. |
| Dated-futures curve/expiry convergence | Needs dated contracts, historical terms, quotes, funding/borrow where relevant and settlement rules. Existing settled perpetual funding is not a futures curve. | Distinct but missing the required inputs. |
| Options volatility compensation | Needs actual option quotes, contract expiries and a feasible hedging account. Candle volatility alone does not establish executable option premium. | Distinct but unsupported. |
| Calendar, post-shock reversal, flow absorption proxies | Can be calculated from candles; overlap prior price/flow hypotheses and invite retrospective event selection. | Do not count as four new independent mechanisms or tune around the known August episode. |

Makarov and Schoar document crypto exchange segmentation and cross-exchange arbitrage constraints; an observed price difference is not proof of simultaneous executable profit. [Author manuscript](https://dspace.mit.edu/entities/publication/7f91bfb5-ba77-4d0e-9c79-ec75e104e6cc). Existing funding carry and premium fade have already been studied; renaming those policies does not expand economic coverage.

## Pair feasibility, including DOGE and PEPE

For equal initial dollar legs N, a full pair round trip uses four fills. Under the existing perpetual baseline assumptions (5 bps taker fee per fill; 2 bps adverse slippage for BTC/ETH and 8 bps for DOGE/PEPE):

| Pair | Modeled round-trip cost / one leg N | Cost / initial gross 2N | Joint stress / one leg N |
|---|---:|---:|---:|
| BTC/ETH | 28 bps | 14 bps | 56 bps |
| DOGE/PEPE | 52 bps | 26 bps | 104 bps |

This is fixed-notional first-order arithmetic, not a profitability estimate or verified historical bid/ask cost. Funding, rebalancing, failed-leg cleanup, participation constraints and additional liquidity deterioration can increase the hurdle. A relative-return convergence must compensate both legs' costs. Minute sampling does not require trading every minute.

BTC/ETH are interpretable broad-market peers; DOGE/PEPE have thematic similarity but no common redemption value, matched cash flows or binding relative price. Correlation does not imply cointegration, and neither relationship is guaranteed stationary. The original pairs evidence concerns US equities and a materially different market structure. [Gatev, Goetzmann and Rouwenhorst, author paper](https://repec.som.yale.edu/icfpub/publications/2573.pdf). PEPE remains native **1000PEPEUSDT** in the perpetual account: one native unit corresponds to 1,000 spot PEPE. Returns can be compared without rescaling quantities incorrectly.

Dollar neutrality differs from estimated beta neutrality; both leave jump, liquidity and nonlinear exposure. Both legs must be simulated together with actual fees/funding and isolated collateral. One leg may fill while the other remains pending. The [outlier audit](minute_data_outliers.md) documents extreme wicks and mark/trade discrepancies; a hedged price series cannot eliminate a leg's execution or liquidation exposure. Shared symbols must net consistently, and every residual position must remain marked and reported.

Maker execution is a separate data problem. Avellaneda–Stoikov explicitly models inventory and order-arrival intensity; its simulated arrivals are not an empirical fill rule for our candles. [Author paper](https://math.nyu.edu/~avellane/HighFrequencyTrading.pdf). Optimal placement research similarly depends on queues, order flow and fees. [Cont–Kukanov](https://arxiv.org/abs/1210.1625). A low touching a limit price cannot establish queue priority, available size or a rebate-eligible fill.

## Next useful work within the one-year limit

Prepare at most one residual-convergence protocol with an interpretable factor hedge, explicit failed-leg policy, fixed economic admissibility checks, unchanged realistic cost/stress assumptions and a valid no-trade outcome. Count every new specification in the cumulative search history. Pair selection, training-only hedge estimation, exposure accounting and basket-level evaluation need independent review before execution; changing leg breadth criteria needs prospective economic justification, not retrospective rescue.

If genuine liquidity provision is the intended next direction, first determine whether a complete sequenced historical book feed exists inside this same year and whether its licensing/access permits reproduction. Do not infer missing queues from candles.

The last evaluation quarter has already been inspected repeatedly. Another pass on it is exploratory historical evidence, even with bootstrap intervals; it cannot become untouched holdout evidence again. The year can support useful falsification, execution audits and a new mechanism test. Durable robustness and four or five independent successes remain unsupported.
