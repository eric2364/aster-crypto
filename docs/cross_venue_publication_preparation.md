# Cross-venue publication gate: preparation only

The new publisher is separate from the frozen candidate26 research sources. It does not collect data, build features, fit, run Engine or change thresholds. No numerical result is published by this preparation.

After root confirms that the seven executions and three independent audits are final:

```sh
.venv/bin/python examples/cross_venue/publish.py \
  --binance data_cache/minute-perpetual-1y \
  --bybit data_cache/minute-bybit-1y \
  --out results/cross-venue-funding-1y-v1 \
  --financial-audit audit/cross_venue_output_evidence.json \
  --feature-audit audit/cross_venue_feature_evidence.json \
  --no-admission-audit audit/cross_venue_no_admission_evidence.json \
  --destination docs/cross_venue_results
```

The destination must not exist and must be outside the sealed experiment directory. Earlier reports are preserved; choose a fresh destination for a subsequent publication. All three audits must be separate files and complete with no errors, pinning the same current source-lock, feature parquet and feature-receipt SHA256.

The financial certificate additionally requires `trajectory_reconstruction_passed=true`, `summary_reconstruction_passed=true`, `execution_fill_reconstruction_passed=true`, `separate_wallet_reconstruction_passed=true`, exact summary SHA256, and a `trials` map covering precisely the seven fixed phases. Each phase must pin exactly the 25 runner outputs, for 175 total file hashes. All three certificates must identify the exact frozen source anchor `98fe45a55866ccfd1fa5a4e68deb52a127ff7ff2`, include `source_unchanged_during_audit=true`, and pin `auditor_sha256` to the current bytes of their respective independent audit implementation (`audit/verify_cross_venue_outputs.py` `audit/verify_cross_venue_features.py` or `audit/verify_cross_venue_no_admission.py`). Auditor changes require a new reconstruction certificate. The feature certificate additionally requires `auditor_source_unchanged=true`, exact input-freeze anchor `1820b8278bfae8a3775fce3b0ee15be8ac2a5448` and `reference_reconstruction_passed=true`; its independent scope is feature and availability reconstruction, not financial certification.

The third certificate is a narrowly scoped zero-activity cohort proof: every eligible hourly pair decision must fail an independently calculated, quantity-cancelled carry/cost bound that ignores minimum-size and margin rejections. It pins the summary, feature certificate and all 175 outputs, verifies every native inventory and both wallets remain cash-only, and requires zero economic admissions. It does not certify generic strategy decisions or GTC cleanup for a future trading cohort. The financial certificate similarly certifies recorded fills and cash trajectories, not omitted strategy decisions.

Before creating the report and again immediately before promoting its staged directory, the publisher checks the frozen source/data/runtime guard, immutable features, all175 export hashes, cached phase identity/configuration/instruments/coordinator/core source provenance, exact source/valuation manifest, summary metrics against phase metrics, the exact 15 Boolean gate names, and all three audit receipt hashes. The staged summary and receipt copies must remain byte-identical to their audited inputs. Failure removes the staging directory and does not produce a final publication. This is a reproducibility gate, not a cryptographic authentication system for audit authors.

The compact publication contains responsive offline Plotly plots of marked combined and venue equity, full-clock drawdown and separate-wallet margin/gross exposure; all seven scores and gates; 56 phase-pair and112 phase-leg contribution rows; unmatched exposure duration/peak/terminal inventories; exact summary and source lock; all three original audit receipts; feature/source verification receipts and the archived prospective protocol. The publisher captures its own bytes before staging, archives them as `executed_publisher.py`, and requires its source to remain unchanged before promotion. A publication manifest seals every published file and identifies that captured publisher implementation separately from the frozen economic code.

Charts sample about2,000 observations while retaining endpoints and global equity/drawdown extrema. Metrics and audits use complete minute and settlement clocks. Unmatched duration is calculated from actual post-fill snapshot state intervals, not callback intent. Full raw ledgers remain in the local sealed experiment directory and are not duplicated into the compact report.

The report identifies one additional exploratory economic family, candidate26, on a year already examined through25 earlier candidates. It discloses the distinction between actual settled funding and assumed predictor availability, approximate Bybit settlement-mark valuation, minute-bar fills and unavailable historical executable quotes, current-rule approximations, cross-venue failures, marked terminal inventory and indicative exit reserves. A pass cannot establish a fresh holdout, eliminate adaptation or prove a durable future edge. A zero-width interval on a constant account does not demonstrate trading profitability.

Synthetic checks only:

```sh
.venv/bin/python -m pytest tests/test_cross_venue_publisher.py tests/test_cross_venue_publication_audit.py tests/test_cross_venue_output_audit_review.py -q
```

These fixtures test missing/incomplete/stale audits, incorrect source/feature/summary seals, all175 output coverage, unexpected phases/files, mutations during staging, separate audit scopes and preservation of an earlier publication. They do not inspect historical features or outcomes.

## Actual publication

Root executed the guarded command above successfully after all three final certificates and independent publisher review. The compact report is now at [cross_venue_results/report.html](cross_venue_results/report.html). All 696 repository tests passed before publication. Frozen economic sources and earlier reports remained unchanged.
