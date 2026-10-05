# Frozen prospective definition: BTC/ETH-hedged residual convergence

Status: one new exploratory economic family, the 25th disclosed candidate after
24 unsuccessful candidates on the same examined year. This is not a fresh
holdout or a promise of four independent profitable strategies. No numerical
fit or historical signal has been inspected when defining this packet.

## Data and estimation

Only `[2025-10-05T00:00Z, 2026-10-05T00:00Z)`. The six target underlyings are
DOGE, PEPE, SOL, XRP, LINK and ADA. BTC and ETH are tradable factor proxies.
All eight actual Binance native linear perpetual trade/mark streams and actual
settlement funding are used. PEPE stays native 1000PEPEUSDT; no quantity rescale.
Current instrument rules approximate history. No order-book or quote inference.

Build synchronized hourly last completed trade closes from the verified minute
grid. Hourly close availability is completion plus one minute. Fit each target's
hourly log returns to an intercept and BTC/ETH hourly log returns using only
availability times before 2026-01-05T00:00Z. Require finite data, full rank and
condition number <=100 on the centered, standardized two-factor design. Freeze
these return betas and hourly alpha. This is not a log-level cointegration fit.

Use the first complete hourly price available at/after January5 as a single
cumulative origin. The residual at any completed price time t is
`log(P_alt(t)/P_alt(origin)) - beta_B*log(P_B(t)/P_B(origin)) -
beta_E*log(P_E(t)/P_E(origin)) - alpha*elapsed_hours(t,origin)`.
Compute it on a disjoint January5–April5 calibration block. Fit an intercept+AR1
OU approximation there: x_next=a+phi*x_prev+innovation; mu=a/(1-phi),
sigma_equilibrium=sqrt(sample_innovation_variance/(1-phi^2)),
half_life_hours=-log(2)/log(phi). Never force its endpoint to zero.

An asset is eligible only if all diagnostics pass: sum(abs(betas))<=4,
0<phi<1, positive finite innovation/equilibrium variance, half-life1–24hours,
and conditional ADFp<=.01 using statsmodels0.14.6, regression='c', maxlag24,
autolag=None. Each chronological calibration half must have its mean within
one full-block equilibrium sigma of mu; the second/first sample variance ratio
must be between .25 and4. All failed assets and diagnostic values are retained.
ADF is a conditional eligibility diagnostic, not a six-asset joint stationarity
proof or an out-of-sample guarantee. No alternate tests/cutoffs after outcomes.

All betas, alpha, origin, mu and sigma remain frozen after April5. Minute
features use all three synchronized, completed prices plus the same one-minute
publication lag. No cumulative origin/equilibrium reset at folds or entries.
No future funding, future prices or validation/evaluation estimation enters.

## Signal and cost rule

At each available minute, z=(x-mu)/sigma. Enter opposite z only if2<=abs(z)<4.
Exit on abs(z)<=.5, direction crossing toward/beyond equilibrium, stopabs(z)>=4,
or48hours since submission. Stop takes precedence; no simultaneous reopen.
An asset stop starts a24hour local cooldown after its exit transaction completes.
No entry in the final48hours of a fold. Existing inventory remains genuinely
marked at the end; no terminal fill is fabricated.

Before entry, prospective residual recovery over48hours is
`max(0,(abs(x-mu)-.5*sigma)*(1-phi**48)-abs(alpha)*48)` in alt log-return units.
It must be >=two times the conservative UNNETTED joint-stress roundtrip
cost, weighted by all three planned native leg notionals divided by actual alt
notional. Stress cost is2*(10bpfee+16bpslippage) per leg. All native rounded
legs must satisfy their opening minima; a required hedge rounded to zero blocks
entry. No favorable alpha or funding credits subsidize eligibility. This is a
model forecast filter, not assured convergence. Forward funding is unknown and
omitted from the entry estimate; actual funding is charged in simulation.
The identical stress-budget filter is used in baseline and stress simulations.

## Actual joint execution and risk

