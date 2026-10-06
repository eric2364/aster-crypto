# Independent positioning feature reconstruction

The standalone verifier `audit/verify_positioning_features.py` reconstructs the declared candidate 28 feature contract without importing its signals, strategy, runner, collector or Engine. Its sole reusable dependency is the earlier independent `audit/verify_positioning_dataset.py` raw ZIP auditor. This review is prospective until a separately authorized historical audit has produced its certificate. Synthetic tests use artificial sources only.

For each of the eight native Binance perpetual identities, the verifier requires every source minute and every five-minute positioning label in the fixed year, without duplicate removal, interpolation or outside-year warmup. At decision minute `n`, price comes from minute `n−2`. A positioning observation `k` is usable only when `5k + delay < n`, independently calculated with integer indexing. The two immutable delays are six and eleven minutes. Quantity changes divide native open interest by its own quantity twelve observations and one observation earlier. Price returns divide source closes sixty and fifteen minutes earlier. Nonfinite derived ratios become missing, and eligibility requires all four finite changes plus a metric age strictly positive and at most five minutes. Source labels, availability clocks, native quantities, derived values, Boolean validity, UTC index, column order and declared attributes must reproduce exactly.

The verifier binds the full source and input packet to explicit full Git commits. The current source graph and archived execution copies must match the source commit, and the input lock and verification bytes must match the independently published input commit. Publication ancestry, pre-feature/pre-trial assertions, exact source/input counts, runtime versions, both sixteen-stream feature hashes and receipt bytes are checked. It rejects extra feature files and archived source files, symlinks, changed assumptions and resealed numerical content. The earlier independent positioning dataset certificate must itself match the source commit, collector/helper hashes and original complete seal. Every original positioning ZIP, checksum and CSV is reparsed again through that independent auditor and compared to its normalized observations. Perpetual raw archives/pages and normalized sources are pinned through the complete Git-anchored input map and earlier offline input-verification receipt; this verifier does not claim a second independent perpetual raw normalization implementation.

The auditor pins all four packet files and all sixteen feature file hashes before its first provenance validation, checks them immediately afterward, checks its own and helper source hashes before and after reconstruction, and repeats all source, input, packet and feature checks at completion. Its fresh certificate includes the exact runner-required four stability flags, sixteen feature hashes, full eight-native/two-delay scope, full reconstruction flag, auditor identity/hash and UTC completion time following the feature receipt. The CLI refuses to overwrite evidence.

```bash
.venv/bin/python audit/verify_positioning_features.py \
  --source-anchor 290c9b755290a382d696ac86f83a1fbec7ee1fe5 \
  --input-anchor 7aa7830878821ed4819f2b2feac51cbd9fe1e82c \
  --out results/positioning-rebound-1y-v1 \
  --perp-cache data_cache/minute-perpetual-1y \
  --metrics-cache data_cache/positioning-metrics-1y \
  --certificate audit/positioning_feature_evidence.json
```

Run this command only after the frozen feature packet exists and the parent has authorized its offline audit. No certificate is produced during source review.

Thirty-six author tests cover hand-known return and quantity arithmetic, exact first availability at label +7/+12 minutes, five-minute age boundaries, prefix equivalence, not-yet-published past observations, future mutations, constant native scaling, millisecond/microsecond/nanosecond clocks and Parquet roundtrip, nonfinite derived arithmetic, malformed grids/identities/types, resealed feature tampering and strict namespace rejection. Fifty-three separately authored reviewer tests bring the passing targeted suite to 89 cases, including mutation during initial provenance validation. That review found and closed a first-validation receipt byte window before any historical feature generation.

Passing this audit proves reproduction under the chosen availability assumptions. Offset-free archive labels, original receipt times, original data vintage, historical quantity-definition continuity and the precise information period remain unverified. Constant native scaling cancels in relative changes; a unit-definition break does not. This audit does not certify economic forecasts, completed executions, liquidation causes, profitability or untouched prospective validation.
