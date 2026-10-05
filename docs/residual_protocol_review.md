# Residual-convergence protocol review — before fitting or outcomes

> This preserves the pre-estimation design discussion. The [approved fixed packet](../examples/residual_convergence/proposed_protocol.md) resolves its alternatives. The [final independent signoff](residual_convergence_preregistration_review.md) verifies the assembled implementation before fitting.

2026-10-06. Draft for root approval; no model fit, historical signal generation, simulation, parameter search or source change has occurred. This is one exploratory 25th candidate on the repeatedly inspected year, not six independent altcoin edges. The preserved 24-candidate studies remain unchanged.

## Concrete model packet

The root draft is coherent with these prospective clarifications:

- Eight native Binance linear perpetuals share one real $100,000 account. BTC and ETH are tradable return-factor proxies; DOGE, native 1000PEPE, SOL, XRP, LINK and ADA are six potential residual exposures. No spot short/borrow or second venue is invented.
- First three months, October5–January5: use complete synchronized UTC hourly trade-close log returns and OLS with intercept plus BTC/ETH factors. One fixed regression per altcoin, no pair/factor/parameter grid. Next three months, January5–April5: coefficients stay frozen; construct cumulative residuals out of sample and estimate/test a mean-reverting hourly AR(1)/OU model. Freeze alpha, betas, equilibrium mean and equilibrium standard deviation before April5. Do not refit on validation/evaluation.
- Residual construction uses one declared January5 price anchor through October5: `x_i(t) = log(P_i(t)/P_i(anchor)) − beta_B log(P_B(t)/P_B(anchor)) − beta_E log(P_E(t)/P_E(anchor)) − alpha_i × elapsed_hours`. This reproduces cumulative hourly regression residuals while permitting minute observation. It must not reset at wallet/month boundaries or use separately centered minute regressions. Completed prices acquire an extra one-minute availability lag; all eight prices must refer to the same complete observation.
- Admissibility must be deterministic and training-only. Require finite coefficients, a numerically well-conditioned two-factor design, positive stationary OU variance, `0 < phi < 1`, hourly half-life1–24 hours and the proposed fixed-lag24/intercept-only ADF test on the disjoint training residual path. Predetermine handling of duplicate/gapped observations and nonpositive prices. Correlation or return-regression R-squared alone is not evidence of residual stationarity. No acceptable model means no trade, with explicit failed diagnostic records.
- The suggested ADF threshold0.01 is **conditional per asset**; testing six paths gives a union bound up to0.06, not a familywise0.01 guarantee. My recommendation is0.01/6 for admissibility, fixed before any fit. These tests still depend on assumptions and a short single-regime history. Do not search lags, retry another trend term or widen half-life bounds when a model fails.
- Root signal defaults: `|z| >= 2` entry, `|z| <= 0.5` exit, observed `|z| >= 4` stop, maximum48-hour holding,24-hour cooldown after a stop. Clarify whether entries are once daily00:01UTC or more often; I recommend once daily to control turnover, with exits/risk observations every eligible minute. No immediate same-callback close/reopen. Stops act through subsequent actual fills and cannot guarantee the threshold price or loss.

