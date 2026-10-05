# Execution model: design contract and limitations

Research checked 6 October 2026. This document specifies the intended conservative
model. The implemented behavior and supported switches must be checked against
the run manifest and tests; design proposals below are not implementation claims.

## Verified MVP profile

The independent code audit verified the interval-boundary engine in
`aster/backtest/engine.py` against the scenarios recorded in `docs/audit.md`.
Its current implementation has these explicit simplifications relative to the
broader design below:

- Conservative and volume-aware profiles share strict penetration plus an
  additional full resting interval. The touch profile permits equality.
- Opening capacity uses prior completed volume. Close capacity uses completed
  current volume less opening allocations, so a subsequent low-volume candle
  cannot retroactively cancel an opening allocation.
- Fixed, spread, volatility and volume slippage are deterministic models.
  Spread is included in the `spread` slippage profile; fixed mode does not add
  synthetic bid/ask. Opening limit marketability is evaluated against open,
  not an observed L1 quote. The execution-price limit remains enforced.
- Order delay applies to submission/trigger activation; cancellations take
  effect immediately at the callback. No cancel-transmission queue exists.
- A partial GTC market order retries at later opens. Use IOC to request immediate
  remainder cancellation; this retry policy is a simulator convention, not a
  universal exchange market-order behavior.
- Funding callbacks expose settled historical rates, not predicted upcoming
  rates. Publication delay is currently zero. Exact publication-time replay is
  an extension; the closed-bar cutoff and positive activation delay are tested.
- Same-time marks and funding settlements are batched before account-wide risk
  checks. Opening/closing prices or supplied mark observations drive liquidation;
  there is no intrabar mark path or order-book liquidation auction.
- Rebate fees are supported through signed rates. Tick and lot grids use guarded
  floating-point rounding, not exact decimal/integer arithmetic. Inverse and
  non-unit-multiplier contracts are rejected.

## Evidence and venue boundaries

Binance distinguishes market, limit and triggered orders; its maker-only limit is
rejected when it would immediately take liquidity. Its order API supports GTC,
IOC and FOK. These are different semantics, not merely fee labels.
[Binance order API](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/trading-endpoints).

