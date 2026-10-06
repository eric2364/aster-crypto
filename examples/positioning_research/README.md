# Confirmed position-unwind rebound: source preparation

This is a new, **unexecuted** exploratory family. The current historical result
count remains **0/27 hurdle passes**. Candidate 28 has not generated historical
features, event counts, trading returns or a successful example. The requested
four or five robust strategies remain unestablished.

The fixed hypothesis combines native quantity-OI contraction, a completed price
decline, a subsequent price rebound and one nonnegative OI poll. It is long/cash
with one active instrument in a common wallet. It does not detect actual forced
liquidations. Its execution clock is one minute; OI source updates are five
minutes, entries are reviewed every five minutes and positions can last four
hours. This does not demonstrate one-minute scalping.

- [Draft exact economic/execution protocol](proposed_protocol.md)
- [Primary literature and mechanism limits](../../docs/positioning_economic_research.md)
- [Independent feature contract review](../../docs/positioning_feature_contract_review.md)
- [Execution assessment](../../docs/positioning_execution_assessment.md)
- [Independent coordinator source review](../../docs/positioning_strategy_review.md)
- [Independent runner source review](../../docs/positioning_runner_review.md)
- [Previously acquired dataset and independent audit](../../docs/positioning_dataset_audit.md)

## Pure feature API

`signals.py` reads no file or network resource on import. `build_features`
accepts one native instrument's already normalized minute candles and
five-minute quantity observations. Default source boundaries are exactly
2025-10-05 to 2026-10-05 UTC, exclusive at the end, with no prior-year warmup.
The native PEPE contract is `binance:perpetual:1000PEPEUSDT`.

It returns a minute-indexed frame with source labels, separately assumed
availability, the latest known native close, one-hour/fifteen-minute price
returns, one-hour/five-minute quantity changes and a finite/stale validity flag.
Only the two declared metric-delay assumptions (6 or 11 minutes) are supported.
Metrics are used strictly after availability; completed prices may be used at
availability. Source grids must be exact, complete and native. Missing or bad
observations raise errors rather than being repaired. Nonfinite derived returns
remain invalid. Receipt-like fields are rejected by this assumed-only API so a
later genuine receipt cannot be silently overridden.

These timing assumptions are a hypothetical historical live-feed reconstruction.
The archive downloaded today is not proof of then-available original values.
Unknown historical revisions, content clocks and unit-definition changes remain
material limits even when synthetic causality tests pass.

## Synthetic verification

```sh
.venv/bin/python -m pytest -q \
  tests/test_positioning_features.py \
  tests/test_positioning_features_audit.py
```

The first source review passed 42 synthetic cases, including 24 independent
adversaries. No historical outcomes were inspected. The draft runner has separate freeze, feature-generation, execution and analysis
commands. It rejects historical execution without an independent feature
certificate and binds cached phases to that certificate and publication receipt.
An exact source/input freeze privately published
before computation, independent full
historical feature reconstruction, five financial trajectories and independent
financial/policy verification are still required before result publication.
Do not call source preparation a profitable backtest or a new tested family.


## Runner interface and outstanding evidence

```sh
.venv/bin/python examples/positioning_research/run.py --help
```

The runner requires explicit `--perp-cache`, `--metrics-cache` and `--out` paths.
`--freeze-only` archives committed sources and verifies inputs; it creates no
predictor or trading result. The source reviews are complete; historical preparation still requires the
reviewed independent numerical auditor and exact published input packet. `--features-only` then requires the exact source/input
lock to have been privately published before computation, with the matching
publication receipt. `--execute` never generates features and additionally
requires `--feature-audit` from a separate complete historical reconstruction.
The independent historical feature auditor remains to be implemented and reviewed.

Two feature caches represent the fixed 6/11-minute metric-delay assumptions.
Execution uses three fresh validation months and separate baseline/stress
final-quarter accounts under the fixed fifteen hurdles. Fully entered but open
episodes do not count toward completed-asset participation. The runner records
all eight native quantities and live orders before automatic final cancellation;
sub-epsilon dust still fails actual endpoint flatness. Independent financial
and recorded-policy replay remain necessary before publishing any result.

No full-year predictor, economic event frequency, study phase, bootstrap outcome
or new historical result has been generated by this source preparation.


Final source preparation checks: **42 feature cases, 54 coordinator cases and
90 runner cases**, 186 total, passed together. The independent reviews include
24 feature, 24 coordinator and 26 runner adversaries. All use synthetic inputs.
Source preparation is complete; the exact input/source freeze and the required
independent historical reconstruction have not been run.
