# Candidate 28 independent financial reconstruction

`audit/verify_positioning_outputs.py` is a standalone financial verifier for the fixed confirmed native position-unwind rebound experiment. Source review and synthetic tests do not execute or inspect historical strategy outcomes. A historical certificate is produced only by a separately authorized run against completed, preserved phase packets.

The current execution source anchor is `290c9b755290a382d696ac86f83a1fbec7ee1fe5`; the privately published pre-feature input anchor is `7aa7830878821ed4819f2b2feac51cbd9fe1e82c`. The original source/input packet remains unchanged. Its exact graph has 43 sources, 308 perpetual raw/normalized inputs and 8,779 positioning inputs. The verifier checks these counts against the Git-anchored preregistration rather than accepting a caller's replacement packet.

## Independence and arithmetic

The verifier imports no Engine, portfolio, strategy, signals, downloader or production runner. It reuses the unchanged independent arithmetic and descriptive metric helpers in `audit/verify_funding_rank_outputs.py`, with that helper's source hash pinned throughout verification. Its event reconstruction adapts the independent reference loop solely to expose additional pre-callback provenance; the old helper and old studies are not edited. Separate synthetic differential checks compare both implementations.

For each of the three validation months and the baseline/stress final-quarter accounts, it reconstructs the native linear perpetual wallet from the preserved minute trade/mark sources, actual settlement sources, accepted immutable orders and actual fills. Opening a derivative does not debit its notional principal. Cash changes through realized price P&L, actual fees, settled funding and liquidation charges; equity adds native marked unrealized P&L. Diagnostic slippage is already embedded in execution prices and is not subtracted again.

The replay checks adverse execution ticks, five/ten-basis-point taker fees, eight/sixteen-basis-point per-side slippage, prior-completed-volume capacity of 5%/2.5%, zero/one-bar activation delay, native lot/minimum rules, reduce-only closes, cross-margin admission limits and the actual funding sign and valuation mark. It reproduces every minute and settlement equity clock, all 63 exposure-observer fields, trades, remaining positions, entry collateral allocation, current-mark initial margin, maintenance margin, realized/unrealized P&L, turnover and all eight leg contributions. Native `1000PEPEUSDT` remains in bundle units throughout.

Quantity checks also walk individual fills, so intermediate fills cannot open a short or simultaneously hold multiple native instruments. Listed completed episodes require an actual full positive target, accepted entry-order identities, actual last entry fill within its deadline, actual entry VWAP, observed full native inventory, actual subsequent full sell quantity and actual flat observation. Failed or merely entered/open episodes cannot count. The compatibility `completed_baskets.json` must exactly equal `completed_episodes.json`; these are single-instrument episodes, not four-leg baskets. Successful closure diagnostics and the completion export must agree without missing or duplicated generations.

The final inventory gate uses exact nonzero classification from the full observer, including dust that a filtered positions export could omit. Terminal live-order IDs, immutable fields, remaining quantity, partial/accepted state and first eligible minute must reproduce from public order events. Orders captured before automatic end-of-data cancellation remain unresolved for the financial gate; a later cancellation cannot be presented as an executed close.

## Packet and summary integrity

Each phase has exactly the expected 26 named exports and a completion seal. The verifier checks CSV/Parquet equivalents, immutable phase parameters, exact native instruments/configuration, executed core hashes, runtime metadata, input serialization hashes and source-manifest identity. It independently reproduces descriptive metrics, indicative exit reserves, endpoint-adjusted daily returns, all fifteen unchanged success gates and the conditional circular seven-day bootstrap with 10,000 draws, seed 42 and tails `0.05/56` and `1−0.05/56`. Anchored evaluation months come from the complete equity series. Short/invalid bootstrap input retains the prescribed unavailable result.

Before the first provenance validation, the verifier pins its own code, its arithmetic helper, the causal feature auditor, preregistration, every common receipt, all raw/normalized input hashes, every archived/current execution source, all sixteen feature files, every phase export/completion and the summary. It checks the initial pin immediately after provenance validation, after each reconstructed phase and after the final source/runtime checks. Thus an earlier phase, helper, publication receipt or feature packet cannot change during later reconstruction and acquire a new apparent seal. Certificate digests retain the initial pinned identities.

The independent feature certificate must bind the same source/input Git anchors, source lock, feature receipt, publication/input-verification receipts, all eight native streams at both six/eleven-minute delays, full reconstruction scope, current feature-auditor/raw-dataset-helper hashes and a completion time after feature packet creation. A financial replay does not replace that feature reconstruction. Perpetual raw sources remain bound to the complete immutable input map and prior verification; this auditor does not claim a second independent raw perpetual normalization implementation.

## Certificate scope and execution

The returned financial certificate sets `complete`, `financial_reconstruction_complete` and `complete_financial_scope` to true **only after the financial checks finish**. It explicitly sets `policy_reconstruction_complete`, `recorded_policy_reconstruction_complete` and `publication_ready` to **false**. A separately reviewed and executed positioning policy auditor/certificate must gate result publication. This financial verifier does not infer that every omitted admission, invalid/stale feature refusal, cooldown, cleanup or lifecycle branch obeyed the policy merely because the account arithmetic reconciles.

The replay exposes `state.preopen_detail[clock]` with native `marks`, `average_prices` and `liquidation_before_callback`, alongside `preopen` quantities and `state.preopen_account`. These describe the stage after previous-minute closes and same-clock settlements/forced closes, before the strategy callback and current-minute open fills. They are available for a separate all-minute policy reconstruction; exporting them does not constitute that reconstruction.

After the five actual fixed phase packets and summary exist, an authorized offline run can use:

```bash
.venv/bin/python audit/verify_positioning_outputs.py \
  --perp-cache data_cache/minute-perpetual-1y \
  --metrics-cache data_cache/positioning-metrics-1y \
  --out results/positioning-rebound-1y-v1 \
  --source-anchor 290c9b755290a382d696ac86f83a1fbec7ee1fe5 \
  --input-anchor 7aa7830878821ed4819f2b2feac51cbd9fe1e82c \
  --feature-audit audit/positioning_feature_evidence.json \
  --receipt audit/positioning_output_evidence.json
```

The CLI refuses to overwrite an existing certificate; a subsequent verification needs a new receipt path. Import and `--help` create no certificate or simulation. Preparation tests use synthetic sources exclusively:

```bash
.venv/bin/python -m pytest -q \
  tests/test_positioning_financial_audit.py \
  tests/test_positioning_financial_review.py
```

The author suite has 64 passing cases covering native wallet/funding reconstruction, DOGE/1000PEPE and partial failures, a real tiny Engine/export packet, forged cash/margin/fees/volume/activation/native identities, false or omitted completed episodes, terminal order classification, stale or substituted feature certificates, symlinks, and initial/later-phase evidence mutation. Independently authored source/differential/adversarial review is recorded separately in [the financial review](positioning_financial_review.md). Synthetic financial correctness is not historical profitability evidence.

Original OI delivery/vintage and historical unit continuity remain unverified. Current native instrument rules approximate historical rules. Candle-based modeled execution cannot establish stressed market depth or deployable capacity. The already examined year remains exploratory; bootstrap confidence diagnostics cannot undo adaptive research. A complete financial certificate therefore certifies a specified reconstruction, not liquidation identification, predictive profitability, independent durable edges or absence of overfitting.
