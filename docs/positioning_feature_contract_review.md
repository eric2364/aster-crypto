# Independent positioning feature contract review

6 October2026. This is prospective feature-design review after the data-only integrity audit and failed candidate27. Current result is0/27. No historical predictor, economic fit, outcome scan, source edit or model execution was performed. The old feasibility memo's0/26 status and sample-only collection paragraphs describe its earlier stage; the authoritative [full dataset audit](positioning_dataset_audit.md) now certifies2,920 current archive/checksum/receipt pairs and840,960 normalized observations, not historical availability or units.

## What the evidence establishes

The exact eight native symbols, source labels, sorted five-minute grid, positive finite values, raw row identity and current published archive bytes have been independently reconstructed. Neither sorting nor a complete grid resolves what economic content belongs to a label. Today's archive receipt is a present acquisition time, not an original row receipt. Binance explicitly allows later archive corrections; matching a current CHECKSUM does not recover an earlier vintage. [Official archive update policy](https://github.com/binance/binance-public-data#updates).

Current USD-M REST documentation distinguishes total OI from OI value, labels its historical timestamp as period end, offers5m as the minimum historical interval and limits that endpoint to recent history. Those definitions do not prove the archive's offset-free `create_time` or original publication clock. The documentation calls account ratios and position ratios different measurements; the top position ratio concerns a selected top20% margin-balance population. It provides no archive-specific historical native quantity/multiplier contract here. [Binance USD-M market-data definitions](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data).

The observed currently downloaded start-labelled daily sets and ambiguous alleged historical labeling transition therefore remain compatible with uncertain content clocks. Do not shift June labels, fit an offset to returns, deduplicate conflicting vintages or choose timing by the strongest result. A content-clock investigation could compare independently timestamped original captures; today's intact files alone cannot resolve the issue.

## Exact plausible assumed availability contract

For a prospective exploratory archive test, retain raw source label `L` and original fields unchanged. Interpret offset-free labels as UTC under the already declared assumption. Add new fields in a separate sealed feature artifact; never modify raw observations or rename present HTTP receipt as historical receipt.

Freeze this conservative **assumption**, not an established exchange fact:

- `content_upper_bound = L + 5 minutes`: assume the row describes a stock snapshot or interval completed no later than one complete five-minute interval after its label.
- `assumed_available_at = content_upper_bound + 1 minute`.
- An observation can enter a decision only when `assumed_available_at < decision_time`, strictly. At minute callbacks a row labelled00:00 is first usable at00:07, not00:00,00:05 or00:06.
- Mark `availability_is_assumed=True` and record the exact policy version, source seal, label assumption and missing historical-receipt status. Do not populate a field claiming factual `historical_receipt`.
- Predeclare one longer-delay sensitivity, such as an additional fixed five minutes for every row. This would first use00:00 at00:12. Its purpose is sensitivity to an arbitrary assumption, not proof that either lag bounds actual latency. Do not select the better lag after results; both share one economic family and the predeclared reporting/gate scope.

These clocks cover the specific hypothesized five-minute start/end ambiguity **only if** the content lies within that bound and delivery takes no longer than the assumed processing delay. There is no empirical upper bound on original publication latency or revision latency. A delay of six minutes, an hour or a day cannot make a currently revised archive point-in-time. If a claim requires verified historical availability rather than assumption-conditioned exploration, that claim remains blocked until authentic original captures exist. Present acquisition receipts would truthfully put the downloaded data after the study year and cannot support then-tradable historical signals.

If authentic per-observation historical receipts are acquired later, preserve their provenance separately. Any revised feature policy must honor both the actual receipt and its chosen content-completion bound, with processing delay, and be frozen before outcomes. It must not silently override a later receipt with the assumed schedule.

## Time-series and price alignment

At any decision rebuild the usable subset from strict availability first, then calculate predecessors, differences and rolling windows. An unpublished row with an earlier label must not change an earlier predecessor, window completeness flag or contraction. Never forward-fill unknown numeric source values before applying availability. Same-time records are excluded until the next minute; timezone/unit conversions must preserve this boundary.

Use only actual contiguous five-minute source labels for a change or lookback. The first row has no contraction until its required in-year predecessor becomes usable. Missing/duplicate/off-grid observations fail or invalidate the full dependent window; never interpolate, stitch across a gap, substitute an outside-year predecessor or use a later record to repair earlier state. Require every required lookback observation, not just a count of rows. All retained decisions and inputs stay in the fixed year; rows whose assumed availability is at or beyond END do not become predictors. Under the baseline lag, the final physical five-minute label is unavailable for within-year decisions; the additional-five-minute sensitivity also excludes the penultimate label. Source integrity still includes those raw observations.

For minute execution, a usable observation may remain current only while `0 < decision_time - assumed_available_at <= 5 minutes`. In the baseline minute grid this means00:07 through00:11 for label00:00; if the next expected observation is absent,00:12 is stale and invalid. This is a prospective expiry rule, not documented publisher latency. A row appearing at five-minute frequency is one update, not five independent observations just because the strategy sees minute callbacks. Exits and risk cleanup must not depend on a newly valid OI row.

Price features need their own prior-close availability contract. If pairing a row with a completed price move, one defensible deterministic choice is the price close at the declared content upper bound `L+5m`, with its existing processing lag, and the correspondingly earlier close for the lookback. The decision must be after **both** OI and price availability. This aligns price to a modeled upper content bound; it does not establish that OI was actually sampled at that close. Preserve separate price clocks and describe this mismatch openly. Do not compare future close/high/low to an OI contraction at its raw label or choose an alignment from correlation scans.

## Quantity, value and native units

