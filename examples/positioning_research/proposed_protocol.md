# Candidate 28: confirmed position-unwind rebound — draft before outcomes

This is one new exploratory economic family after 27 unsuccessful disclosed
candidates. It uses five-minute reported native quantity open interest as an
additional state variable while execution and risk checks run on minute data.
No historical feature generation, signal inspection, parameter fit, trial or
profitable-result claim is authorized by this draft alone. Source review,
synthetic execution checks and an exact privately published input/source lock
must precede historical computations.

## Mechanism and fixed decisions

A long/cash hypothesis: a completed price decline accompanied by shrinking
outstanding position quantity can be followed by a rebound after pressure
subsides. OI does not identify liquidations, which side closed, leverage or
forced versus voluntary activity. Continuing stress and permanent impact are
competing explanations. A positive recent price move and a nonnegative latest
OI poll provide weak confirmation; neither proves exhaustion. Parameters below
are fixed round-number engineering hypotheses, not coefficients estimated from
this already examined year's returns or a replication of published profit.

Native universe in deterministic priority order: BTCUSDT, ETHUSDT, DOGEUSDT,
1000PEPEUSDT, SOLUSDT, XRPUSDT, LINKUSDT, ADAUSDT. Native bundle quantities and
marks remain distinct from PEPE spot units. All assets are eligible. Executed
DOGE and PEPE participation must be demonstrated, never inferred from the list.

On a five-minute review boundary, while actually flat with no live orders and
outside cooldown, admit the first currently eligible instrument in that fixed
order. Require valid finite delayed observations, one-hour native quantity OI
change <= −2%, latest five-minute quantity OI change >= 0, one-hour price return
<= −1.5%, and fifteen-minute price return >= +0.3%. Discard other simultaneous
candidates; no ranked winner, queued proposal or future retry of stale intent.
Buy native units with at most 10% of fresh observed account equity divided by
the latest known native close, floored exactly to the native lot step. Orders
use actual minimum quantity/notional rules and fresh collateral admission.
One active instrument at a time; no short sleeve, artificial hedge or transfer.

Entry is a market GTC order with a five-minute deadline after activation;
partial or failed entry triggers cancellation and actual reduce-only cleanup.
Successful entry completion requires the full target native quantity and
resolved entry order. Exit when four hours have elapsed after the actual final
entry fill, the known closed price is at least 2% below actual entry fill VWAP,
or a necessary positioning observation becomes invalid/stale. Risk and exit
checks run each minute. No profit target. Failed admission, engine risk events,
partial failures and aborted positions remain visible and cannot be silently
retried. After actual flat plus resolved orders, wait one hour before a new
admission. Cleanup persists without stacking orders; unresolved native dust or
rejection remains an explicit blocked state, not a fabricated terminal close.

Request terminal cleanup ten minutes before each phase end. Stop new entries
four hours and ten minutes before the end. Automatic end-of-data cancellation
cannot substitute for actual flat, and no fill may be invented at the endpoint.

## Timing and data assumptions

The fixed raw window is [2025-10-05 00:00 UTC, 2026-10-05 00:00 UTC). No outside
warmup. Metric archive labels are interpreted as UTC. Their content-period,
original historical delivery, unit convention and vintage remain unverified.
Assume availability at label plus five minutes for possible period completion,
plus one processing minute. Use STRICTLY earlier assumed availability, so a
label becomes eligible on the label+7m callback. A fixed eleven-minute delay
sensitivity first permits label+12m; this cannot validate unknown revisions or
original latency. No interpolation. Carry the latest source only within five
minutes of its assumed availability. Require exact complete native source grids.

Trade candle close is available at minute start+2m, at or before the callback.
Price changes use two such completed prices, without future closes or matched
OI valuation-price inference. Quantity changes use exact 12/1 source polls;
within-native constant unit scaling cancels. Quote-valued OI and archived
account/taker ratios are not predictors. Archive integrity is a data claim,
not a point-in-time causal claim. Record labels and assumed availability apart.

## Evaluation and costs

One actual 100,000-USDT common cross-margin account, linear native perpetuals,
leverage one, maximum gross leverage 0.5 and marked position fraction 0.25.
Actual source marks and settled funding cash flows remain enabled. Current
venue instrument rules approximate historical rules and must be disclosed.
Uniform taker fee 5bps and adverse slippage 8bps per side; volume-aware partial
capacity 5% of prior completed volume, baseline execution delay zero bars.
Joint cost stress: 10bps fee, 16bps slippage, capacity 2.5%, delay one bar,
plus the fixed eleven-minute assumed metric availability. Fixed fee/slippage
round trip is 26bps base and 52bps stress before ticks, funding and failures.

First six months are history only, with no fitted parameters or selection.
Fresh monthly validation accounts: April5–May5, May5–June5, June5–July5 2026.
Final-quarter July5–October5 uses a fresh continuous account, plus a separate
joint-stress account over the same quarter. All this year has already been
examined; these are reused-year exploratory phases, not untouched validation.

Keep the preceding fifteen applicable success hurdles: positive compounded
validation and after exit reserve, positive evaluation and after reserve,
positive stress and after reserve; two positive evaluation months; daily
Sharpe >=0.5; complete minute drawdown <=20%; no liquidation in any phase;
at least four completed native assets; actual completed DOGE and 1000PEPE
participation; at least two completed baskets (here single-instrument episodes); every actual endpoint
flat with no live orders BEFORE automatic cancellation. Final gate definitions
must be copied exactly from the preceding execution source during runner review,
not changed to match results. Conditional seven-day bootstrap diagnostics use
10,000 resamples, seed42 and disclosed 28-comparison tails; they cannot establish
absence of overfitting or repair repeated research on the same year.

Source execution and independent financial replay must prove actual admission,
native fills, funding, cash, fees, collateral, phase boundaries and endpoints.
A recorded-policy audit must state omissions it cannot reconstruct. Preserve
all zero-activity, partial, losing and stress runs. A pass is exploratory
historical evidence, never proof of four or five independent durable edges.