One centralized strategy in one eight-instrument Engine and one100,000USDT
account per fold. Isolated leverage1, maxgross1, maxposition.5. Total initial
basket gross budget is25,000, equally divided across six targets; inadmissible
or idle budgets stay cash and are not redistributed. For each entry, ideal alt
notional is its gross budget/(1+abs(beta_B)+abs(beta_E)); choose native quantities
at observed available close prices. Hedge dollar notionals are minus beta times
signed alt notional. Round quantities to native lots. Store each active basket's
fixed native alt/BTC/ETH contributions; shared factor targets are their sums.
No minute mark-based rebalancing. Estimated beta neutrality at entry is an
approximation; report actual dollar and factor exposure and all eight leg P&Ls.

Baseline taker fees5bps and uniform adverse slippage8bps on EVERY leg, a
prospective conservative assumption because Engine slippage is account-wide.
Stress doubles to10/16bps, adds one-minute activation delay and halves prior
completed-volume participation from5% to2.5%. Neither mode has atomic fills.
Actual separate funding and independent marks remain unchanged.

Each intent produces one immutable full native target vector and one GTC order
per changed instrument. Never cancel/reissue pending orders every minute.
Check completion from actual positions at the next completed minute, with
max(1e-9,lot*1e-6) tolerance. Observe five eligible opening attempts: deadline is
submission + activation delay +5minutes. Rejection/cancellation with unmet
quantity, overshoot, any liquidation or deadline failure aborts the entire
account transaction. Cancel tracked orders; submit one reduce-only GTC exit per
actual position and retain it through partial fills. No new entry until genuinely
flat, then wait24hours from the observed flatten completion before new entry. Unclosable sub-minimum dust stays
marked and blocks re-entry. No risk-saving invented fills, collateral transfers
or target shrinkage. Closing and stop requests take precedence over new entries.

## Evaluation and publication

No parameter grid, pair search, scale selection or training-profit optimization.
Three fresh-wallet monthly validation folds April5–May5, May5–June5, June5–July5;
one July5–October5 evaluation and its one joint-stress rerun. Five joint-account
simulations total. Models and residual states stay continuous despite wallets
resetting. Disclose every target, admissibility failure, fill, abort and leg.

Unchanged economic hurdle types: positive compounded validation, evaluation and
stress net returns, positive corresponding indicative terminal-exit-reserve
returns; >=2/3 positive anchored evaluation months; daily Sharpe>=.5;
minute marked drawdown<=20%; no actual liquidation in any five runs. Because
losing factor hedge legs are economically expected, prospective basket breadth
requires fills in>=4 distinct target alts including DOGE or PEPE, not five
profitable individual legs. This new rule does not amend any prior cohort gate.
No neighbor scale is relevant: there is one fixed specification, all five runs
are retained. Include full-resolution source-pinned conditional intervals with
25-comparison tails, while stating they cannot undo adaptive year reuse.

Freeze the economic packet, model/runner/coordinator and core hashes, all input
hashes and numerical runtime versions BEFORE fitting. Archive executed code.
Independently test causal prefix behavior, disjoint fits, constant-origin residual,
OU/admissibility/no-trade and non-atomic/native execution. Audit source and every
cash/native quantity/funding/reserve/equity trajectory and rebuild summaries
before publishing. Original24 studies stay unchanged. A zero-eligible/zero-trade
outcome is valid and must not trigger relaxed filters or an opposite model.

## Primary motivation and limits

[Avellaneda–Lee](https://math.nyu.edu/inmemoriam/avellaneda/AvellanedaLeeStatArb20090616.pdf)
motivates factor-residual mean reversion and identifies the fitted-residual
endpoint artifact. Its US equity results do not establish this crypto edge.
[Crypto cointegration research](https://arxiv.org/abs/2109.10662) studies a related
mechanism with quote/size information unavailable here. The present return-beta
adaptation is not a replication of that paper or a cointegration certificate.
[ADF documentation](https://www.statsmodels.org/v0.14.6/generated/statsmodels.tsa.stattools.adfuller.html)
defines the pinned test settings. Survivorship, approximate historic fees/rules,
minute liquidity/mark sampling, old factor coefficients and unknown historical
receipt times remain limitations. A pass is exploratory, not proven non-overfit.