For a first quantity-contraction hypothesis use the archived `sum_open_interest` as a native source series, preferably within-instrument `log(Q_L)-log(Q_previous)` or percentage change. Constant rescaling cancels: if a PEPE quantity convention differs by1000 throughout the window, its percentage change is unchanged. This does **not** solve historical multiplier, aggregation or single-/double-sided definition breaks; those cause spurious changes and remain unverified. Require a fixed interpretation within each used lookback and disclose the absence of historical unit proof.

Do not interpret an absolute cross-asset OI number as comparable size. Do not use it to size executable orders, infer coin inventory, leverage or money at risk. Retain native `1000PEPEUSDT` source identity; Engine quantities and prices remain native bundles under their independently reviewed catalog, with no extra spot-PEPE conversion. The metric's native identity alone does not prove its quantity equals the Engine's contract unit.

`sum_open_interest_value` is a separate source field. Under a verified constant valuation convention one might decompose log value change into log quantity change plus valuation-price change. That relation is a hypothesis to check, not an established equality to our minute trade or mark close. Constant quantity with a falling value can reflect valuation rather than positions closing. `value/quantity` is an implied source valuation, not a verified synchronous mark, an execution price or a replacement source for missing prices. Never call quote-value contraction native OI contraction.

Keep account-count, top-account and top-position ratios separate; they are dimensionless population measures, not eight-asset position quantities or the whole market's direction. The taker-volume ratio describes flow rather than a position stock and overlaps an already tested flow mechanism. None should be added as an opportunistic filter to a new OI family. A minimal first feature contract can simply preserve these fields for provenance and leave them unused.

OI contraction is consistent with an aggregate position unwind, not proof of forced liquidation, distressed side or an imminent rebound. Every matched contract has counterparties. Voluntary closure, transfer/aggregation changes and market-definition changes are competing explanations. An exhaustion/reversal thesis and continuation/stress thesis are competing economic candidates, not simultaneous labels selected from outcomes.

## Required independent adversaries before freezing features

Use hand-constructed rows and minute prices, without historical outcomes:

1. A label00:00 row remains inaccessible at00:06 and becomes usable00:07; ms/us/ns precision and equivalent aware timezones preserve strict inequality. The longer-delay version becomes usable only00:12.
2. Future quantity/value/price mutations and a delayed unpublished past-label row leave every earlier feature, predecessor and validity flag unchanged. Prefix execution agrees with the corresponding full-input prefix.
3. Constant quantity with a10% value decline yields zero quantity contraction; quantity doubling with unchanged value does not yield zero contraction. Constant1000 scaling of a native quantity history leaves its dimensionless changes unchanged, while a one-time scale jump is not silently repaired.
4. No predecessor before START; reject duplicate/off-grid/naive clocks, wrong native IDs, nonpositive/nonfinite quantities and hidden normalized reseals. All lookbacks after a gap reset; a missed next update expires rather than silently extending stale carry.
5. Permuting physical archive row order preserves sorted values and original source-row provenance. Added source receipt metadata cannot fabricate a historical publication time. END-boundary unavailable rows cannot alter within-year state.
6. Price-window endpoints and availability are separately verified from known completed minute closes. Future closes/highs/lows cannot influence contraction direction, entry identity or sizing.
7. Freeze the exact new feature source, raw/normalized seals, schema, assumptions, lag variants and full-year boundaries before historical construction. An independent offline scalar verifier must reconstruct every eligible update and confirm unchanged source/input bytes before and after certification.

These tests can establish causal implementation **conditional on the declared availability/unit assumptions**. They cannot prove the assumptions, archive vintage, economic predictiveness or lack of overfitting. There is no material engineering blocker to such clearly labelled exploratory construction once an exact packet is approved. There remains a material evidentiary blocker to claiming historically verified point-in-time OI signals or a liquidation-specific mechanism. The repeatedly examined year still supplies no untouched holdout or promise of4–5 robust winners.

## Synthetic implementation review

The new pure builder `examples/positioning_research/signals.py` was reviewed before any historical feature construction. It produces within-native quantity percentage changes at one-hour and five-minute lookbacks, separately delayed one-hour/15-minute price returns, raw metric label, modeled availability and source price clocks. Latest available price returns update each minute while a metric can remain current for up to five minutes; these are not proven identical underlying sampling intervals. The five-minute quantity change is a weak stabilization observable, not evidence identifying forced liquidation. No historical values or returns were evaluated to choose it.

The initial derived-ratio overflow issue was repaired: positive finite source numbers can still divide to infinity, so derived infinities now become missing and invalidate the row. The assumed-only API also rejects boolean/string source quantities/prices and any supplied receipt/availability field that it would otherwise silently ignore. Exact eight native identities and integer delays6/11 are required. Availability is explicitly modeled in the preserved assumption attributes; `metric_available_at` must never be presented as a factual historical receipt.

The independent24-case suite and author's18 cases passed together: **42 tests in0.55 seconds**. Independent hand cases distinguish quantity contraction from declining value, test both strict lag boundaries, five-minute stabilization arithmetic, constant1000 scaling versus unrepaired scale breaks, exact timestamp precision/timezone conversion, unpublished past labels, prefix agreement, future mutations, finite-source derived overflow, unsupported receipt/numeric types, raw input preservation and source-grid violations. These are wholly synthetic; no archive, signal output, fitted threshold or economic outcome was inspected.

Reviewed builder SHA256 is recorded below. There is no remaining material causal arithmetic blocker under the declared fixed assumptions. Historical vintage/content timing and changing unit definitions remain unverified; these tests do not resolve those evidentiary limits.

`9ad4502e81141c2752d5ceb937e735aa740f9e6ddb3bfcc6b5131e6359b69078`