Binance publishes tick, quantity and notional filters that should be validated
against decimal grids. A historical run needs historical filter snapshots;
current instrument rules are not evidence of past constraints.
[Binance filters](https://developers.binance.com/docs/binance-spot-api-docs/filters).

Bybit converts market orders into IOC orders with price protection, so a submitted
market order need not fill completely. Its conditional orders can use last, mark
or index triggers, and reduce-only must prevent position increases.
[Bybit order API](https://bybit-exchange.github.io/docs/v5/order/create-order).

OKX distinguishes market, ordinary limit, post-only, IOC and FOK; derivative size
is contracts whereas spot size is base asset quantity. Normalize quantity units
using contract multipliers before execution or accounting.
[OKX API](https://www.okx.com/docs-v5/en/).

Bybit exposes tick and lot filters, leverage bounds, funding interval and launch
and delivery times. These belong in instrument metadata, versioned through time.
[Bybit instruments](https://bybit-exchange.github.io/docs/v5/market/instrument).

NautilusTrader separates market-data replay, simulated venues, accounts, matching
and fill models. Adopt these separations without implying that a candle replay
has order-book fidelity.
[Nautilus backtesting](https://nautilustrader.io/docs/latest/concepts/backtesting/).

## Time contract

Represent every bar as `[start_time, end_time)`, UTC. Its complete high, low,
close and volume become available at `end_time + publication_delay`. An exchange
API's inclusive close timestamp is normalized to the exclusive boundary. Keep
`event_time` distinct from `available_time`; historical settlement rates are not
strategy-visible before their published availability.

1. Complete the preceding interval's existing-order matching and valuation.
2. Apply funding at its exact settlement timestamp to positions already held at
   the timestamp, before strategy-generated opening orders at that boundary.
   This is a documented tie-breaking convention, not a universal exchange rule.
3. Publish completed bars together across instruments; call strategy with a
   read-only history ending here. One symbol must not see another's future bar.
4. Submit orders. `activation_time = submission_time + strategy_latency +
   transmission_latency`; cancellation has its own effective arrival time.
5. Execute at the first eligible future observation. For bar-only opening
   execution use `bar.start >= activation_time`. A strictly positive 50 ms delay
   after a close boundary therefore advances to a later bar opening; interpolated
   sub-bar prices are unavailable.

Zero-latency next-open is a coarse boundary assumption: the previous closed bar
may inform an order filled at the next opening trade. It cannot fill at the
previous close. Publication delay must be included if known. Same-bar-close mode
requires a separately documented valid order mechanism and is excluded by default.

## Conservative candle matching

The model intentionally avoids inventing an OHLC path. A resting order eligible
before the interval begins can use that interval's extrema only when the interval
has completed; fills are timestamped at completion, before the strategy callback.
This prevents a fill callback from reacting to a hidden intrabar fill and placing
another order into the same completed interval.

| Situation | Intended behavior |
| --- | --- |
| Market at opening | Taker; reference open plus adverse spread/slippage; no old-close execution |
| Buy limit marketable at activation | If limit >= simulated ask, taker; fill price never above limit |
| Sell limit marketable at activation | If limit <= simulated bid, taker; fill price never below limit |
| Post-only marketable at activation | Reject/cancel per venue policy; never silently convert to taker |
| Resting buy limit | Require strict penetration: low < limit minus configurable tick buffer |
| Resting sell limit | Require strict penetration: high > limit plus configurable tick buffer |
| Exact limit touch | No fill in conservative model; touch model must be explicitly labelled |
| Gap through an existing limit | Use maker classification for already resting order; conservatively fill at its limit, without claiming favorable opening improvement |
| Stop crossed at opening | Trigger at opening; stop-market reference is adverse opening price, not old stop price |
| Stop crossed only intrabar | Detect at interval completion; activate child at next eligible observation |
| Stop-limit crossed intrabar | Trigger now, defer limit matching; high/low cannot establish trigger-then-fill ordering |

Limit adverse cost cannot be clipped to manufacture a fill: if an immediately
marketable candidate with spread/impact exceeds the limit, withhold that candidate.
Passive limit execution at the limit should not have a second adverse slippage
deduction that violates its price constraint. Its adverse selection remains a
model limitation.

Maker/taker is a property of each fill. An ordinary GTC order may first take some
liquidity and later rest and make liquidity. A limit-order label alone cannot
determine the commission rate. Synthetic opening bid/ask is `open * (1 +/-
spread_bps / 20000)`; these are assumptions, not observed quotes.

## Volume, TIF and queue approximation

Use one aggregate capacity budget per instrument and matching interval. All
orders compete in a deterministic priority order; do not independently reuse
the entire volume for each order. Snap executable size down to the lot grid.

Opening executions may use only previously published liquidity observations.
Previous-bar volume times a participation fraction is a causal proxy. Current
bar total volume is not known at its open and must not determine an opening
fill. Close-time resting fills may use current completed volume, while still
sharing capacity with previous opening allocations. Zero capacity means no fill.
This does not estimate executable depth or volume at a particular limit price.

- GTC: keep unfilled remainder resting until cancellation or run end.
- IOC: one activation matching opportunity; cancel all unfilled remainder.
  A nonmarketable IOC must not wait for a later candle excursion.
- FOK: first calculate full candidate capacity, price and available funds/margin.
  If any requirement fails, cancel with zero fill and zero fee. Commit atomically.
- Partial market fills: cancel remainder under an IOC-like protection policy, or
  explicitly label a configured retry policy; silently persisting a market order
  is misleading.
- Reduce-only: on every candidate fill, recalculate the live position. Clamp to
  the reducing quantity and cancel if no longer reducing. Outstanding opposite
  reducing orders must never flip a position.
- Post-only plus IOC/FOK: reject incompatible combinations unless the venue
  explicitly permits a supported interpretation.

Queue position is not observable from candles. Strict penetration and limited
participation are conservative heuristics, not guarantees of queue priority or
fill probabilities. Do not call this HFT-realistic. Seeded probabilistic models
are suitable for sensitivity runs, with the seed in the manifest.

## Costs and observability

Maintain fill quantity, reference price, execution price, liquidity type,
commission rate, commission amount, spread/impact assumptions, activation time,
fill model and exit reason. Explicit fee amounts should use the commission
currency, normalized to reporting currency if supported.

`slippage_cost = side_sign * quantity * multiplier * (execution - reference)`.
Execution prices already include slippage in trading P&L. Report slippage as an
attribution component, or use reference-price gross P&L, but never subtract it
twice from actual-price P&L. Funding and liquidation penalties are separate cash
ledger entries. All fill cash/margin mutations must be atomic after validation.

## Future quote/trade/L2 implementation

Quote mode uses real bid/ask; takers consume the opposite side. Trade mode needs
aggressor side and volume-at-price to advance resting queue estimates. L2 replay
requires sequence validation, snapshot/update reconciliation, queue depletion,
hidden-order assumptions, and a policy for the simulated order's market impact.
L2 snapshots alone do not reveal queue rank or cancellations ahead of us.

Cross-venue fills use separate balances, clocks, latency and books. Hedge orders
can fill asynchronously, leaving leg risk. No atomic arbitrage fill or immediate
balance transfer is assumed. Inverse contracts and venue-specific price bands,
self-trade prevention, fee rebates/tier changes, outages, insurance funds and
ADL need dedicated extensions and historical metadata.

## Required verification cases

Hand-calculate tests for close-to-next-open gaps; positive latency crossing a
boundary; untouched/equal-touch/penetrated limits; marketable limit taker fee;
post-only rejection; two orders sharing liquidity; IOC cancellation; atomic FOK;
reduce-only competing closes; stop-market gap; ambiguous stop-limit candle;
zero-volume interval; lot/tick/minimum-notional failure; and slippage attribution
reconciling exactly to final account equity.
