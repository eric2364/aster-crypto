# Independent cross-venue feature reconstruction

`audit/verify_cross_venue_features.py` independently reconstructs the immutable feature file. It imports no model, signal, strategy, runner, or Engine module and never fits or simulates. The audited model source anchor is `98fe45a55866ccfd1fa5a4e68deb52a127ff7ff2`; the previously published input/runtime lock and verification receipt anchor is `1820b8278bfae8a3775fce3b0ee15be8ac2a5448`. A later rewritten or shortened input map cannot substitute for those exact pre-feature Git bytes.

The implementation is tested by `tests/test_cross_venue_feature_verifier.py`. Thirty adversarial synthetic tests pass, including a scanner enforcing absence of production model imports. Known reference rates establish independent overlap/per-hour arithmetic at 1/2/4/8-hour cadence, actual elapsed durations at the ±5-second tolerance, first-within-year predecessor omission, 152-hour admissible versus 144-hour insufficient coverage, expiry and invalid interval aging. An unpublished settlement in the past cannot alter the known predecessor sequence, validity, or intensity. After publication plus processing it can correctly create a mixed-cadence failure. Future gap/rate mutations preserve earlier reference values.

Synthetic feature tests reject future-price substitution, offhour values/valid flags, incorrect decision validity, extra fields, grid omissions, and altered availability assumptions. Before/after auditor-byte guards reject a changed verification implementation; a published-input-anchor fixture rejects a locally resealed shortened lock.

## Exact real-data checks

At root's readiness notice, the auditor is permitted to read the already frozen historical feature file; it does not modify that file or its inputs. The final certificate is `audit/cross_venue_feature_evidence.json`.

The verifier requires exactly 525,598 synchronized minute availability rows and 48 ordered fields for 16 native streams. Every price must equal its separately sourced native trade close from two minutes earlier: interval completion plus one processing minute. It excludes the final two source closes whose availability is at/after END. Source minute grids, durations, identities, finite positive prices, and native 1000PEPE prices remain explicit. No forward-filled missing tradable candle is accepted.

For every hourly UTC `:05` decision, each venue's reference selects only settlements with availability **strictly before** the decision. Explicit historical receipt, if present, must not precede settlement and receives one processing minute. Without such a receipt, settlement-plus-one-minute is separately recorded as an assumption. Intervals are then formed from the known endpoints, not a globally precomputed predecessor sequence.

The independent implementation calculates scalar calendar-window overlaps and uses `math.fsum` for weighted funding arithmetic. It rejects unrecognized overlapping intervals, mixed recognized cadence in the trailing 168-hour window, insufficient 151.2-hour coverage, or a newest known settlement older than its latest actual recognized interval plus ten minutes. A valid intensity is compared within 1e-15 absolute or 1e-12 relative tolerance; an invalid intensity must be NaN. Validity flags must be boolean. All nondecision-minute yield fields must be NaN and flags false.

The certificate checks every frozen input byte hash; all executed sources against the pre-feature Git source anchor and their archived copies; numerical runtime; exact pre-feature lock/verification/preregistration bytes and counts; normalized source pins, original Binance archives/funding pages, and Bybit raw-envelope pins/25-file completed seal. Feature bytes, schema and assumptions must match their receipt. These checks run before and after reconstruction. The auditor's own SHA is likewise recorded before and after; the certificate flags source stability only after equality passes.

Reproduce with the recorded frozen inputs and numerical runtime:

```bash
.venv/bin/python -m pytest tests/test_cross_venue_feature_verifier.py -q
.venv/bin/python audit/verify_cross_venue_features.py
```

## Scope and interpretation

The certificate is causal feature evidence only. It does not establish profitable economics or verify the seven financial trajectories; the independent financial auditor separately reconstructs wallets, fills, cash funding, exposure, contribution ledgers, metrics and summary gates. Publication must require both completed receipts and their exact current hashes.

Observed durations do not prove contractual earning intervals or missing-payment absence. A consistently omitted settlement could still mimic a longer regular cadence. Historical receipt times are not provided by the current archives, so the lag is an assumption. Current fee/rule and approximate funding-mark limitations remain in the component reviews. Past realized intensity is not a known future funding rate or a recovered historical schedule. The same year was already used for 25 unsuccessful candidates; this prospective source/input freeze does not create an untouched holdout or prove freedom from overfitting.

## Completed original-cohort certificate

The final actual reconstruction passed: **525,598 rows, 48 fields, 16 streams, 8,409,568 prior-price values and 140,160 hourly venue-native funding checks**. Maximum absolute difference from the independently summed valid intensity was **2.710505431213761e-20**. Every invalid/offhour field passed its NaN/false contract. The final auditor's before/after SHA was `98db1328a5d1fcf6bccb154223608e7a4f25be43e92fec6e67187505d9b2bd4f`; its source remained unchanged during verification. All 30 synthetic verifier tests passed in 0.44 seconds before this final run.

The immutable feature SHA is `04500be0fa13f39e401e519978123fa81d60b3592ea6f6a61ccb287d2e9d1c74`; the original frozen lock SHA is `a2e3a341a84e49fd2a4b1a09533dbd3b69e65aca0e8b9cc783879ccbad6b6919`. The 1820 publication pins exactly 40 executed sources and 8,814 input files before historical features existed. The certificate carries both full Git anchors, all common receipt hashes and the two equivalent auditor-source-stability fields required by the publication guards.

This is an original-cohort certificate using the published input identities, including recorded absolute paths. A relocated replication needs an explicitly documented path mapping and separate verification receipt; it cannot obtain this certificate by rewriting the published lock. No financial result is inferred from successful causal reconstruction.
