# Cross-venue funding differential: execution feasibility

Status: read-only planning after the failed residual experiment. No new candidate
has been frozen, no historical model fitted and no full Bybit dataset collected.
This describes a possible 26th exploratory candidate, not a tested edge or a
live execution system. The existing 25 candidates and their frozen code remain
unchanged. Companion [data feasibility](cross_venue_data_feasibility.md) documents
the small public boundary probes; those probes do not establish complete coverage.

## Feasible with the present engine

One `Engine` can coordinate two separately funded exchange wallets. Instruments
must have distinct IDs such as `binance:perpetual:BTCUSDT` and
`bybit:perpetual:BTCUSDT`, even when symbols match. Position, prior-volume and
order state use the full ID. `Portfolio.cash` is keyed by venue. Opening margin,
position limits, gross leverage and liquidation calculations use the relevant
venue's balances and positions. Cross margin pools eligible derivatives **within
one venue**, never across exchanges. Funding and trading cash flows change only
the instrument's wallet. Pooled reported equity is the sum of venue equity, not
transferable collateral.

The checked checkout has no `DataBundle` class. The current executable interface
is `Engine(instruments, config).run(bars, strategy, funding=...)`, with normalized
tall bar/funding DataFrames. A new collection manifest or research-specific bundle
can wrap those inputs without changing their execution semantics.

| Concern | Current behavior | Research consequence |
|---|---|---|
| Settlement currency | All instruments must share one quote currency | Restrict to native linear USDT perpetuals; exclude inverse/USDC products |
| Wallet capital | `initial_balances={'binance':50000,'bybit':50000}` is supported | Total capital is 100,000, with no assumed later transfer or replenishment |
| Fees and rules | Per-instrument fees, increments, maintenance rate and liquidation fee | Pin separate venue assumptions; current rules approximate historical rules |
| Risk configuration | Leverage/margin mode and slippage/participation/delay are global | Use common conservative assumptions; do not claim independently calibrated venue latency |
| Funding events | Explicit rate/mark/time per instrument; intervals are not synthesized | Retain actual asynchronous settlement clocks and changing intervals |
| Pair execution | Separate orders, separate volume capacity and risk acceptance | A pair is never an atomic exchange transaction |
| Terminal inventory | Remaining positions are genuinely marked | Disclose each venue/leg plus indicative exit costs; no fabricated close |

Evidence already exists in `tests/test_derivatives.py`:
`test_exchange_wallets_never_mutually_collateralize` proves that a profitable or
well-funded Bybit wallet cannot rescue a failing Binance cross wallet;
`test_snapshot_equity_reconciles_account_cash_and_unrealized` verifies pooled
cash/equity against the separate venue contributions. Funding direction/sign and
negative-balance/penalty conservation also have existing hand-value tests. These
are accounting foundations, not evidence of a successful cross-venue strategy.

## Important accounting and execution boundaries