[Avellaneda and Lee's author manuscript](https://math.nyu.edu/inmemoriam/avellaneda/AvellanedaLeeStatArb20090616.pdf) motivates tradable factor-residual convergence and explicitly examines degradation/crisis risk. The proposed split, fixed hedge, thresholds and crypto costs are an adaptation, not a reproduction of their equity experiment. [The crypto cointegration study](https://arxiv.org/abs/2109.10662) additionally relies on quote/size execution information unavailable here. Neither paper establishes profitability for this packet.

## Position sizing and cost budget

The root's fixed total gross budget is25% of initial capital, split equally across six possible groups. For group i, `a_i = (100000 × 0.25 / 6) / (1 + |beta_B| + |beta_E|)`. At entry, side is opposite residual z. Intended native quantities are `side × a_i / P_i`, `−side × beta_B × a_i / P_B`, and `−side × beta_E × a_i / P_E`, floored to native lots. Quantities stay fixed between real group transitions; no minute notional/beta rebalancing is implied. Native1000PEPE prices/quantities stay per bundle. Net all simultaneous BTC/ETH hedge intentions centrally, rather than independently submitting conflicting factor orders.

Current Engine slippage is one global configuration, so a true joint simulation cannot apply separate2/5/8bp class assumptions without changing core. **8bp baseline on every leg and16bp stress** is a transparent conservative prospective assumption; fees5/10bp, stress one-minute extra delay and half participation remain. Keep current corrected isolated leverage1 and max gross leverage1, and report actual exposure drift rather than calling the account continuously beta-neutral. Shared wallet cash does not automatically collateralize an isolated losing leg.

I recommend an entry screen against turnover costs. Before an entry, estimate unnetted three-leg joint-stress round-trip fees/slippage (both entry and exit on each intended gross leg). Require hypothetical convergence value `a_i × max(0, |x_i−mu_i| − 0.5sigma_i − |alpha_i|×48)` to exceed twice that cost estimate. Do not offset the budget with favorable funding or favorable alpha. This is an approximate log-return model diagnostic, **not promised PnL or a guaranteed conservative execution bound**. Future funding, price gaps, volume cleanup and nonlinear exposure can exceed it; actual cash flows remain in Engine. Using unnetted hedge costs avoids optimistic savings from simultaneous group cancellations. If this screen produces no activity, retain that no-trade result rather than weakening the cost requirement.

## Pending orders and isolated risk

Use submitted public `Order` objects and their mutated status/remaining quantity to track commitment. `ctx.target` cancels pending orders each call, so repeatedly calling it while an unchanged exit is delayed can starve execution. Retain eligible GTC exits; submit/cancel only on actual intent changes. A central coordinator controls the two shared factor instruments. Never compute performance by subtracting separate single-asset simulations.

The simplest conservative failed-leg policy is a **basket-wide abort**: cancel entry intentions and issue reduce-only zero targets for all actual positions if an entry is rejected/cancelled, or summed marked deviation from the fixed intended native targets exceeds1% of intended gross for five minutes. Keep closing orders alive until genuinely filled, block new entries while any close remains pending, and start the24-hour cooldown after actual flattening. A one-leg fill is real exposure during those five minutes, not an atomic hedge. The initial entry timer, target quantization, tiny net hedge below minimum notional and pending-commitment accounting require explicit synthetic fixtures before running.

Likewise, if any held leg's `(maintenance + taker/liquidation close reserve) / (isolated collateral + UPL)` reaches0.5, or local equity is nonpositive, request the same basket-wide risk exit. Engine owns actual mark liquidation and funding. Cash cannot be fabricated into an isolated allocation; minute observations cannot catch every intraminute margin breach. A group-level z stop could instead remove only one group and recompute the shared hedge, but that requires a more complex partial-fill/attribution policy. **Choose the scope before implementation**; do not switch after seeing how often a meme group aborts.

Actual wallet PnL, fees, settled funding, liquidation penalties and open inventory must reconcile. Record actual eight-instrument leg contributions and group intent/entry/exit episodes separately. With shared net hedges, allocating realized factor PnL uniquely to individual groups is convention-dependent; synthetic group spread returns cannot replace the actual portfolio ledger or be presented as separately executable strategies.

## Evaluation and evidence

Keep the proposed fresh-wallet three validation month folds and July5–October5 reused evaluation, with the same frozen model/anchor throughout. No retroactive training strategy simulation with coefficients estimated from later training observations. Use minute/funding-clock evaluation and joint stress, true marked terminal holdings and separate indicative exit reserves. All failed diagnostics and zero-activity cases remain retained.

Portfolio gates should require positive compounded validation, evaluation, stress and corresponding exit-reserve diagnostics; at least two of three anchored positive months; Sharpe>=0.5; drawdown<=20%; zero actual liquidations. Breadth is at least four distinct altcoins actually traded, including DOGE or PEPE, with all eight leg contributions reported. Profitable hedge legs individually are not required. The meme participation requirement reflects the requested broad assets and must remain fixed even if those models are inadmissible. Decide whether four training-admissible altcoins, including a meme, is additionally required to launch any trading; otherwise allow the eligible subset but count an insufficient-breadth run as a failure.

Add a disclosed minimum complete group-episode count if claiming statistical robustness; choose it before results. Six simultaneous exposures to one common shock are not six independent observations. Confidence intervals become conditional25-candidate diagnostics, not proof of unadapted or independent evaluation. There is no sound basis here to promise four or five durable profitable strategies.

## Approval decisions still required

1. ADF threshold: nominal0.01 per asset or prospective0.01/6; fixed coefficient/conditioning safeguards and deterministic inadmissibility behavior.
2. Entry schedule and ex-ante two-times-stress cost screen, including conservative alpha drag.
3. Group-level signal exit versus basket-wide stop/failed-leg/margin abort, native target-tracking tolerance and five-minute timer semantics.
4. Whether minimum four admissible alts (including one meme) prevents trading altogether, and minimum completed episodes for a claim.

No implementation should begin until those choices form one reviewable frozen packet. The thresholds above are recommendations/draft choices, not historically optimized parameters.
