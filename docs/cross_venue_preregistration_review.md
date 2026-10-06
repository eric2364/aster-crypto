# Prospective cross-venue packet integration review

The source and synthetic integration review passes, with the two identified pre-freeze runner defects repaired. It does not certify that candidate26 has been preregistered: that requires the final reviewed source commit, completed independently verified inputs, and source/input/runtime freeze before historical features or outcomes. The existing result remains 0/25. Earlier source and results remain separate.

The packet is `examples/cross_venue/proposed_protocol.md`. Component reviews are [funding signals](cross_venue_signal_review.md), [paired execution](cross_venue_execution_review.md), and [collector](cross_venue_collector_review.md). The runner is `examples/cross_venue/run.py`; independent integration tests are `tests/test_cross_venue_runner_audit.py`. All test artifacts are synthetic. No historical feature construction, input freeze, fitting, or economic run was performed by this review.

## Integration contracts

The freeze identity hashes all `aster` sources, coordinator/signals/unit/collector/protocol sources, imported residual runner and its signals/strategy, and imported Binance download helpers. It includes normalized inputs/catalogs/manifests, Binance raw archives/funding pages, Bybit raw envelopes and completed dataset seal, and numerical runtime versions. Sources are archived under relative repository paths. The freeze runs Binance verification and offline Bybit raw reconstruction, checks input identity again, and preserves the input-verification receipt. Source, raw input, runtime, archive, and receipt drift must all fail guard before feature loading or Engine execution.

Features are immutable parquet plus a receipt tied to the source lock, exact bytes, schema, and availability assumptions. Partial or altered features cannot be silently recreated. Funding loading must preserve optional historical receipts; projecting only rate/settlement/identity would falsely change delayed publication to an assumed one-minute lag. That pre-freeze bug was reproduced independently and repaired by the runner author.

The fixed cohort has three fresh-wallet validation months April5–July5, primary evaluation baseline/stress July5–October5, and alternative-valuation evaluation baseline/stress over the same evaluation dates. Exactly seven trajectories are retained; no additional scale, asset ranking, fitting, or outcome-based selection is introduced. A hidden or missing phase blocks summary construction.

Configuration is two separate 50,000-USDT cross-margin wallets at leverage one, .5 maximum venue gross leverage, .25 maximum position percentage, and one-minute equity recording. Baseline venue taker fees are 5/6bps; stress fees are 10/12bps, slippage16bps instead of8, participation2.5% instead of5%, and one additional activation bar. All sixteen native linear-USDT instruments retain independent identities, including equal 1000PEPE quantities. Fee/cost overrides are explicit modeling assumptions, not historical account-tier evidence.

The observer calls the original portfolio snapshot exactly once and returns it unchanged. It records actual post-fill quantities and venue-local cash, equity, gross exposure, available margin, and margin used. Cross-margin current-mark initial margin is distinct from the stored position entry-collateral field. Same-direction positions are entirely unmatched; opposite native quantities are matched only to their smaller absolute leg. Actual post-fill exposure, rather than pre-open callback intent diagnostics, is the trajectory evidence.

Actual funding events are clipped to inclusive begin/stop boundaries before alternative valuation. Bybit's alternative value is the latest completed within-year mark close at or before the event, including subminute event clocks and END. An event with no completed within-year predecessor cannot receive a fabricated prior-year or future close. This remains a valuation approximation, not an exchange-exact settlement tick.

Twenty-five execution outputs per trajectory are sealed, including actual six ledgers, metadata/configuration, quality/source manifests, post-fill exposure, sixteen leg/eight pair contributions, matched entries and coordinator diagnostics. Partial trajectories are preserved. Cached metadata must match the frozen coordinator/version, core source hashes, source manifest, requested phase/configuration and native fees, as well as the sealed output bytes. Reconstructed leg and pair contributions must conserve actual joint P&L. No publication should rely solely on cached aggregate metrics.

The summary retains every predeclared hurdle: validation/evaluation/stress and alternative-valuation positivity before and after indicative exit reserves; two positive anchored months; daily Sharpe >=.5; minute/funding-clock marked drawdown <=20%; no liquidation anywhere; and four actual matched pairs including both DOGE and PEPE. The reserve is diagnostic, not a second executed cash expense. Seven-day circular bootstrap intervals are conditional on the reused year, with cumulative26-comparison tails .05/52 and 1-.05/52. Independent millisecond/microsecond/nanosecond endpoint tests reconstruct those quantiles directly from known synthetic daily returns.

## Outstanding publication conditions

The independent runner suite has 22 cases. Together with the runner author's 11 cases, all 33 focused tests passed in 0.70 seconds. Reproduction:

```bash
.venv/bin/python -m pytest tests/test_cross_venue_runner.py tests/test_cross_venue_runner_audit.py -q
```

Resealed-cache regressions independently reproduced acceptance of a wrong coordinator class/version, core source hashes, and frozen manifest. The author repaired these checks, additionally verifying the exported manifest and actual execution bounds. All regressions now pass. No frozen earlier source or core was edited by this reviewer. Before actual research, retain the final commit and authoritative source/input/runtime locks. Before public numerical reporting, independently reconstruct all seven native/wallet/funding/fee/exposure trajectories and all gates/conditional diagnostics, verify complete output maps and frozen source provenance, and bind the provisional summary to a final audit receipt. The runner's summary is explicitly unpublished until that separate review.

The full Bybit year, receipt assumptions, current instrument rules, funding completeness ambiguity and settlement-mark proxies remain separate evidence limits. Observer-only memory measurements are synthetic and exclude the full Engine, bars, features and exports; they do not promise full-phase memory capacity. Nothing in this source review establishes profitable or non-overfit performance for a year already examined by 25 failed candidates.

Final assembled verification: the full repository suite passed **552 tests in 20.79 seconds** after the receipt-forwarding and cached-provenance repairs. This establishes prospective software readiness for the final source commit and input verification/freeze; it does not certify an executed candidate26 or numerical results.