The smallest truthful no-core-change scope uses **cash-only cross margin at both
venues**, low gross exposure and a separately funded cash buffer. The existing
isolated funding policy always changes a position's isolated collateral by its
funding payment. Bybit currently describes a different debit priority: available
balance first, then initial position margin if insufficient. Therefore the
current isolated model must not be advertised as an exact Bybit isolated-account
replication. Cash-only cross margin avoids this particular reserve-priority
mismatch, but fixed maintenance rates, fee reserves and forced-liquidation fills
still approximate actual exchange tiers, unified collateral and liquidation
procedures. Bybit also describes dynamic funding intervals and uncertainty for
positions changed within seconds of settlement. A minute model should avoid
settlement-boundary entry/exit claims rather than promise funding capture.
[Bybit funding rules](https://www.bybit.com/en/help-center/article/Funding-fee-calculation).

A price-neutral pair can still lose one account. Equal long/short base quantity
cancels common price movement in the pooled P&L approximately, while gains on one
venue do not collateralize losses on the other. Funding profits, venue basis
changes and liquidation losses must remain separate ledger contributions.
Transfers, borrowing, insurance-fund support, automatic deleveraging, exchange
failure and withdrawal restrictions are not modeled.

Core liquidation forcibly closes the full position at an adverse mark-derived
price without normal volume capacity. That is an explicit emergency-fill
approximation, not evidence of available market depth. There is no order-book,
BBO spread, queue, latency distribution or cross-exchange clock receipt replay.
FOK/IOC apply to one order and do not make two venues atomic. `Context.target`
cancels pending orders on that instrument, so calling it every minute can defeat
delayed fills; a pair coordinator must retain its original GTC orders.

## Minimum causal data and coordinator contract

Use independently sourced trade OHLCV and mark OHLC for each venue. Bybit linear
trade volume is in base coin and turnover is in quote currency; reversed API
pagination must be sorted and checked for exact duplicate-free coverage. Mark
candles have no tradable volume. Keep each instrument's volume independent;
never use Binance volume to fill Bybit orders.
[Bybit kline schema](https://bybit-exchange.github.io/docs/v5/market/kline).

Native base normalization belongs in an explicit mapping. The probes found
1000PEPEUSDT on both venues: one native quantity unit corresponds to 1,000 PEPE,
and both native prices are per bundle. Equal and opposite native quantities
therefore match exposure directly. Current Binance/Bybit steps of 1/100 require
a common 100-native-unit hedge grid, representing 100,000 underlying PEPE. This
is a current-rule approximation, not a historical lot-size certificate. For
other contracts, compute the common quantity grid from exact decimal native
increments and reject an unmatchable opening minimum. Never multiply quantity
and price by the bundle factor twice.

Funding history is a record of **settled** rates, not the rate announced for an
upcoming settlement. Bybit returns symbol, funding rate and settlement timestamp,
without settlement mark or original historical receipt time. The engine requires
a positive funding mark, so the adapter must declare a same-venue minute-mark
proxy and its approximation: a backward completed mark or the settlement
minute's mark-open assumption, never that minute's future close as an exact
instantaneous mark. Differences against genuine settlement marks are unknown;
retain a valuation sensitivity and do not call those cash amounts exchange-exact.
[Bybit funding-history schema](https://bybit-exchange.github.io/docs/v5/market/history-fund-rate).

The decision predictor must be a separate causal feature stream. For a realized
rate at settlement `s`, its assumed decision availability is
`max(s, recorded_receipt_if_present)+one_minute`, rejecting any receipt before
settlement. With no receipt archive, that lag is an assumption. Read only rates
already available at the decision clock, apply a fixed stale/no-trade rule, and
normalize historical payment intervals before comparing rates. An eight-hour
payment must not be compared directly with a one-hour payment as equal horizons.
Interval estimation may use only prior observed settlement times; today's
instrument interval must not overwrite the historical schedule. The realized
next payment belongs exclusively to the cash replay, never to an entry score.
Opening at settlement after its cash event cannot retroactively earn that event.
A delayed-publication rate must not leak through `on_funding`; the coordinator
should read its separately lagged feature stream.

Before outcomes, define one central immutable target intent for both legs,
with native quantities fixed at entry. Evaluate both wallets' available balance
and opening minima; submit one GTC order per leg and observe actual positions.
Use a predeclared completion tolerance, bounded attempt/deadline rule, matched
quantity diagnostic and explicit unhedged exposure budget. On rejection,
overshoot, deadline failure or either leg's actual liquidation, cancel tracked
orders and retain reduce-only GTC cleanup of both actual positions through partial
fills. A closed profitable leg does not erase the other leg's deficit. Subminimum
quantity dust stays marked and blocks re-entry. No synthetic target shrinkage,
cash transfer or atomic rollback should make the pair appear complete.

## Fresh tests and conditional changes before any numerical study

1. Actual two-venue Engine fixtures: matched opening/closing quantities, different
   fee/tick/lot rules, four funding sign combinations and separate wallet cash,
   collateral and equity at every settlement clock. Include native 1000PEPE
   common-grid rounding and distinct IDs despite equal symbols.
2. Asynchronous settlement and publication tests: mismatched one/eight-hour
   histories, millisecond event jitter, out-of-order/late receipts, no retroactive
   funding on a new leg and future-rate/price perturbation invariance.
3. Non-atomic GTC tests: only one leg fills, independent low volume, delayed
   acceptance, rejected margin, opposite venue gaps, partial cleanup, minimum
   quantity dust and liquidation before the hedge completes. Persist orders and
   retain negative wallet balances; never imply FOK makes a whole pair atomic.
4. Per-venue accounting/exposure audits and exact final open-inventory identity.
   Test indicative exit reserves independently from cash; preserve actual
   funding at an endpoint when sourced and a position survives.
5. Full-grid/source/rule/mark validation before fitting or replay. Current bar
   normalization warns about gaps rather than rejecting them. The new runner
   must fail incomplete coverage or predeclare a genuine no-trade outage model;
   it must not create tradable forward-filled bars.

No core change is needed for the restricted two-wallet cash-only cross-margin
scope. Research-specific collectors, causal features, coordinator and audits are
new work. An exact isolated-Bybit claim would require a prospectively versioned
funding-allocation policy and debit/receipt reserve tests; independently varying
venue latency, slippage or capacity would need configuration/execution extensions.
For genuine outage replay, current opening capacity can reuse the last completed
volume after a long gap; a future version should suppress stale capacity. These
extensions must not silently amend any prior frozen experiment. Risk-tier,
insurance/ADL, historic fee schedules and settlement-boundary matching need data
and additional models, not an unsupported configuration flag.

Begin with synthetic one-pair proof fixtures. If full-year data then passes,
freeze one economical funding-differential family before inspecting its returns.
A joint 16-instrument/two-wallet basket can share cash within each venue; separately
simulated paired sleeves would instead represent segregated subaccounts and must
be labeled accordingly. Preserve all predeclared assets and failures, rather than
selecting the best venue/asset after outcomes. Benchmark memory before a large
joint run. Even a future positive result is an exploratory new-input experiment
on a reused year, not four independent strategies or non-overfit proof.
