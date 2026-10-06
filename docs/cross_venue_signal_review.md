# Independent realized-funding feature review

The prospective feature implementation in `examples/cross_venue/signals.py` passes the independent synthetic causal audit. No real funding intensities, fitted values, strategy signals, or economic outcomes were calculated for this review. This is component signoff, not execution, input-freeze, or publication signoff. The proposed family is not yet a frozen/tested 26th candidate; the research status remains 0/25.

`tests/test_cross_venue_signals_audit.py` contains 29 passing cases. The fixed packet remains in `examples/cross_venue/proposed_protocol.md`. No source or core edits were made by the auditor.

## What was independently checked

The arithmetic tests generate funding rates from a known per-hour intensity at one-, two-, four-, and eight-hour cadence. They independently calculate the seven-day partial-overlap weights and verify normalization by actual elapsed duration, including recognized intervals with exactly five seconds of positive/negative jitter. A duration beyond that tolerance suppresses the feature. The weighted quantity is a rate per hour; it is neither a simple mean of settlement rates nor an assumed eight-hour conversion.

The critical causal fixture adds a previously unpublished settlement halfway through an otherwise eight-hour interval. Its settlement is in the past, but its receipt is in the future. Before receipt plus processing lag, neither its presence nor an extreme mutation of its rate changes yield, predecessor choice, coverage, or invalidity flags. Once received, the new four-hour intervals make the window mixed and correctly suppress the feature. This checks known-sequence reconstruction rather than merely mutating future settlement timestamps.

Further regressions verify:

- Full-history and prefix values agree; future rate and malformed-cadence perturbations do not change earlier features.
- Explicit receipt must not precede settlement; its processing lag is applied once. Availability equal to the decision time remains excluded, and a one-microsecond later decision includes it. Absent historical receipts produce a separately labelled settlement-plus-one-minute assumption.
- The first within-year rate contributes no predecessor interval; changing it arbitrarily leaves yield unchanged. Pre-year and post-year settlements, duplicate clocks, mixed or unknown native IDs, naive timestamps, and nonfinite rates are rejected.
- Nineteen eight-hour intervals supply 152 hours and pass startup coverage; eighteen supply 144 and fail. The 151.2-hour threshold is tested through those neighboring admissible histories rather than a fabricated impossible fractional cadence.
- The exact latest-interval-plus-ten-minute expiry passes; one microsecond later fails. An invalid interval suppresses only while it overlaps the trailing window, then ages out without a global future-history flag.
- Sixteen price/funding streams preserve venue-native identity. Native 1000PEPE prices are not rescaled. Missing price rows, wrong identity, nonminute duration, naive price clocks, and nonpositive closes fail construction.
- Source minute closes appear exactly two minutes after their interval start: completed close plus one processing minute. Later price mutations leave earlier available prices unchanged. Final closes that would become available at or after the year endpoint are excluded.
- A warmed eight-day synthetic feature frame has valid funding fields only at UTC hourly `:05`; other minutes remain NaN/false. Shortening that synthetic source window to a seven-day prefix preserves every common output row exactly.

Reproduction:

```bash
.venv/bin/python -m pytest tests/test_cross_venue_signals_audit.py -q
```

The final focused run passed 29/29 tests in 4.71 seconds.

## Interpretation and remaining limits

This implementation measures lagged, realized funding intensity. It does not recover a contractual accrual schedule or predict an announced next rate. Single-cadence windows deliberately reject genuine schedule changes along with suspected omissions. Systematic missing payments can still imitate a regular slower cadence; elapsed-time coverage and the recognized-cadence rule cannot prove source completeness. Raw pagination and collector reconstruction remain necessary, and the residual source uncertainty remains disclosed in [the collector review](cross_venue_collector_review.md).

Historical receipt times are unavailable in the current raw archive schema. A one-minute lag is a prospective modeling assumption, not a verified point-in-time observation. Current fees/rules, approximate Bybit settlement marks, independent venue margin and asynchronous execution still require the execution/runner audit. Seven-day carry extrapolation remains a fixed hypothesis rather than future cash knowledge. Passing these causal tests supplies no profitability or non-overfitting guarantee for the reused historical year.
