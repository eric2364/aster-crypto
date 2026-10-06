# Confirmed position-unwind rebound: historical research

This fixed exploratory family has completed five historical simulations and
separate independent feature, financial and scoped recorded-policy audits.
**It fails five of fifteen hurdles; qualified historical families remain 0/28.**
The requested four or five robust strategies remain unestablished.

[Audited report](../../docs/positioning_results/report.html) ·
[Financial scope](../../docs/positioning_financial_reconstruction.md) ·
[Recorded-policy scope](../../docs/positioning_policy_review.md).

The fixed source window is 2025-10-05 to 2026-10-05 UTC, exclusive at the end.
Compounded validation is +0.2145%, baseline final quarter −0.1801%, and joint
cost/delay stress −0.8612%. Baseline has 16 actually completed closed episodes
across ADA, DOGE, LINK and native 1000PEPE; all five accounts end truly flat.
Neither positive asset attribution nor activity makes this a qualified strategy.

[Historical feature evidence](../../docs/positioning_historical_features.md)
certifies all 16 streams and 8,409,568 minute rows exactly, after the privately
published source/input freeze and reviewed independent auditor source.

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
The exact source/input freeze was privately published before computation;
independent full historical feature reconstruction passed. Five financial trajectories and separate financial/scoped recorded-policy
verification have completed; the audit-gated presentation is published.
Feature certification does not establish profitability.


## Runner interface and outstanding evidence

```sh
.venv/bin/python examples/positioning_research/run.py --help
```

The runner requires explicit `--perp-cache`, `--metrics-cache` and `--out` paths.
`--freeze-only` archives committed sources and verifies inputs; it creates no
predictor or trading result. The source reviews and published exact input packet are complete. `--features-only` then requires the exact source/input
lock to have been privately published before computation, with the matching
publication receipt. `--execute` never generates features and additionally
requires `--feature-audit` from a separate complete historical reconstruction.
The independent historical feature auditor is implemented, reviewed and has
certified the full historical packet; see its certificate and commands below.

Two feature caches represent the fixed 6/11-minute metric-delay assumptions.
Execution uses three fresh validation months and separate baseline/stress
final-quarter accounts under the fixed fifteen hurdles. Fully entered but open
episodes do not count toward completed-asset participation. The runner records
all eight native quantities and live orders before automatic final cancellation;
sub-epsilon dust still fails actual endpoint flatness. Independent financial and scoped recorded-policy replay have now completed;
the published report preserves their separate boundaries and limitations.

Full-year features, account arithmetic and recorded policy are separately
certified. The published report retains all negative outcomes and the bounded
policy scope; it does not prove every cleanup transition or omitted abort.


Original source preparation checkpoint: **42 feature cases, 54 coordinator cases and
90 runner cases**, 186 total, passed together. The independent reviews include
24 feature, 24 coordinator and 26 runner adversaries. All use synthetic inputs.
Source preparation, exact input/source freeze and full independent historical
feature reconstruction are complete. The feature auditor passed a separate
89-case synthetic suite before actual reconstruction.


## Independent historical feature audit

The certificate is preserved at
[audit/positioning_feature_evidence.json](../../audit/positioning_feature_evidence.json).
For a fresh verification, use a new certificate path rather than overwriting it:

```sh
.venv/bin/python audit/verify_positioning_features.py \
  --source-anchor 290c9b755290a382d696ac86f83a1fbec7ee1fe5 \
  --input-anchor 7aa7830878821ed4819f2b2feac51cbd9fe1e82c \
  --certificate results/positioning-rebound-1y-v1/fresh-feature-audit.json
```

These default cache/output paths refer to the original preserved one-year study.
The audited experiment itself remains bound to its original certificate bytes.
Current archive integrity and exact calculations do not verify original delivery
or revisions; all results remain conditional exploratory research.


## Reproduce the preserved study

```sh
.venv/bin/python examples/positioning_research/run.py \
  --perp-cache data_cache/minute-perpetual-1y \
  --metrics-cache data_cache/positioning-metrics-1y \
  --out results/positioning-rebound-1y-v1 \
  --execute --feature-audit audit/positioning_feature_evidence.json
```

Complete cached phases are verified rather than silently replaced. Preserve all
original sources, data and certificates; incomplete or changed packets fail.
For independent fresh audits, follow the linked feature, financial and policy
guides with new certificate destinations. Do not replace the original study's
certificate bytes with newly dated copies. The [publication guide](../../docs/positioning_publication.md)
explains how to generate a separate fresh report from the preserved packet.
The original receipts remain unchanged and their publication flags retain their
individual audit scope. The composed report does not broaden either audit.

Final repository verification: **1,521 tests passed in 90.24 seconds** after the
feature, financial, recorded-policy and publication review additions.
