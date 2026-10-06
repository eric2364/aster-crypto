# Proposed packet: cross-venue realized-funding differential

Status: prospective implemented packet reviewed with synthetic tests. This is
**not yet a source/input-frozen or historically tested 26th candidate**. The full
Bybit year has been acquired and checked for source reconstruction only. No
historical strategy features, fitting, signals or Engine outcomes have been
calculated or inspected for this definition. Source/input/runtime freezing and
its dated Git evidence must precede that work. The same year has already been examined through
25 unsuccessful candidates; this remains exploratory even after a code freeze.
There is one economic family, not several independent edges. Earlier packets,
execution code and results are not amended.

## Economic mechanism and fixed scope

Hold equal and opposite native base quantities on Binance and Bybit, shorting
the venue with the higher *previous realized funding intensity* and buying the
other venue. The hypothesis is persistence of a venue funding differential long
enough to cover two independently executed roundtrips. Common price risk is
approximately hedged; venue basis, funding changes, execution failures and
separate-account margin risk remain. No future basis convergence, future funding
announcement or perfect arbitrage is presumed. Market segmentation motivates
investigation, not proof of this funding edge:
[Makarov–Schoar](https://dspace.mit.edu/entities/publication/7f91bfb5-ba77-4d0e-9c79-ec75e104e6cc).

Use only `[2025-10-05T00:00Z, 2026-10-05T00:00Z)`: BTC, ETH, DOGE, PEPE, SOL,
XRP, LINK and ADA native linear USDT perpetuals on both venues. Do not import a
pre-year predecessor, price warmup or funding payment. Both PEPE instruments
remain native 1000PEPEUSDT. No asset ranking, return-based exclusion, model grid,
parameter selection or ineligible-budget redistribution is permitted.

## Previous-only predictor: exact definition

At decision time `t`, construct each venue's funding sequence **only from records
with availability strictly before t**, ordered by actual settlement time. Availability is
`max(settlement_time, explicit_historical_receipt_if_present) + 1 minute`.
Reject a receipt before settlement. An archive downloaded today is not an
original historical receipt. Without such receipts, the one-minute lag is an
explicit modeling assumption. Records whose availability equals t are deferred; future/unpublished rows must not change the
sequence, predecessor choice, invalidity flags or feature at t.

For adjacent known settlements `s_prev, s_j`, observed elapsed hours are
`d_j=(s_j-s_prev)/1hour`. An interval is recognized only when its duration is
within 5 seconds of one of `{1,2,4,8}` hours. Use the **actual elapsed duration**
in calculations, not its rounded label. The first within-year record has no
predecessor and contributes no interval. Nonpositive, duplicate, malformed or
unrecognized intervals are invalid. An invalid known interval with positive-length overlap with the
trailing window suppresses that venue's feature; do not delete it to improve a
score. Source completeness must also pass independent pagination/raw-row checks.
Additionally require one common recognized cadence label among **all** currently
known intervals with positive-length overlap with the seven-day window, independently per venue. A
mixture of otherwise legal interval lengths is ambiguous and suppresses the
feature until the transition ages out; do not choose the prevailing label and
ignore the others. This intentionally forgoes trading through genuine cadence
changes as well as suspected missing-event gaps. A lone missing four-hour payment
therefore cannot silently become an accepted eight-hour interval among four-hour
records. Missing every other payment consistently could still appear regular:
timestamps and the 90% duration threshold cannot establish completeness. Full
raw pagination is necessary, and unresolved source omissions fail collection
quality rather than being repaired with fabricated rates. The elapsed interval
is observed history, not proof of the contractual earning period or recovered
historical schedule.

The trailing calendar window is `[t-168hours,t]`. For each recognized, cadence-consistent completed
interval whose two endpoints are currently known, let `w_j` be its overlap with
that window, in hours, and let `u_j=realized_rate_j/d_j`. Define

`intensity_v(t) = sum(w_j*u_j) / sum(w_j)`.

Require covered hours `sum(w_j) >= .90*168` independently at each venue. The
unsettled/unpublished tail contributes neither a payment nor a made-up zero
rate. Do not sum only a fixed number of observations: one-hour and eight-hour
payments are not comparable observations. Suppress if the newest known
settlement is older than its latest recognized elapsed interval plus 10 minutes.
There must be a recognized latest interval; otherwise there is no feature.
All these checks are causal and recomputed from known rows, including delayed
out-of-order publication. There is no global full-history invalidity flag that
leaks a later gap into an earlier decision.

Compare `gap = intensity_bybit - intensity_binance`, in rate per hour. Positive
gap proposes long Binance/short Bybit; negative gap proposes the reverse.
Signals are evaluated hourly at UTC `:05`. Prices are synchronized completed
trade closes with completion plus one-minute availability and at most two-minute
staleness. No current bar's future close/volume, future settlement rate or
forward-filled tradable price may enter the score. Funding callbacks supply
cash facts, not instantaneous access to a newly settled predictor rate.

## Capital, native units and fixed cost admission

One actual 16-instrument joint Engine, two separate 50,000 USDT cash wallets;
leverage 1, cash-only **cross** margin at each venue, `max_gross_leverage=.5` and
`max_position_pct=.25`. No transfers, borrowing, automatic cash replenishment,
shared collateral, unified noncash assets or insurance credit. Account equity
is pooled only for reporting. Venue risk remains independently binding.

Each of eight pair sleeves receives a fixed 1,250 USDT maximum initial leg
notional on each venue: total initial gross budget 20,000 USDT, 20% of capital.
At entry use the largest common native-grid quantity satisfying
`q*known_price_binance <=1250` and `q*known_price_bybit <=1250`, both opening
minima and all fixed quantity bounds. Use exact decimal lot-grid intersection,
not `max(lot_steps)`; `.03` and `.02` require a `.06` common step. The additive
`units.py` helper implements this contract. Reject unmatchable/below-minimum
pairs. Both 1000PEPE quantities are equal native units; no spot conversion or
second price/quantity multiplier is used. Store quantities fixed at entry; no
minute notional rebalancing. Unused budgets stay cash.

Baseline assumed taker fees: Binance 5bps, Bybit 6bps. The Bybit assumption is
rounded conservatively rather than treated as a verified historical personal
fee tier. Use global adverse slippage 8bps on every instrument and previous
completed-volume participation 5%. The joint stress doubles fees to 10/12bps,
slippage to 16bps, adds one-minute activation delay and halves participation to
2.5%. Venue tick rounding remains adverse. This is a minute market-order cost
model, not a spread/order-book claim. Identical admission logic applies to both
baseline and stress.

For planned matched native quantity q and currently available prices, let
`N_ref=q*(P_binance+P_bybit)/2`. Forecast carry over the fixed seven-day maximum
holding horizon using only the intensity difference:

`forecast_carry = N_ref * abs(gap) * 168`.

Conservative unnetted joint-stress roundtrip cost is

`C = 2*q*[P_binance*(10+16)/10000 + P_bybit*(12+16)/10000]`.

Require `forecast_carry >=1.5*C` and nonzero gap. All four planned entry/exit
fees and slippage costs remain in C even if positions offset in pooled exposure.
There is no favorable future basis/funding credit. Seven days amortizes the
four fills in a slow carry hypothesis; the 50% cost buffer acknowledges an
uncertain persistence forecast. Neither choice is a fitted performance result.
If this gate admits nothing, retain that valid failure and do not relax it.

## Holding, asynchronous execution and risk exits

At entry save orientation, native quantity, C and submission time. At subsequent
hourly `:05` decisions, close when the retained-direction gap is nonpositive,
when either causal feature is invalid/stale, or when retained-direction forecast
carry using the same seven-day horizon falls below `.5*C` (entry C is fixed).
Close after seven elapsed days since submission regardless of rates. No same-
callback reversal or reopen. A completed normal exit starts a 24-hour pair
cooldown. No new entry in the final seven days of any fold. Existing final
inventory is genuinely marked; there is no forced terminal fill.

Each pair intent is immutable: one native GTC order for each changed leg.
Submit both orders, retain their objects and never cancel/resubmit each minute.
At each completed minute, compare actual positions against both targets with
`max(1e-9, native_lot*1e-6)` tolerance. Completion requires both actual native
quantities, not matching notional or merely accepted orders. Deadline is entry
submission plus configured activation delay plus five minutes. Orders can fill
independently; FOK/IOC cannot make a whole cross-venue pair atomic.

On rejected/cancelled unmet leg, overshoot, deadline failure or an actual
liquidation, cancel tracked orders and abort that pair: submit reduce-only GTC
cleanup of both actual legs and persist partial fills. No new entry until both
legs are genuinely flat and a 24-hour pair cooldown after cleanup has elapsed.
Subminimum quantity dust remains marked and blocks that pair. Report transient
unmatched native quantity, its marked dollar exposure, duration and all failed
intents. Never manufacture a hedge completion or transfer collateral to conceal
one venue's deficit. An actual liquidation fails the study hurdle even if the
other venue's gains leave pooled P&L positive.

At every completed minute, an account-level risk breach—either venue equity
at or below 80% of its initial 50,000, nonpositive available margin, or actual
venue gross exposure above `.5*venue_equity`—aborts the entire account. Cancel
all tracked entries and retain reduce-only cleanup of all actual positions.
Re-entry requires truly flat accounts plus 24 hours after cleanup. This trigger
is a request for a future executable exit, not a guaranteed loss bound. Core
forced liquidation may still occur first and has its disclosed mark-derived,
capacity-unconstrained emergency-fill approximation.

Normal decisions occur five minutes after the nominal hourly boundary, not
within Bybit's stated seconds-around-settlement ambiguity. Unknown historical
clock/receipt precision remains a limitation. A leg entered after a funding
cash event never receives that already-settled payment. Delayed leg completion
can legitimately leave only one venue eligible for a later payment; retain the
actual asymmetric cash flow rather than assuming matched funding schedules.
[Bybit funding and settlement rules](https://www.bybit.com/en/help-center/article/Funding-fee-calculation).

## Actual cash valuation and predetermined sensitivity

Retain each Binance funding row's actual sourced settlement mark. Bybit funding
history supplies no settlement mark: primary cash valuation uses the same-
venue mark candle's **open** for the minute containing the actual settlement.
Label it a minute-mark approximation, not exchange-exact cash. At the exclusive
END, where no new within-year mark-open exists, use the last completed within-
year mark close. Never download/use a post-year candle to fill that boundary.
The first START event has no preceding within-year completed mark for the
alternative. Keep its raw rate in causal history without inventing a cash mark;
no Engine fold begins before April, and phase clipping precedes required-mark
validation for that alternative cash replay.
Duplicate/missing mark coverage fails quality, not interpolation.

Predetermine an alternative valuation using the latest completed same-venue
mark close at or before each Bybit settlement; preserve all real rates, event
clocks, quantities, economic parameters and Binance funding marks. Execute the
same evaluation baseline and joint stress under this alternative because cash
valuation can affect venue risk/execution. These are sensitivity replays of one
candidate, not two new strategies. Positive cash valuations do not establish
exact historical settlement marks.

## Disjoint runs, fixed gates and full disclosure

The first six months supply causal history and source checks only: no training
P&L selection, fitting or threshold optimization. Three fresh-wallet validation
folds are April5–May5, May5–June5 and June5–July5. Evaluation is July5–October5.
Exactly seven joint simulations are retained: three primary-valuation validation
folds, primary evaluation baseline/stress, and alternative-valuation evaluation
baseline/stress. Features use only past available records within the fixed year;
wallets reset between folds. No outcome-based neighboring grid is introduced. Seven-day forward carry is a
frozen extrapolation of past cash-rate intensity, not a claim that future rates
or settlement intervals are known.

Pass only if all predeclared gates hold:

- Positive compounded primary validation return, primary evaluation and joint-
  stress returns, and corresponding returns after indicative exit-cost reserves.
- Positive alternative-valuation evaluation and joint-stress returns and their
  corresponding indicative-reserve returns.
- At least two of three anchored evaluation months positive; daily Sharpe >=.5
  and full minute/funding-clock marked drawdown <=20% on primary evaluation.
- No actual liquidation in any of the seven runs.
- At least four distinct pairs achieved an actual matched completed entry in
  primary evaluation, including **both DOGE and PEPE**. Hedge legs may lose;
  report both venue contributions for all eight pairs rather than require each
  leg to be profitable or hide failed assets.

Indicative reserve equals the sum of final open native marked notionals times
that run's assumed taker fee plus adverse slippage. It is analysis only, never a
second subtraction from executed cash or an assurance of available exit volume.
Report all unmatched/dust/terminal positions, costs, rates, funding cash, venue
cash/collateral/equity, entry/abort counts and both native/dollar exposures.
Conditional circular seven-day bootstrap diagnostics use 26-comparison tails
`.05/52` and `1-.05/52`, with full-resolution equity source hashes. They are not
an additional hidden selection rule and cannot undo adaptive reuse of this year.

Before any numerical outcome: complete acquisition/coverage checks; independent
synthetic causal/native-wallet/asynchronous-GTC tests; root and independent
review of this packet and code; commit/archive all model/coordinator/core/input
hashes and numerical runtime. Only then describe candidate26 as preregistered.
Reconstruct every wallet, quantity, funding and equity trajectory and rebuild
all gates before publication. Preserve all 25 earlier results. Zero admitted
pairs, a failed hypothesis or poor breadth must remain visible without retuning.
